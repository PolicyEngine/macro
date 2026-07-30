"""Code-tab Step 2 — define the reform.

Importable so every later script reuses the same Policy object::

    from og_dashboard.reform import REFORM

The reform raises the basic rate of UK income tax from 20% to 21% from
calendar year 2026 (which the dashboard charts label as fiscal year 2027–28).
"""

from datetime import datetime

from policyengine.core import ParameterValue, Policy
from policyengine.tax_benefit_models.uk import uk_latest

basic_rate = uk_latest.get_parameter("gov.hmrc.income_tax.rates.uk[0].rate")

REFORM = Policy(
    name="Basic rate 21%",
    parameter_values=[
        ParameterValue(
            parameter=basic_rate,
            value=0.21,
            start_date=datetime(2026, 1, 1),
        ),
    ],
)
