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
MODEL_INVENTORY_PAGES = (
    "index.html",
    "models/index.html",
    "docs/index.html",
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
    if "six evidence guides" not in papers:
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
    for path in ("economy/index.html", "economy/us/index.html"):
        page = _read(path)
        for href in ('href="/economy/"', 'href="/economy/us/"'):
            if href not in page:
                failures.append(f"{path}: missing country link {href}")
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
        economy_position = header.find('href="/economy/"')
        if home_position == -1 or economy_position == -1:
            failures.append(f"{path}: missing Home or Economy navigation")
        elif home_position > economy_position:
            failures.append(f"{path}: Home is not the first navigation tab")
        if 'href="/notes/"' in header:
            failures.append(f"{path}: Notes remains a global navigation tab")
        if 'href="/validation/"' in header:
            failures.append(f"{path}: Evidence remains a global navigation tab")
        if 'href="/contact/"' in header:
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
        "Preserved vintages",
        "Public forecast record",
        "Honest validation",
        "Run a hosted model",
    ):
        if proof not in home:
            failures.append(f"index.html: missing primary selling point: {proof}")

    if failures:
        raise SystemExit("\n".join(failures))


if __name__ == "__main__":
    check_public_model_inventory()
    check_economy_navigation()
    check_editorial_consistency()
    print("Public inventory, navigation, and editorial claims are consistent.")
