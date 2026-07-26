"""New-model adapter contract built on the production ``ScoreResult``.

The common request is capability-checked before execution.  The common result
is the same object already emitted by scoring entry points; adapters may not
introduce a second result envelope or infer units.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from policyengine_macro.capabilities import get_status
from policyengine_macro.core import (
    ScoreQuantity,
    ScoreResult,
    hank_shock,
    obr_score_reform,
)


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str
    analysis_type: str = Field(min_length=1)
    country: str = Field(pattern=r"^[a-z]{2}$")
    inputs: dict[str, Any]
    baseline: str = Field(min_length=1)
    horizon: str = Field(min_length=1)
    requested_outputs: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def registered_and_supported(self) -> "AnalysisRequest":
        capability = get_status(self.model_id)
        if self.country not in capability["geography"]:
            raise ValueError(f"{self.model_id} does not support {self.country}")
        if self.analysis_type not in capability["question_types"]:
            raise ValueError(f"{self.model_id} does not support {self.analysis_type}")
        unsupported = sorted(set(self.requested_outputs) - set(capability["outputs"]))
        if unsupported:
            raise ValueError(f"unsupported outputs for {self.model_id}: {unsupported}")
        return self


class ModelAdapter(ABC):
    """Base class and fail-closed request/result boundary for model packages."""

    model_id: str

    @abstractmethod
    def validate_request(self, request: AnalysisRequest) -> None:
        """Validate names, ranges, dimensions, frequency and units."""

    @abstractmethod
    def execute(self, request: AnalysisRequest) -> ScoreResult | dict:
        """Execute the model and return the canonical result contract."""

    def run(self, request: AnalysisRequest | dict) -> ScoreResult:
        request = AnalysisRequest.model_validate(request)
        if request.model_id != self.model_id:
            raise ValueError(
                f"adapter {self.model_id} cannot run request for {request.model_id}"
            )
        self.validate_request(request)
        result = ScoreResult.model_validate(self.execute(request))
        mismatches = []
        if result.model != request.model_id:
            mismatches.append("model")
        if result.country != request.country:
            mismatches.append("country")
        if result.baseline != request.baseline:
            mismatches.append("baseline")
        if result.horizon != request.horizon:
            mismatches.append("horizon")
        missing = set(request.requested_outputs) - set(result.quantities)
        if missing:
            mismatches.append(f"outputs {sorted(missing)}")
        if mismatches:
            raise ValueError(
                "adapter result does not match request: " + ", ".join(mismatches)
            )
        return result


class OBRPolicyReformAdapter(ModelAdapter):
    """First real contract implementation: reviewed reform-to-OBR bridge."""

    model_id = "obr-macro"
    allowed_inputs = {"reform", "start_year", "years", "dataset"}

    def validate_request(self, request: AnalysisRequest) -> None:
        unknown = set(request.inputs) - self.allowed_inputs
        if unknown:
            raise ValueError(f"unknown OBR adapter inputs: {sorted(unknown)}")
        if "reform" not in request.inputs:
            raise ValueError("OBR adapter requires an explicit reform mapping")
        if int(request.inputs.get("years", 5)) < 1:
            raise ValueError("years must be at least 1")

    def execute(self, request: AnalysisRequest) -> ScoreResult:
        payload = obr_score_reform(**request.inputs)
        return ScoreResult.model_validate(payload["score"])


class USHankShockAdapter(ModelAdapter):
    """Stylized-shock contract for the US HANK member.

    Wraps ``core.hank_shock`` in the common ScoreResult. There is no reform
    input: the model scores stylized shocks (kind, size, persistence), not
    detailed tax reforms, and inventing a reform bridge is out of scope by
    design. Peak deviations are reported as ``delta_pct`` per quantity; the
    full IRF stays on the hank_shock tool/CLI surface.
    """

    model_id = "us-hank"
    allowed_inputs = {"kind", "size", "persistence", "horizon", "variant"}

    # Requested-output name -> (IRF series, units, unit_code).
    _OUTPUTS = {
        "gdp": ("Y", "% deviation from steady state (peak)", "PCT_DEV_SS"),
        "consumption": ("C", "% deviation from steady state (peak)", "PCT_DEV_SS"),
        "investment": ("I", "% deviation from steady state (peak)", "PCT_DEV_SS"),
        "inflation": ("pi", "pp deviation, quarterly rate (peak)", "PP_DEV_SS"),
        "real_rate": ("r", "pp deviation, quarterly rate (peak)", "PP_DEV_SS"),
    }

    def validate_request(self, request: AnalysisRequest) -> None:
        unknown = set(request.inputs) - self.allowed_inputs
        if unknown:
            raise ValueError(f"unknown US HANK adapter inputs: {sorted(unknown)}")
        for required in ("kind", "size"):
            if required not in request.inputs:
                raise ValueError(
                    f"US HANK adapter requires an explicit '{required}' input"
                )
        if request.inputs.get("variant", "two_asset") == "one_asset":
            unavailable = {"investment"} & set(request.requested_outputs)
            if unavailable:
                raise ValueError(
                    "the one_asset variant has no capital, so it cannot "
                    f"return {sorted(unavailable)}"
                )

    def execute(self, request: AnalysisRequest) -> ScoreResult:
        payload = hank_shock(**request.inputs)
        quantities = {}
        for name in request.requested_outputs:
            series, units, unit_code = self._OUTPUTS[name]
            quantities[name] = ScoreQuantity(
                delta_pct=payload["peaks"][series]["value"],
                units=units,
                unit_code=unit_code,
                basis="linear (first-order) sequence-space IRF vs the "
                      "calibrated steady state",
                time_basis=(
                    f"peak absolute deviation within {payload['horizon']} "
                    f"quarters (at quarter "
                    f"{payload['peaks'][series]['quarter']})"
                ),
                price_basis="real, model calibration basis",
                geography="us",
                baseline_definition=request.baseline,
                uncertainty="none quantified; deterministic linear IRF",
            )
        return ScoreResult(
            model=self.model_id,
            model_class="heterogeneous-agent New Keynesian (sequence-space)",
            analysis_type=request.analysis_type,
            result_type="scenario",
            country="us",
            reform={},  # no reform vocabulary: stylized shock experiment
            baseline=request.baseline,
            provenance=payload["provenance"],
            horizon=request.horizon,
            quantities=quantities,
            assumptions=[
                "Auclert-Bardóczy-Rognlie-Straub (2021) calibration at "
                "production grids",
                "AR(1) shock path size * persistence**t",
                "fiscal_spending shocks are implicitly financed by the "
                "endogenous labor tax",
            ],
            caveats=[
                "validated replication scoring stylized shocks, not detailed "
                "tax reforms; NOT a forecaster",
                "responses are first-order (linear) and scale exactly with "
                "the shock size; no state dependence",
                "distributional outputs, where requested via hank_shock, are "
                "first-order approximations from steady-state policies",
            ],
            validation=[
                "us-hank-model's 18-test suite gates steady-state targets, "
                "market clearing and shock responses against the published "
                "Econometrica 2021 results",
            ],
            warnings=[payload["warning"]] if payload.get("warning") else [],
        )

