"""Shared, dependency-free scaffolding for the repo-level test suite.

Why this file exists
--------------------
The site scripts in this repo (``site_nav.py``, ``site_contract.py``,
``data/fetch.py``) are deliberately stdlib-only so that CI needs nothing but a
Python interpreter. These tests keep that property: the only third-party import
in ``tests/`` is pytest itself. That rules out ``bs4``/``lxml``, so this module
provides the small amount of HTML machinery the tests need — a tolerant
``html.parser`` tree, a URL resolver that understands ``vercel.json``, and the
per-file parametrisation hooks.

Why a tree and not more regexes
-------------------------------
``site_contract.check_fragment_anchors`` scrapes ``href="...#..."`` with a
regex, and that is fine for what it does. It is *not* fine for the structural
checks here: a regex counts an ``<h4>`` inside a JavaScript template string as a
real heading (``models/index.html`` has exactly that), and it cannot tell
whether an ``<a>`` has visible text or whether an ``alt=""`` image sits inside a
link that already carries its own accessible name. ``html.parser`` puts
``<script>``/``<style>`` bodies into CDATA mode for free, so parsing once and
asking structural questions of the tree removes a whole class of false
positives that would otherwise train people to ignore this suite.

The parser is deliberately forgiving. It is a link/structure checker, not a
validator: an end tag that does not match the top of the stack pops back to the
nearest matching ancestor rather than raising, so one stray ``</div>`` cannot
take the whole suite down.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Directories that never contain reviewable public HTML. ``vendor/`` is
# third-party (MathJax, fonts) and is excluded by the task brief; ``.git`` is
# not source. Everything else — including generated pages such as
# ``notes/releases/`` — is in scope, because a generator can emit a broken page
# just as easily as a human can write one.
EXCLUDED_DIRS = {".git", "vendor", "node_modules", ".venv", "venv"}

# Elements that have no closing tag. Needed so the tree builder does not treat
# `<img>`/`<meta>`/`<br>` as opening a scope that swallows their siblings.
VOID_ELEMENTS = frozenset(
    {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }
)

# Elements whose text content is code, not prose: never counted as headings,
# link text, or ids.
RAW_TEXT_ELEMENTS = frozenset({"script", "style"})


# --------------------------------------------------------------- HTML tree

@dataclass
class Node:
    """One element (or text run) in a parsed page."""

    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    line: int = 0
    text: str = ""
    children: list["Node"] = field(default_factory=list)
    parent: "Node | None" = field(default=None, repr=False)

    def descendants(self):
        for child in self.children:
            yield child
            yield from child.descendants()

    def ancestors(self):
        node = self.parent
        while node is not None:
            yield node
            node = node.parent

    def visible_text(self) -> str:
        """Text a sighted user reads, with script/style bodies removed."""
        if self.tag == "#text":
            return self.text
        if self.tag in RAW_TEXT_ELEMENTS:
            return ""
        return "".join(child.visible_text() for child in self.children)


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#root")
        self._stack = [self.root]

    def _append(self, tag: str, attrs) -> Node:
        node = Node(
            tag=tag,
            attrs={key: (value or "") for key, value in attrs},
            line=self.getpos()[0],
            parent=self._stack[-1],
        )
        self._stack[-1].children.append(node)
        return node

    def handle_starttag(self, tag, attrs):
        node = self._append(tag, attrs)
        if tag not in VOID_ELEMENTS:
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self._append(tag, attrs)

    def handle_endtag(self, tag):
        if tag in VOID_ELEMENTS:
            return
        # Tolerant close: pop back to the nearest matching ancestor. An end tag
        # with no open counterpart is ignored rather than fatal.
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    def handle_data(self, data):
        if data.strip():
            node = Node("#text", line=self.getpos()[0], parent=self._stack[-1])
            node.text = data
            self._stack[-1].children.append(node)


def parse_html(source: str) -> Node:
    builder = _TreeBuilder()
    builder.feed(source)
    builder.close()
    return builder.root


# --------------------------------------------------------------- pages

@dataclass
class Page:
    """A single public HTML file plus everything the tests ask of it."""

    path: Path

    def __post_init__(self) -> None:
        self.rel = self.path.relative_to(ROOT).as_posix()
        self.source = self.path.read_text()
        self.lines = self.source.splitlines()
        self.tree = parse_html(self.source)
        self.nodes = list(self.tree.descendants())

    def __str__(self) -> str:  # pragma: no cover - identifiers only
        return self.rel

    @property
    def url(self) -> str:
        """The page's canonical site path under ``cleanUrls``.

        ``index.html`` -> ``/``; ``models/index.html`` -> ``/models``;
        ``reports/x.html`` -> ``/reports/x`` (Vercel serves and 308-redirects
        the ``.html`` form to the extension-less one).
        """
        relative = self.path.relative_to(ROOT)
        if relative.as_posix() == "index.html":
            return "/"
        if relative.name == "index.html":
            return "/" + relative.parent.as_posix()
        return "/" + relative.with_suffix("").as_posix()

    def elements(self, *tags: str) -> list[Node]:
        wanted = set(tags)
        return [node for node in self.nodes if node.tag in wanted]

    def ids(self) -> dict[str, int]:
        """Every ``id`` on the page mapped to the line that declares it.

        Read off the tree, so an id in a JavaScript template string is not
        mistaken for one that exists in the served document.
        """
        found: dict[str, int] = {}
        for node in self.nodes:
            identifier = node.attrs.get("id")
            if identifier and identifier not in found:
                found[identifier] = node.line
        return found

    def line_of(self, needle: str) -> int:
        """First 1-based line containing ``needle``; 0 when absent.

        Used to point a failure at a spot the reader can open, for checks whose
        subject is a raw string (a doctype, a canonical href) rather than a node.
        """
        for number, line in enumerate(self.lines, start=1):
            if needle in line:
                return number
        return 0


def html_paths() -> list[Path]:
    return sorted(
        path
        for path in ROOT.rglob("*.html")
        if not set(path.relative_to(ROOT).parts) & EXCLUDED_DIRS
    )


_PAGE_CACHE: dict[Path, Page] = {}


def load_page(path: Path) -> Page:
    """Parse each page at most once per session — every page, many tests."""
    if path not in _PAGE_CACHE:
        _PAGE_CACHE[path] = Page(path)
    return _PAGE_CACHE[path]


# --------------------------------------------------------------- routing

@dataclass
class Site:
    """The repo as Vercel serves it: clean URLs plus the redirect table."""

    root: Path = ROOT

    def __post_init__(self) -> None:
        config = json.loads((self.root / "vercel.json").read_text())
        self.clean_urls = bool(config.get("cleanUrls"))
        self.trailing_slash = bool(config.get("trailingSlash"))
        # Vercel matches ``source`` exactly, so /papers and /papers/ are two
        # separate rules and both are listed in vercel.json. Key on the literal.
        self.redirects: dict[str, str] = {
            rule["source"]: rule["destination"]
            for rule in config.get("redirects", [])
        }

    # -- origin ---------------------------------------------------------
    @property
    def origin(self) -> str:
        """Canonical origin, read from sitemap.xml rather than hardcoded.

        The deployment domain is expected to change. Deriving it from the one
        file that must list it means a domain move is a one-line edit that the
        suite follows, instead of a literal buried in five assertions.
        """
        sitemap = (self.root / "sitemap.xml").read_text()
        first = re.search(r"<loc>([^<]+)</loc>", sitemap)
        assert first, "sitemap.xml contains no <loc> entries to derive the origin from"
        return first.group(1).rstrip("/")

    # -- resolution -----------------------------------------------------
    @staticmethod
    def split(url: str) -> tuple[str, str]:
        """``/a/b?x=1#frag`` -> (``/a/b``, ``frag``)."""
        path, _, fragment = url.partition("#")
        path = path.split("?", 1)[0]
        return path, fragment

    def canonicalise(self, path: str) -> str:
        """Apply ``trailingSlash: false`` — ``/economy/`` is served as ``/economy``."""
        if path in ("", "/"):
            return "/"
        if not self.trailing_slash:
            path = path.rstrip("/") or "/"
        return path

    def follow_redirects(self, path: str) -> tuple[str, str]:
        """Resolve a path through the redirect table.

        Returns the final path and any fragment the redirect destination adds
        (``/papers`` -> ``/models#evidence`` contributes ``evidence``). Bounded
        so a redirect loop fails as a broken link rather than hanging CI.
        """
        fragment = ""
        for _ in range(10):
            destination = self.redirects.get(path)
            if destination is None:
                return path, fragment
            path, new_fragment = self.split(destination)
            fragment = new_fragment or fragment
        return path, fragment

    def file_for(self, path: str) -> Path | None:
        """The file Vercel would serve for a site-absolute path, or None."""
        path = self.canonicalise(path)
        if path == "/":
            index = self.root / "index.html"
            return index if index.is_file() else None
        if not path.startswith("/"):
            return None
        relative = path.lstrip("/")
        # Reject traversal rather than letting it escape the repo.
        if ".." in Path(relative).parts:
            return None
        exact = self.root / relative
        if exact.is_file():
            return exact
        if self.clean_urls:
            extensionless = self.root / (relative + ".html")
            if extensionless.is_file():
                return extensionless
        index = exact / "index.html"
        if index.is_file():
            return index
        return None

    def resolve(self, url: str) -> tuple[Path | None, str]:
        """Full resolution of an internal link: redirects then filesystem.

        Returns ``(file, fragment)``. ``file`` is None when nothing on disk can
        serve the URL. A link to a redirect *source* is legitimate, so the
        redirect is followed and the destination is what has to exist.
        """
        path, fragment = self.split(url)
        path, redirect_fragment = self.follow_redirects(self.canonicalise(path))
        return self.file_for(path), fragment or redirect_fragment


