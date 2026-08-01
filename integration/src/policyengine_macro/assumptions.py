"""Macro -> micro EconomicAssumptions overlay (PolicyEngine/macro#11).

Carries the OG-UK model's long-run price changes (wages, labour supply,
interest rates) into the PolicyEngine microsimulation, so a "dynamic"
population score is the ordinary static score run under macro-adjusted
economic inputs.

DOUBLE-COUNTING INVARIANT
-------------------------
The overlay carries only the reform/baseline RATIO from the macro model,
never a level. The baseline microsim run uses the stock inputs — which
already embed the OBR forecast the OG-UK baseline is calibrated to — so the
static effect of the reform is never counted twice: a no-op macro result
(w_reform == w_baseline) produces NO modifier at all and dynamic scoring
reduces exactly to static scoring. Tests assert this.

APPLICATION MECHANISM: DIRECT INPUT SCALING (not parameter overrides)
---------------------------------------------------------------------
The factor is applied by scaling the employment-income input arrays of the
REFORM simulation only, through the engine's supported hook: a
``policyengine.core.Dynamic`` with a ``simulation_modifier`` callable,
which ``PolicyEngineUKLatest.run`` invokes on the underlying
``policyengine_uk.Microsimulation`` after construction and before any
calculation (policyengine tax_benefit_models/uk/model.py). The modifier
uses ``Simulation.set_input`` (policyengine_core) on the populated
employment-income input holder.

WHY NOT A PARAMETER OVERLAY ON THE UPRATING INDICES (empirical finding,
2026-07-20): an earlier version of this module overrode the derived index
``gov.economic_assumptions.indices.obr.average_earnings`` in the reform
dict. That mechanism is DEAD in population runs: the per-year population
datasets (e.g. enhanced_frs_2023_24-year-2026) are pre-uprated at dataset
BUILD time — ``policyengine.tax_benefit_models.uk.datasets.create_datasets``
materialises ``sim.dataset[year]`` once under stock parameters into the
per-year .h5, and ``PolicyEngineUKLatest.run`` feeds those stored input
arrays straight into ``UKSingleYearDataset`` — so simulation-time uprating
parameters are never consulted for input variables. Verified against the
production engine: two population_reform_impact calls overriding the 2026
index by x0.99 (1.66561) and then drastically to 0.84 BOTH returned exactly
zero everywhere (£0.0bn, 0 winners, 0 losers, all deciles 0.0).
"""

from __future__ import annotations

from pydantic import BaseModel

# Input variables carrying employment income, in the order tried: after
# policyengine_uk's Simulation.__init__ move_values step the dataset's
# employment income lives in employment_income_before_lsr;
# employment_income itself is kept as a fallback for data layouts that
# did not go through that step.
SCALED_INPUT_VARIABLES = ("employment_income_before_lsr", "employment_income")

# The dynamic score refuses user reforms under this prefix: uprating
# overrides there are silently dead in population runs (see module
# docstring), so accepting them would ship a plausible-looking no-op.
OVERLAY_PARAM_PREFIX = "gov.economic_assumptions."

# Earnings concepts for the shock-incidence constructors (from_frbus_result,
# from_hank_result). "wage" scales by the wage/compensation price alone;
# "wage_bill" scales by wage x hours, so the aggregate labour-income change
# is carried — uniformly, which understates the concentration of actual
# incidence in job losers (stated in caveats).
INCOME_CONCEPTS = ("wage", "wage_bill")

# Same plausibility gate for every constructor: a factor outside this band
# is a degenerate solve or a mis-sized shock, not an overlay to apply.
_FACTOR_BOUNDS = (0.5, 2.0)


def _check_factor(label: str, factor: float, source: str) -> None:
    lo, hi = _FACTOR_BOUNDS
    if not (factor == factor and lo <= factor <= hi):  # NaN-safe
        raise ValueError(
            f"implausible {label} factor {factor!r} (outside "
            f"[{lo}, {hi}]) from {source} — inspect the model run "
            "rather than applying it as an overlay"
        )


