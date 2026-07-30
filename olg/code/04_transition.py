"""Code-tab Step 4 — solve the year-by-year transition path.

Run::

    uv run python scripts/04_transition.py
"""

from dask.distributed import Client

from oguk import map_transition_to_real_world, run_transition_path

from og_dashboard.reform import REFORM


def main() -> None:
    client = Client(n_workers=2, threads_per_worker=1, memory_limit="2GB")
    try:
        base_tp, reform_tp = run_transition_path(
            start_year=2026,
            policy=REFORM,
            client=client,
        )
    finally:
        client.close()

    impact = map_transition_to_real_world(base_tp, reform_tp)

    # First ten years of GDP and tax-revenue impacts.
    for i in range(10):
        print(
            f"{impact.years[i]}  "
            f"ΔGDP {impact.gdp_change[i]:+6.2f}  "
            f"ΔRevenue {impact.tax_revenue_change[i]:+6.2f}"
        )


if __name__ == "__main__":
    main()
