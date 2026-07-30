"""Code-tab Step 5 — the fields map_transition_to_real_world returns.

Reference file: run after 04_transition.py has produced base_tp / reform_tp.
The mapping is GDP-anchored: one scale factor (real-world GDP / model GDP)
converts model-unit changes, with levels anchored to live ONS series and
HMRC total receipts.
"""

from oguk import map_transition_to_real_world


def describe(base_tp, reform_tp) -> None:
    impact = map_transition_to_real_world(base_tp, reform_tp)

    impact.years              # fiscal-year strings: ["2026-27", ..., "2085-86"]
    impact.gdp                # reform GDP path (£bn, per year)
    impact.gdp_change         # £bn change vs baseline, per year
    impact.tax_revenue_change
    impact.consumption_change
    impact.investment_change
    impact.government_change
    impact.debt_change

    # Interest-rate paths live on the TPI results themselves:
    base_tp.r, reform_tp.r    # baseline / reform r(t)
