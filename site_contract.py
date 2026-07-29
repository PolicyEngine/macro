"""Dependency-free contracts for high-risk public website claims."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent
PUBLIC_MODELS = (
    "obr-macro",
    "boe-svar",
    "frb-us",
    "us-hank",
    "pe-microsim",
    "psl-og",
)
# /docs is a permanent redirect to /models#compare in vercel.json; the model
# inventory lives on the pages below.
MODEL_INVENTORY_PAGES = (
    "index.html",
    "models/index.html",
    "validation/index.html",
)


def _read(path: str) -> str:
    return (ROOT / path).read_text()


def check_public_model_inventory() -> None:
    failures: list[str] = []
    for path in MODEL_INVENTORY_PAGES:
        page = _read(path)
        missing = [model for model in PUBLIC_MODELS if model not in page]
        if missing:
            failures.append(f"{path}: missing {', '.join(missing)}")

    papers = _read("papers/index.html")
    if "evidence for all six models" not in papers:
        failures.append("papers/index.html: evidence-guide count is not six")
    missing_papers = [model for model in PUBLIC_MODELS if model not in papers]
    if missing_papers:
        failures.append(
            f"papers/index.html: missing {', '.join(missing_papers)}"
        )

    validation = _read("validation/index.html")
    if "The six models support" not in validation:
        failures.append("validation/index.html: model count is not six")

    if failures:
        raise SystemExit("\n".join(failures))


def check_economy_navigation() -> None:
    failures: list[str] = []
    overview_routes = {
        "economy/index.html": 'href="/economy/trends"',
        "economy/us/index.html": 'href="/economy/us/trends"',
    }
    for path, trends_href in overview_routes.items():
        page = _read(path)
        for href in ('href="/economy"', 'href="/economy/us"'):
            if href not in page:
                failures.append(f"{path}: missing country link {href}")
        if trends_href not in page:
            failures.append(f"{path}: missing dedicated Trends link {trends_href}")
        if 'id="trends"' not in page:
            failures.append(f"{path}: missing in-page Trends section")
        for country_href in (
            'href="/economy/trends"',
            'href="/economy/us/trends"',
        ):
            if country_href not in page:
                failures.append(
                    f"{path}: Trends section missing country link {country_href}"
                )
        if 'id="figures"' in page or "economy-figures:begin" in page:
            failures.append(f"{path}: duplicates charts from its Trends page")
        if 'src="/economy/economy-nav.js"' not in page:
            failures.append(f"{path}: missing scroll-aware topic navigation")
        if path == "economy/index.html" and "ons.gov.uk/" in page:
            if re.search(r'href="https://www\.ons\.gov\.uk/[^"]+/data"', page):
                failures.append(
                    f"{path}: displayed ONS source link points to a JSON endpoint"
                )

    for path in ("economy/trends/index.html", "economy/us/trends/index.html"):
        page = _read(path)
        for href in (
            'href="/economy/trends"',
            'href="/economy/us/trends"',
        ):
            if href not in page:
                failures.append(f"{path}: missing country-preserving link {href}")
        if page.count('class="economy-figure"') != 3:
            failures.append(f"{path}: expected three generated trend figures")

    for path in MODEL_INVENTORY_PAGES:
        header = _read(path).split("</header>", 1)[0]
        home_position = header.find('href="/"')
        economy_position = header.find('href="/economy"')
        if home_position == -1 or economy_position == -1:
            failures.append(f"{path}: missing Home or Economy navigation")
        elif home_position > economy_position:
            failures.append(f"{path}: Home is not the first navigation tab")
        if 'href="/notes"' in header:
            failures.append(f"{path}: Notes remains a global navigation tab")
        if 'href="/validation"' in header:
            failures.append(f"{path}: Evidence remains a global navigation tab")
        if 'href="/contact"' in header:
            failures.append(f"{path}: Contact remains a global navigation tab")
        if ">Track record</a>" not in header:
            failures.append(f"{path}: Forecasts is not labelled Track record")

    if failures:
        raise SystemExit("\n".join(failures))


def check_editorial_consistency() -> None:
    failures: list[str] = []
    stale_claims = {
        "notes/2026-07-25-cpi-2026q2/index.html": "1992Q1–2023Q2",
        "papers/index.html": "against its November 2025 forecast",
        "validation/index.html": "This audit covers the three macro models",
        "forecasts/index.html": "a forecast reported without one is marketing",
    }
    for path, stale in stale_claims.items():
        if stale in _read(path):
            failures.append(f"{path}: stale or redundant copy remains: {stale}")

    home = _read("index.html")
    for proof in (
        "No account needed",
        "Point-in-time data",
        "Scored in public",
        "Failures published",
        "Run a hosted model",
    ):
        if proof not in home:
            failures.append(f"index.html: missing primary selling point: {proof}")

    if failures:
        raise SystemExit("\n".join(failures))


def check_docs_match_code() -> None:
    """Documented tool counts and commands must match the integration code."""
    failures: list[str] = []
    mcp_source = _read("integration/src/policyengine_macro/mcp_server.py")
    tool_count = mcp_source.count("@mcp.tool")
    count_words = {18: "eighteen", 19: "nineteen", 20: "twenty", 21: "twenty-one",
                   22: "twenty-two", 23: "twenty-three", 24: "twenty-four"}
    readme = _read("integration/README.md")
    expected = count_words.get(tool_count, str(tool_count))
    if f"{expected} tools" not in readme:
        failures.append(
            f"integration/README.md: MCP tool count drifted — server defines "
            f"{tool_count} @mcp.tool functions; README must say '{expected} tools'"
        )
    for name in ("hank_shock", "hank_summary", "list_model_capabilities",
                 "get_model_status", "recommend_model"):
        if f"def {name}" in mcp_source and name not in readme:
            failures.append(f"integration/README.md: tool `{name}` undocumented")

    connect = _read("connect/index.html")
    endpoint = "https://policyengine--policyengine-macro-mcp-serve.modal.run/mcp"
    for path, page in (("connect/index.html", connect),
                       ("integration/README.md", readme)):
        if endpoint not in page:
            failures.append(f"{path}: hosted MCP endpoint URL missing or drifted")
    if "pe-macro household --country us</code>" in connect:
        failures.append(
            "connect/index.html: `pe-macro household` example omits required "
            "--people option"
        )

    if failures:
        raise SystemExit("\n".join(failures))


def check_footer_directory_is_complete() -> None:
    """Every public page must be reachable from the footer site directory.

    The directory is generated identically on all pages by site_nav.py; this
    checks it against the pages that actually exist, so adding a page without
    listing it (a 'hidden page') fails CI.
    """
    import site_nav

    listed = {href for _, links in site_nav.FOOTER_DIRECTORY for href, _ in links}
    # Pages indexed by a listed parent rather than the footer itself:
    # dated notes on /notes, paper subpages on /papers, reports on /papers.
    exempt_prefixes = ("/notes/", "/reports/", "/papers/")
    failures = []
    for page in site_nav.pages():
        url = site_nav.page_url(page)
        if url == "/" or url.startswith(exempt_prefixes):
            continue
        if url not in listed:
            failures.append(
                f"{page.relative_to(ROOT)}: {url} missing from "
                "site_nav.FOOTER_DIRECTORY — every public page must appear "
                "in the footer site directory"
            )
    if failures:
        raise SystemExit("\n".join(failures))


def check_fragment_anchors() -> None:
    """Every internal fragment link must point at an id that exists.

    Covers same-page ``href="#x"`` and cross-page ``href="/path/#x"`` links.
    This is the check that catches a section being renamed or renumbered
    while prose elsewhere still links to the old anchor.
    """
    skip_roots = {"vendor", "reveal.js", "audit", "assets", "data"}
    pages = {
        path
        for path in ROOT.rglob("*.html")
        if not any(part.startswith(".") for part in path.relative_to(ROOT).parts)
        and path.relative_to(ROOT).parts[0] not in skip_roots
    }
    ids: dict[Path, set[str]] = {
        page: set(re.findall(r'\bid="([^"]+)"', page.read_text())) for page in pages
    }

    def resolve(target: str) -> Path | None:
        candidate = ROOT / target.strip("/")
        if candidate.suffix == ".html":
            return candidate if candidate in ids else None
        index = candidate / "index.html"
        return index if index in ids else None

    failures = []
    for page in sorted(pages):
        html = page.read_text()
        rel = page.relative_to(ROOT)
        for target, fragment in re.findall(r'href="([^"#]*)#([^"]+)"', html):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            dest = page if target == "" else resolve(target)
            if dest is None:
                failures.append(f"{rel}: link to missing page {target}#{fragment}")
            elif fragment not in ids[dest]:
                failures.append(
                    f"{rel}: broken anchor href=\"{target}#{fragment}\" — no "
                    f"id=\"{fragment}\" in {dest.relative_to(ROOT)}"
                )
    if failures:
        raise SystemExit("\n".join(failures))


if __name__ == "__main__":
    check_public_model_inventory()
    check_economy_navigation()
    check_editorial_consistency()
    check_docs_match_code()
    check_footer_directory_is_complete()
    check_fragment_anchors()
    print("Public inventory, navigation, and editorial claims are consistent.")
