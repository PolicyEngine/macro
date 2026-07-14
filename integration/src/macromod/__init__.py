"""MacroMod integration layer.

Wraps two local model repos behind one API:

- OBR macroeconomic model emulator (``obr_macro``): policy reform scoring.
- UK SVAR / BVAR model (``boe_var``): forecasts and structural shock readings.

Same functions are exposed via a CLI (``macromod``) and an MCP server
(``python -m macromod.mcp_server``).
"""

from macromod.core import (
    obr_score_reform,
    obr_list_variables,
    svar_forecast,
    svar_latest_shocks,
    svar_summary,
)

__all__ = [
    "obr_score_reform",
    "obr_list_variables",
    "svar_forecast",
    "svar_latest_shocks",
    "svar_summary",
]

__version__ = "0.1.0"
