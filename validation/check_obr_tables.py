"""Recompute the hand-written OBR validation figures from committed CSVs.

The anchored-levels table, the anchored-fit ranges and the free-running
endpoints on /obr/validation are typed into the page, not spliced by a
generator. This script recomputes each of them from the committed figure data
and fails if the page disagrees.

    python3 validation/check_obr_tables.py      # exits 1 on any mismatch

Sources (both written by papers/obr-macro/figures/fig_*.py):
    papers/obr-macro/figures/fig_anchored_data.csv      levels, £m/qtr
    papers/obr-macro/figures/fig_free_running_data.csv  levels, £m/qtr

Stdlib only.
"""

import csv
import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIG = ROOT / "papers" / "obr-macro" / "figures"
PAGE = ROOT / "obr" / "validation" / "index.html"
WINDOW = ("2025Q1", "2027Q4")


def rows(name):
    with open(FIG / name, newline="") as f:
        out = {r[""]: {k: float(v) for k, v in r.items() if k} for r in csv.DictReader(f)}
    lo, hi = WINDOW
    return {p: r for p, r in out.items() if lo <= p <= hi}


def pct(model, efo):
    return 100 * (model / efo - 1)


def fmt_signed(x, d=2):
    return f"{'+' if x >= 0 else '−'}{abs(x):.{d}f}%"


def expected():
    a = rows("fig_anchored_data.csv")
    fr = rows("fig_free_running_data.csv")
    lo, hi = WINDOW
    claims = []
    for label, col in (("Real GDP", "GDPM"), ("Consumption", "CONS")):
        for q in (lo, hi):
            m, e = a[q][f"{col}_model"] / 1000, a[q][f"{col}_efo"] / 1000
            dev = pct(a[q][f"{col}_model"], a[q][f"{col}_efo"])
            claims.append(
                f"{label}, {q}</th><td>{m:.1f}</td><td>{e:.1f}</td><td>{fmt_signed(dev)}</td>"
            )
        devs = [pct(r[f"{col}_model"], r[f"{col}_efo"]) for r in a.values()]
        claims.append(f"{fmt_signed(min(devs))} to {fmt_signed(max(devs))}")
        mad = sum(abs(d) for d in devs) / len(devs)
        claims.append(f"mean absolute deviation {mad:.2f}%")
    fr_devs = [abs(pct(r["GDPM_model"], r["GDPM_efo"])) for r in fr.values()]
    claims.append(f"{sum(fr_devs) / len(fr_devs):.2f} per cent mean absolute deviation")
    claims.append(
        f"contracts from {fr[lo]['GDPM_model'] / 1000:.1f} to {fr[hi]['GDPM_model'] / 1000:.1f}"
    )
    gap = (fr[hi]["GDPM_efo"] - fr[hi]["GDPM_model"]) / 1000
    claims.append(f"widens to {round(gap)} billion pounds")
    return claims


def main():
    text = html.unescape(PAGE.read_text()).replace("&minus;", "−")
    text = re.sub(r"\s+", " ", text)
    missing = [c for c in expected() if c.replace("-", "−") not in text and c not in text]
    for c in expected():
        print(("MISSING " if c in missing else "ok      ") + c)
    if missing:
        print(f"FAIL {PAGE.relative_to(ROOT)}: {len(missing)} figure(s) disagree with the CSVs")
        return 1
    print("OBR validation hand-written figures match the committed CSVs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
