"""Dependency-free contracts for high-risk public website claims."""

from pathlib import Path


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


if __name__ == "__main__":
    check_public_model_inventory()
    print("Public model inventory is consistent across discovery and evidence pages.")
