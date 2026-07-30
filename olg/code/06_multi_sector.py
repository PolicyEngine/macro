"""Code-tab Step 6 — transition path with the 8-sector industry calibration.

Run::

    uv run python scripts/06_multi_sector.py
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
            multi_sector=True,  # 8-sector CES production
        )
    finally:
        client.close()

    impact = map_transition_to_real_world(base_tp, reform_tp)
    print(f"GDP at year 10: £{impact.gdp[10]:,.1f}bn  Δ £{impact.gdp_change[10]:+,.2f}bn")
    print(f"GDP at year 30: £{impact.gdp[30]:,.1f}bn  Δ £{impact.gdp_change[30]:+,.2f}bn")


if __name__ == "__main__":
    main()