def _check_income_concept(income_concept: str) -> None:
    if income_concept not in INCOME_CONCEPTS:
        raise ValueError(
            f"income_concept must be one of {INCOME_CONCEPTS}, got "
            f"{income_concept!r}. 'wage' scales employment income by the "
            "wage price alone; 'wage_bill' also carries the hours change "
            "(applied uniformly)."
        )


class EconomicAssumptions(BaseModel):
    """Macro-model price changes expressed as microsim input adjustments.

    Steady-state comparative statics: the factors are LONG-RUN level shifts
    (reform/baseline ratios), applied flat from ``start_year`` with no
    transition dynamics — that assumption is spelled out in ``notes`` and
    must be carried into any ScoreResult built from this object.

    v1 scope (deliberately narrow, and honest about it):
    - ``earnings_factor`` scales the employment-income input arrays of the
      reform simulation only (see ``input_scaling_modifier``).
    - Other earnings-linked inputs (self-employment/mixed income, pension
      income) are NOT scaled in v1. This is a v1 INCIDENCE CHOICE, not a
      distinction OG identifies: the OG ``w`` is the price of an effective
      labour unit (its calibration blends employment and self-employment
      income) and ``L`` is effective labour, not raw hours — restricting
      the pass-through to employment income keeps the applied margin
      narrow and explicit rather than asserting broader incidence.
    - ``labour_supply_factor`` is REPORTED in assumptions/caveats but not
      allocated to any input: an aggregate hours change has no
      distributional incidence the microsim could apply without inventing
      one.
    - No price-level overlay: the OG model is real (no price level).
    """

    source: str
    start_year: int
    earnings_factor: float        # w_reform / w_baseline
    labour_supply_factor: float   # L_reform / L_baseline
    interest_rate_baseline: float
    interest_rate_reform: float
    notes: list[str] = []
    # Constructor-specific caveats. When set, caveat_strings() returns these
    # verbatim; when empty (the OG constructor), the v1 OG-specific caveats
    # below are used, so existing dynamic-score output is unchanged.
    caveats: list[str] = []

    @classmethod
    def from_og_result(cls, og_payload: dict) -> "EconomicAssumptions":
        """Construct from an og_score_reform payload.

        Uses the two ``*_steady_state_model_units`` dicts (fields r, w, Y,
        K, L, ...). The model is real, so w and L ratios are the only price
        signals carried; r is reported for context.
        """
        try:
            base = og_payload["baseline_steady_state_model_units"]
            ref = og_payload["reform_steady_state_model_units"]
            start_year = int(og_payload["start_year"])
            (base["w"], base["L"], base["r"], ref["w"], ref["L"], ref["r"])
        except (KeyError, TypeError) as e:
            raise ValueError(
                "og_payload is not an og-score result (missing field "
                f"{e}); pass the unmodified output of "
                "`pe-macro og-score --json`"
            ) from e
        for name in ("w", "L"):
            for side, vals in (("baseline", base), ("reform", ref)):
                try:
                    v = float(vals[name])
                except (TypeError, ValueError) as e:
                    raise ValueError(
                        f"OG {side} steady state has non-numeric "
                        f"{name}={vals[name]!r}; pass the unmodified output "
                        "of `pe-macro og-score --json`"
                    ) from e
                if not (v and v > 0) or v != v or v in (float("inf"),):
                    raise ValueError(
                        f"OG {side} steady state has non-positive/non-finite "
                        f"{name}={v!r}; refusing to build an overlay from a "
                        "degenerate solve"
                    )
        earnings_factor = ref["w"] / base["w"]
        labour_supply_factor = ref["L"] / base["L"]
        for label, f in (("earnings", earnings_factor),
                         ("labour-supply", labour_supply_factor)):
            if not 0.5 <= f <= 2.0:
                raise ValueError(
                    f"implausible steady-state {label} ratio {f:.4f} "
                    "(outside [0.5, 2.0]) — inspect the OG solve rather "
                    "than applying it as an overlay"
                )
        return cls(
            source=(
                "OG-UK overlapping generations (steady state), "
                "pooled ages, single representative sector"
            ),
            start_year=start_year,
            earnings_factor=earnings_factor,
            labour_supply_factor=labour_supply_factor,
            interest_rate_baseline=base["r"],
            interest_rate_reform=ref["r"],
            notes=[
                f"steady-state overlay: long-run factor applied uniformly "
                f"from {start_year}; no transition dynamics",
                "overlay carries only the reform/baseline ratio, so the "
                "static effect embedded in the stock inputs is never "
                "counted twice",
            ],
        )

    @classmethod
    def from_frbus_result(
        cls,
        payload: dict,
        year: int,
        income_concept: str = "wage_bill",
    ) -> "EconomicAssumptions":
        """Construct from an (unmodified) frbus_shock payload.

        Uses the FRB/US real labour-market deviations for the four quarters
        of ``year``: ``pl`` (compensation per hour, % deviation from
        baseline), ``lhp`` (aggregate hours, % deviation) and ``leh``
        (civilian employment, % deviation; reported for context). The
        caller must have requested them: ``frbus_shock(...,
        variables=["pl", "lhp", "leh"])``.

        earnings_factor = 1 + annual mean of (pl) [income_concept="wage"]
        or (pl + lhp) [income_concept="wage_bill"] over the year's four
        quarters, / 100 — a TRANSITION-QUARTER AVERAGE, not a steady state.
        """
        _check_income_concept(income_concept)
        year = int(year)
        required = ("pl", "lhp", "leh")
        try:
            rows = payload["results"]
            rows[0]["period"]
        except (KeyError, TypeError, IndexError) as e:
            raise ValueError(
                "payload is not a frbus_shock result (no per-period "
                f"'results' rows: {e}); pass the unmodified output of "
                "frbus_shock"
            ) from e
        missing = [v for v in required if v not in rows[0]]
        if missing:
            raise ValueError(
                f"frbus_shock payload lacks the series {missing}: the "
                "incidence overlay needs the real labour-market deviations. "
                "Re-run frbus_shock with variables=[\"pl\", \"lhp\", "
                "\"leh\"] and pass that payload."
            )
        quarters = [f"{year}Q{q}" for q in (1, 2, 3, 4)]
        by_period = {r["period"]: r for r in rows}
        absent = [q for q in quarters if q not in by_period]
        if absent:
            raise ValueError(
                f"frbus_shock payload does not cover the four quarters of "
                f"{year} (missing {absent}; payload covers "
                f"{rows[0]['period']}-{rows[-1]['period']}). Re-run "
                "frbus_shock with a start/horizon window that spans the "
                "incidence year."
            )

        def _annual_mean(series: str) -> float:
            return sum(float(by_period[q][series]) for q in quarters) / 4.0

        pl, lhp, leh = (_annual_mean(v) for v in required)
        earnings_pct = pl + lhp if income_concept == "wage_bill" else pl
        earnings_factor = 1.0 + earnings_pct / 100.0
        labour_supply_factor = 1.0 + lhp / 100.0
        src = f"frbus_shock payload, {year} annual mean"
        _check_factor("earnings", earnings_factor, src)
        _check_factor("labour-supply", labour_supply_factor, src)

        notes = [
            f"transition-quarter average: annual mean of the {year} "
            "quarterly FRB/US deviations, not a steady state",
            "pre-tax scaling: the factor moves gross employment income; "
            "PolicyEngine applies statutory taxes and benefits to the "
            "scaled inputs",
            "country pair: FRB/US (US model) feeding the PolicyEngine US "
            "population microsimulation",
        ]
        if income_concept == "wage_bill":
            notes.append(
                f"income_concept='wage_bill': earnings factor carries "
                f"compensation per hour ({pl:+.3f}%) PLUS aggregate hours "
                f"({lhp:+.3f}%), applied uniformly"
            )
        else:
            notes.append(
                f"income_concept='wage': earnings factor carries "
                f"compensation per hour only ({pl:+.3f}%); the hours change "
                f"({lhp:+.3f}%) is reported, not applied"
            )
        caveats = [
            "uniform scaling understates distributional incidence: actual "
            "labour-market adjustment concentrates in job losers "
            f"(employment leh {leh:+.3f}%, hours lhp {lhp:+.3f}% annual "
            "mean), while the overlay spreads the change evenly over all "
            "employment income",
            "earnings factor applied to employment income only; "
            "self-employment and capital income are not adjusted",
            "no price-level overlay: pl/lhp/leh enter as real deviations",
        ]

        rff_note = (
            "interest_rate fields carry the rff pp deviation from baseline "
            f"(annual mean over {year}) against a 0.0 baseline convention; "
            "FRB/US baseline rate LEVELS are not part of the shock payload"
        )
        if "rff" in rows[0]:
            rate_base, rate_ref = 0.0, _annual_mean("rff")
        else:
            rate_base, rate_ref = 0.0, 0.0
            rff_note = ("interest_rate fields are 0.0/0.0: rff was not in "
                        "the frbus_shock payload")
        notes.append(rff_note)

        return cls(
            source=(
                "FRB/US (VAR expectations) shock deviations, "
                f"{year} annual mean, income_concept={income_concept!r}"
            ),
            start_year=year,
            earnings_factor=earnings_factor,
            labour_supply_factor=labour_supply_factor,
            interest_rate_baseline=rate_base,
            interest_rate_reform=rate_ref,
            notes=notes,
            caveats=caveats,
        )

    @classmethod
    def from_hank_result(
        cls,
        payload: dict,
        year: int,
        income_concept: str = "wage_bill",
        start_year: int = 2026,
    ) -> "EconomicAssumptions":
        """Construct from an (unmodified) hank_shock payload.

        Uses the model's pre-tax real wage ``w`` and labor ``N`` IRFs (both
        % deviations from steady state), which hank_shock surfaces from the
        general-equilibrium sequence-space Jacobian. HANK quarters are
        offsets from the shock's start, so ``start_year`` maps quarter 0 to
        Q1 of that calendar year (default 2026).

        earnings_factor = 1 + annual mean of (w) [income_concept="wage"] or
        (w + N) [income_concept="wage_bill"] over the four quarters of
        ``year``, / 100 — a transition-quarter average around the steady
        state, not a steady-state shift.
        """
        _check_income_concept(income_concept)
        year, start_year = int(year), int(start_year)
        if year < start_year:
            raise ValueError(
                f"year ({year}) is before start_year ({start_year}): HANK "
                "quarters are offsets from the shock start, which "
                f"start_year maps to {start_year}Q1"
            )
        try:
            rows = payload["results"]
            rows[0]["quarter"]
        except (KeyError, TypeError, IndexError) as e:
            raise ValueError(
                "payload is not a hank_shock result (no per-quarter "
                f"'results' rows: {e}); pass the unmodified output of "
                "hank_shock"
            ) from e
        missing = [v for v in ("w", "N") if v not in rows[0]]
        if missing:
            raise ValueError(
                f"hank_shock payload lacks the series {missing}: the "
                "incidence overlay needs the pre-tax real wage and labor "
                "IRFs. This policyengine-macro version's hank_shock "
                "surfaces them — re-run hank_shock from this package and "
                "pass that payload."
            )
        offset = 4 * (year - start_year)
        if len(rows) < offset + 4:
            raise ValueError(
                f"hank_shock payload covers {len(rows)} quarters, but the "
                f"four quarters of {year} are offsets {offset}-{offset + 3} "
                f"from the shock start ({start_year}Q1). Re-run hank_shock "
                f"with horizon >= {offset + 4}."
            )
        window = rows[offset:offset + 4]

        def _annual_mean(series: str) -> float:
            return sum(float(r[series]) for r in window) / 4.0

        w, n = _annual_mean("w"), _annual_mean("N")
        earnings_pct = w + n if income_concept == "wage_bill" else w
        earnings_factor = 1.0 + earnings_pct / 100.0
        labour_supply_factor = 1.0 + n / 100.0
        src = f"hank_shock payload, {year} annual mean"
        _check_factor("earnings", earnings_factor, src)
        _check_factor("labour-supply", labour_supply_factor, src)

        notes = [
            f"transition-quarter average: annual mean of the {year} "
            "quarterly HANK deviations from steady state (quarter offsets "
            f"{offset}-{offset + 3}, shock start mapped to "
            f"{start_year}Q1), not a steady-state shift",
            "pre-tax scaling: the factor moves gross employment income; "
            "PolicyEngine applies statutory taxes and benefits to the "
            "scaled inputs",
            "country pair: US HANK (stylized calibrated model) feeding the "
            "PolicyEngine US population microsimulation",
        ]
        if income_concept == "wage_bill":
            notes.append(
                f"income_concept='wage_bill': earnings factor carries the "
                f"real wage ({w:+.3f}%) PLUS labor N ({n:+.3f}%), applied "
                "uniformly"
            )
        else:
            notes.append(
                f"income_concept='wage': earnings factor carries the real "
                f"wage only ({w:+.3f}%); the labor change ({n:+.3f}%) is "
                "reported, not applied"
            )
        rate_ref = 0.0
        rate_note = ("interest_rate fields are 0.0/0.0: 'r' was not in the "
                     "hank_shock payload")
        if "r" in rows[0]:
            rate_ref = _annual_mean("r")
            rate_note = (
                "interest_rate fields carry the QUARTERLY real-rate pp "
                f"deviation from steady state (annual mean over {year}) "
                "against a 0.0 baseline convention"
            )
        notes.append(rate_note)
        caveats = [
            "uniform scaling understates distributional incidence: actual "
            "labour-market adjustment concentrates in job losers, while "
            "the overlay spreads the change evenly over all employment "
            "income (HANK's N is aggregate labor, with no unemployment "
            "margin to allocate)",
            "earnings factor applied to employment income only; "
            "self-employment and capital income are not adjusted",
            "stylized calibrated model: the steady state is the "
            "Auclert-Bardóczy-Rognlie-Straub (2021) calibration, not a US "
            "forecast baseline; responses are linear/first-order",
        ]
        return cls(
            source=(
                "US HANK (sequence-space) shock deviations, "
                f"{year} annual mean, income_concept={income_concept!r}"
            ),
            start_year=year,
            earnings_factor=earnings_factor,
            labour_supply_factor=labour_supply_factor,
            interest_rate_baseline=0.0,
            interest_rate_reform=rate_ref,
            notes=notes,
            caveats=caveats,
        )

    def input_scaling_modifier(self):
        """The overlay as a simulation modifier, or None for a null result.

        Returns a callable suitable for ``policyengine.core.Dynamic(
        simulation_modifier=...)``: it multiplies the first POPULATED
        employment-income input variable (SCALED_INPUT_VARIABLES order) by
        ``earnings_factor`` on every known period, via the engine's
        supported ``set_input`` API. Input scaling is used because
        parameter overrides on the uprating indices are dead in population
        runs (pre-uprated per-year datasets; see module docstring).

        Invariant: a no-op macro result (earnings_factor == 1) returns
        None — the caller attaches NO dynamic, so the reform simulation is
        bit-identical to the static one.
        """
        if self.earnings_factor == 1.0:
            return None
        factor = self.earnings_factor

        def modifier(microsim):
            for name in SCALED_INPUT_VARIABLES:
                holder = microsim.get_holder(name)
                periods = list(holder.get_known_periods())
                if not periods:
                    continue
                for period in periods:
                    values = holder.get_array(period)
                    holder.delete_arrays(period)
                    microsim.set_input(name, period, values * factor)
                return microsim
            raise RuntimeError(
                "EconomicAssumptions overlay found no populated "
                f"employment-income input among {SCALED_INPUT_VARIABLES}; "
                "the earnings factor cannot be applied — refusing to "
                "return a silently static result as a dynamic one."
            )

        return modifier

    def assumption_strings(self) -> list[str]:
        return [
            f"macro source: {self.source}",
            *self.notes,
            "application: employment-income input arrays of the reform "
            f"simulation scaled by {self.earnings_factor} (direct input "
            "scaling; uprating-parameter overrides are dead on pre-built "
            "per-year datasets)",
        ]

    def caveat_strings(self) -> list[str]:
        if self.caveats:
            return list(self.caveats)
        labour_pct = 100.0 * (self.labour_supply_factor - 1.0)
        return [
            f"aggregate effective-labour change {labour_pct:+.2f}% not "
            "distributionally allocated in v1 (labour_supply_factor is "
            "reported, not applied to any input; OG's L is effective "
            "labour units, not raw hours)",
            "earnings factor applied to employment income only; "
            "self-employment/mixed income and pension income are not "
            "adjusted in v1",
            "no price-level overlay: the OG model is real",
        ]
