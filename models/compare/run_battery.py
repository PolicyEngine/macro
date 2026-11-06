#!/usr/bin/env python3
"""Check or refresh the cross-model battery behind /models/compare.

``results.json`` is the committed, versioned record of the "same question,
every model" battery (macro#213). Every answered cell carries the exact call
that produced it: the tool, its arguments, the date, the adapter version and,
for stored paths, the hosted ``run_at``.

    python3 models/compare/run_battery.py --check
        Validate the committed file only: schema, provenance on every cell,
        units on every number, and the identities the stored paths must
        satisfy. No model is solved.

    PYTHONPATH=integration/src python3 models/compare/run_battery.py --refresh frb-us
        Re-run the FRB/US cells that store a path through the local
        integration layer (``policyengine_macro.core.frbus_shock``, about a
        second each) and rewrite their paths, peaks and provenance.

FRB/US is the only cheap local path. US HANK needs a steady-state and
jacobian solve, and the OBR emulator a full Gauss-Seidel solve per run; both
are heavy jobs on a laptop, so their cells stay as the hosted results of
6 Nov 2026 (``run.kind`` "hosted" or "battery") and are refreshed only by
re-running the hosted tools. The BoE SVAR and DEFINE-UK cells are committed
model-repo outputs (``run.kind`` "committed"); neither model has a hosted
shock surface.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results.json"

RUN_KINDS = {"hosted", "battery", "committed"}
VERDICTS = {"plausible", "plausible-in-model", "off", "questionable", "unresolved", "not-tested"}
MODEL_ORDER = ("obr", "svar", "frb-us", "us-hank", "define")
REFRESHABLE = {"frb-us"}


def load(path: Path = RESULTS) -> dict:
    return json.loads(path.read_text())


def problems(data: dict) -> list[str]:
    """Every way the committed file falls short of its contract."""
    out: list[str] = []
    for key in ("schema", "version", "date", "models", "benchmarks", "issues", "questions"):
        if key not in data:
            out.append(f"missing top-level key {key!r}")
    if out:
        return out
    if not str(data["version"]).startswith(data["date"]):
        out.append("version must start with the run date")
    for qi, q in enumerate(data["questions"]):
        where = q.get("id", f"question {qi}")
        for bid in q.get("benchmarks", []):
            bench = data["benchmarks"].get(bid)
            if bench is None:
                out.append(f"{where}: unknown benchmark {bid}")
            elif not bench.get("source") or not bench.get("url"):
                out.append(f"{where}: benchmark {bid} has no source")
        models = [c.get("model") for c in q["cells"]]
        if tuple(sorted(models, key=MODEL_ORDER.index)) != tuple(models):
            out.append(f"{where}: cells are not in the fixed hub order")
        if set(models) != set(MODEL_ORDER):
            out.append(f"{where}: every model needs a cell (grey 'no instrument' if it cannot answer)")
        for cell in q["cells"]:
            tag = f"{where}/{cell.get('model')}"
            if cell.get("model") not in data["models"]:
                out.append(f"{tag}: unknown model")
            if cell.get("status") == "no_instrument":
                if not cell.get("reason"):
                    out.append(f"{tag}: a no-instrument cell needs its reason")
                continue
            if cell.get("status") != "answered":
                out.append(f"{tag}: status must be answered or no_instrument")
                continue
            run = cell.get("run") or {}
            if run.get("kind") not in RUN_KINDS:
                out.append(f"{tag}: run.kind must be one of {sorted(RUN_KINDS)}")
            for key in ("tool", "args", "date", "label"):
                if not run.get(key):
                    out.append(f"{tag}: run.{key} missing")
            if run.get("kind") in {"hosted", "battery"} and not run.get("adapter"):
                out.append(f"{tag}: a hosted run needs its adapter version")
            if run.get("kind") == "committed" and not run.get("source"):
                out.append(f"{tag}: a committed cell needs its source")
            if cell.get("verdict") not in VERDICTS:
                out.append(f"{tag}: verdict {cell.get('verdict')!r} not in {sorted(VERDICTS)}")
            if not cell.get("verdict_label") or not cell.get("reason"):
                out.append(f"{tag}: verdict needs a label and a reason")
            issue = cell.get("issue")
            if issue is not None and issue not in data["issues"]:
                out.append(f"{tag}: unknown issue {issue}")
            for key in ("gdp", "inflation"):
                if key in cell and not cell[key].get("units"):
                    out.append(f"{tag}: {key} has no units")
            path = cell.get("path")
            if path:
                if run.get("kind") != "hosted" or not run.get("run_at"):
                    out.append(f"{tag}: a stored path needs a hosted run_at")
                n = len(path["x"])
                for key in ("gdp", "inflation"):
                    if len(path[key]) != n:
                        out.append(f"{tag}: path.{key} length {len(path[key])} != {n}")
                    if not path.get(f"{key}_units"):
                        out.append(f"{tag}: path.{key}_units missing")
                if path.get("inflation_scale") not in (1, 4):
                    out.append(f"{tag}: inflation_scale must be 1 or 4 (quarterly to annual)")
                # The headline peak must be the path's own peak, so the table
                # and the chart can never disagree.
                if "gdp" in cell and n:
                    peak = max(path["gdp"], key=abs)
                    if abs(round(peak, 3) - cell["gdp"]["value"]) > 0.0015:
                        out.append(f"{tag}: gdp peak {cell['gdp']['value']} != path peak {peak:.4f}")
    return out


def _frbus_refresh(cell: dict) -> None:
    from policyengine_macro import core

    args = dict(cell["run"]["args"])
    result = core.frbus_shock(**args)
    rows = result["results"]
    path = cell["path"]
    path["x"] = [r["period"] for r in rows]
    path["gdp"] = [r["xgdp"] for r in rows]
    series = "pcpi" if path["inflation_units"].startswith("% deviation of the CPI") else "picxfe"
    path["inflation"] = [r[series] for r in rows]
    cell["gdp"]["value"] = round(result["peaks"]["xgdp"]["value"], 3)
    prov = result["provenance"]
    cell["run"].update(
        kind="hosted" if prov.get("run_at") else cell["run"]["kind"],
        run_at=prov.get("run_at", ""),
        adapter=prov.get("adapter_version", cell["run"].get("adapter")),
        date=str(prov.get("run_at", ""))[:10] or cell["run"]["date"],
        label=f"local run, {str(prov.get('run_at', ''))[:10]}",
    )


def refresh(data: dict, model: str) -> int:
    if model not in REFRESHABLE:
        raise SystemExit(f"{model}: not a cheap local path; re-run the hosted tool instead")
    n = 0
    for q in data["questions"]:
        for cell in q["cells"]:
            if cell.get("model") == model and cell.get("path"):
                _frbus_refresh(cell)
                n += 1
    return n


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="validate results.json; no solve")
    parser.add_argument("--refresh", choices=sorted(REFRESHABLE), help="re-run one model's stored paths locally")
    args = parser.parse_args()
    data = load()
    if args.refresh:
        n = refresh(data, args.refresh)
        RESULTS.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        print(f"refreshed {n} {args.refresh} cell(s); bump 'version' and rebuild the page")
    found = problems(data)
    for line in found:
        print(f"FAIL {line}", file=sys.stderr)
    if not found:
        cells = sum(len(q["cells"]) for q in data["questions"])
        print(f"OK — {len(data['questions'])} questions, {cells} cells, version {data['version']}")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