# --------------------------------------------------------------- data store

def vintage_paths() -> list[Path]:
    return sorted((ROOT / "data" / "vintages").glob("*/*/*.json"))


def series_dirs() -> list[Path]:
    """One directory per stored series: ``data/vintages/<source>/<series>/``."""
    return sorted(
        path
        for path in (ROOT / "data" / "vintages").glob("*/*")
        if path.is_dir() and any(path.glob("*.json"))
    )


# --------------------------------------------------------------- fixtures

def pytest_generate_tests(metafunc):
    """Parametrise per-file so a failure names the file in its test id.

    Done here rather than with ``@pytest.mark.parametrize`` in each module so
    the test files never have to import this conftest — pytest imports two
    ``conftest`` modules in this repo (``tests/`` and ``integration/tests/``)
    and cross-importing one by name is a trap.
    """
    if "page" in metafunc.fixturenames:
        paths = html_paths()
        metafunc.parametrize(
            "page",
            [load_page(path) for path in paths],
            ids=[path.relative_to(ROOT).as_posix() for path in paths],
        )
    if "vintage_path" in metafunc.fixturenames:
        paths = vintage_paths()
        metafunc.parametrize(
            "vintage_path",
            paths,
            ids=[path.relative_to(ROOT / "data" / "vintages").as_posix() for path in paths],
        )
    if "series_dir" in metafunc.fixturenames:
        dirs = series_dirs()
        metafunc.parametrize("series_dir", dirs, ids=[path.name for path in dirs])


@pytest.fixture(scope="session")
def site() -> Site:
    return Site()


@pytest.fixture(scope="session")
def pages() -> list[Page]:
    return [load_page(path) for path in html_paths()]


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return ROOT
