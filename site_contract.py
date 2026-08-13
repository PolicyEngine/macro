"""Dependency-free contracts for high-risk public website claims."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent
# In the order the site presents them. pe-microsim leads: it is
# PolicyEngine's own engine, the only production-ready member and the only
# one covering both countries. The order here is the contract — the "model
# NN" eyebrow on every model page is checked against this tuple's index, so
# reordering the site means reordering this and nothing else.
PUBLIC_MODELS = (
    "pe-microsim",
    "obr-macro",
    "boe-svar",
    "frb-us",
    "us-hank",
    "psl-og",
    "define-uk",
)

# Public model id -> the directory holding its four pages. papers/ pages
# carry the same eyebrow and are checked too.
MODEL_PAGE_ROOTS = {
    "pe-microsim": ("pe", "papers/pe-microsim"),
    "obr-macro": ("obr", "papers/obr-macro"),
    "boe-svar": ("svar", "papers/boe-svar"),
    "frb-us": ("frb-us", "papers/frb-us"),
    "us-hank": ("us-hank",),
    "psl-og": ("olg", "papers/psl-og"),
    "define-uk": ("define", "papers/define-uk"),
}
# /docs is a permanent redirect to /models#compare in vercel.json; the model
# inventory lives on the pages below.
MODEL_INVENTORY_PAGES = (
    "index.html",
    "models/index.html",
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


    # /validation was absorbed into /models#validation; the gradient claims
    # now live on the models hub page.
    validation = _read("models/index.html")
    if "The seven models support" not in validation:
        failures.append("models/index.html: model count is not seven")

    if failures:
        raise SystemExit("\n".join(failures))


def check_economy_navigation() -> None:
    failures: list[str] = []
    overview_routes = {
        "economy/index.html": "economy-trends-figures",
        "economy/us/index.html": "us-economy-trends-figures",
    }
    for path, trends_marker in overview_routes.items():
        page = _read(path)
        for href in ('href="/economy"', 'href="/economy/us"'):
            if href not in page:
                failures.append(f"{path}: missing country link {href}")
        if 'id="trends"' not in page:
            failures.append(f"{path}: missing in-page Trends section")
        if f"<!-- {trends_marker}:begin -->" not in page:
            failures.append(f"{path}: missing generated trends block {trends_marker}")
        if page.count('class="economy-figure"') != 3:
            failures.append(f"{path}: expected three generated trend figures")
        for retired in ('href="/economy/trends"', 'href="/economy/us/trends"'):
            if retired in page:
                failures.append(f"{path}: links to retired Trends page {retired}")
        for anchor in ('id="indicators"', 'id="markets"', 'id="releases"'):
            if anchor not in page:
                failures.append(f"{path}: missing merged-section anchor {anchor}")
        if 'src="/economy/economy-nav.js"' not in page:
            failures.append(f"{path}: missing scroll-aware topic navigation")
        if path == "economy/index.html" and "ons.gov.uk/" in page:
            if re.search(r'href="https://www\.ons\.gov\.uk/[^"]+/data"', page):
                failures.append(
                    f"{path}: displayed ONS source link points to a JSON endpoint"
                )

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
        if ">Forecasts</a>" not in header:
            failures.append(f"{path}: the forecasts tab is not labelled Forecasts")

    if failures:
        raise SystemExit("\n".join(failures))


def check_editorial_consistency() -> None:
    failures: list[str] = []
    stale_claims = {
        "notes/2026-07-25-cpi-2026q2/index.html": "1992Q1–2023Q2",
        "models/index.html": "This audit covers the three macro models",
        "forecasts/index.html": "a forecast reported without one is marketing",
    }
    for path, stale in stale_claims.items():
        if stale in _read(path):
            failures.append(f"{path}: stale or redundant copy remains: {stale}")

    home = _read("index.html")
    for proof in (
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

    # The deploy script's docstring is the other place the tool inventory is
    # written out by hand, and nothing was checking it: it drifted to "20
    # tools" while the server grew to 26.
    modal_app = _read("integration/modal_app.py")
    header = modal_app.split('"""', 2)[1]
    if f"{tool_count} tools" not in header:
        failures.append(
            f"integration/modal_app.py: docstring tool count drifted — server "
            f"defines {tool_count} @mcp.tool functions"
        )

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


def check_model_ordinals() -> None:
    """The "model NN" eyebrow must match the order the site presents models in.

    pe-microsim was promoted to lead the suite, and for a while every one of
    its own pages still said "model 06" while it was card 01 on the homepage,
    the models grid and /connect. Twenty-eight pages disagreed with every
    ordered surface, and nothing caught it, because the ordinal lived only in
    hand-written prose.

    Structural rather than textual: it derives the expected number from
    PUBLIC_MODELS' index, so reordering the site is a one-line change here and
    a regeneration, not a 28-file hunt.
    """
    failures: list[str] = []
    for model, roots in MODEL_PAGE_ROOTS.items():
        expected = PUBLIC_MODELS.index(model) + 1
        for root in roots:
            for page in sorted((ROOT / root).glob("**/index.html")):
                found = re.search(r"model (\d{2}) &mdash;|model (\d{2}) —",
                                  page.read_text())
                if not found:
                    continue
                actual = int(found.group(1) or found.group(2))
                if actual != expected:
                    failures.append(
                        f"{page.relative_to(ROOT)}: eyebrow says model "
                        f"{actual:02d}, but {model} is #{expected} in "
                        "PUBLIC_MODELS"
                    )

    missing = set(MODEL_PAGE_ROOTS) ^ set(PUBLIC_MODELS)
    if missing:
        failures.append(
            f"MODEL_PAGE_ROOTS and PUBLIC_MODELS disagree on: {sorted(missing)}"
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
    check_model_ordinals()
    check_fragment_anchors()
    print("Public inventory, navigation, and editorial claims are consistent.")
