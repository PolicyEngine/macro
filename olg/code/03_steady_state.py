"""Code-tab Step 3 — solve the long-run steady state under the reform.

Run::

    uv run python scripts/03_steady_state.py
"""

from oguk import map_to_real_world, solve_steady_state

from og_dashboard.reform import REFORM


def main() -> None:
    baseline = solve_steady_state(start_year=2026)
    reform = solve_steady_state(start_year=2026, policy=REFORM)

    impact = map_to_real_world(baseline, reform)

    print(f"GDP:         £{impact.gdp:,.1f}bn  ({impact.gdp_pct:+.3f}%)")
    print(f"Tax revenue: £{impact.tax_revenue:,.1f}bn  ({impact.tax_revenue_pct:+.3f}%)")
    print(f"Investment:  £{impact.investment:,.1f}bn  ({impact.investment_pct:+.3f}%)")
    print(f"Interest:    {impact.r_baseline:.2%} -> {impact.r_reform:.2%}")


if __name__ == "__main__":
    main()
