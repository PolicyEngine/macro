# MacroMod integration layer

A single Python package (`macromod`) exposing two local UK macro models behind
one CLI and one MCP server:

- **OBR emulator** (`obr_macro`, at `~/obr-macroeconomic-model`): runs the
  OBR's published model equations to score policy reforms (spending, tax).
- **UK SVAR** (`boe_var`, at `~/boe-var-model`): sign-identified Bayesian VAR
  for UK GDP/CPI forecasts and structural shock readings.

`src/macromod/core.py` holds the model adapters (single source of truth);
`cli.py` and `mcp_server.py` are thin wrappers over the same functions.

## Install

Into the conda `python313` env (unset `VIRTUAL_ENV` first if set):

```bash
PY=/Users/janansadeqian/anaconda3/envs/python313/bin/python
$PY -m pip install -e /Users/janansadeqian/obr-macroeconomic-model \
                   -e /Users/janansadeqian/boe-var-model \
                   -e /Users/janansadeqian/MacroMod/integration
```

## CLI

```bash
macromod variables                                   # OBR shock variables + units
macromod score --var CGG --shock 1250 --periods 4    # £5bn/yr spending, 1 year
macromod score --var TCPRO --shock -0.05 --investment-closure   # 5pp corp tax cut
macromod forecast --horizons 12 --draws 500          # YoY GDP & CPI, 68/90 bands
macromod shocks --draws 500                          # P(sign) of latest-quarter shocks
macromod summary                                     # instant, parses committed results
```

Add `--json` to any command for machine-readable output. Units: CGG/CGIPS
shocks are £m per quarter; TCPRO is a decimal rate change. SVAR estimation
results are cached in-process by draw count, so repeat calls are instant
within one process (each CLI invocation is a fresh process; the cache mainly
benefits the MCP server).

## MCP server

Runs over stdio via `python -m macromod.mcp_server`, exposing tools
`score_reform`, `list_reform_variables`, `forecast_uk`, `latest_shocks`,
`model_summary`.

Test locally with Claude Code:

```bash
claude mcp add macromod -- /Users/janansadeqian/anaconda3/envs/python313/bin/python -m macromod.mcp_server
```

Default `draws=500` keeps tool calls to tens of seconds; raise it (e.g. 2000+)
for smoother bands. Repeated calls with the same parameters hit an in-process
cache and return instantly.

**Next step:** hosted remote deployment at `https://mcp.macromod.dev/mcp` —
FastMCP supports the streamable-http transport
(`mcp.run(transport="streamable-http")`) for exactly this.

## Tests

```bash
cd /Users/janansadeqian/MacroMod/integration
python -m pytest tests -q     # includes an end-to-end stdio MCP client test
```
