"""Background jobs for adapter calls that outlive an HTTP request.

Modal enforces a hard **150-second** ceiling on any HTTP request to a web
endpoint. Past that the proxy abandons the request and returns a 303 pointing
at a polling URL. That escape hatch does not work here: a 303 tells a
standards-compliant client to re-issue the request as a GET, and Modal's
polling URL rejects GET with ``400 modal-http: bad redirect method``. So every
HTTP client that follows redirects correctly -- curl -L, fetch, httpx with
follow_redirects -- gets a 400, and every client that does not gets a bare 303.
There is no client-side fix.

Measured against the deployed server:

    obr_shock    ~103s warm  -> succeeds; cold -> exceeds 150s and fails
    score_reform ~111s local, more on Modal -> exceeds 150s, always fails

score_reform cannot be squeezed under the ceiling: the work is two full
372-equation solves plus one PolicyEngine static costing per year of the
window. The ceiling is a property of the transport, so the fix is to stop
doing the work inside the request.

``start_job`` hands the call to a worker with a 30-minute budget and returns
immediately; ``get_job_result`` polls it, blocking for a bounded interval that
is itself comfortably inside the 150s ceiling.

This module is deliberately backend-agnostic. The hosted server installs a
Modal backend at startup (see ``modal_app.serve``); anywhere else -- the local
stdio server, the CLI, tests -- no backend is installed and the job tools
report that plainly instead of pretending to queue work that nothing will run.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from policyengine_macro import core

# Adapter calls allowed to run as jobs. An allow-list, not getattr on a
# caller-supplied name: `tool` arrives from an MCP client, and resolving it
# straight onto a module would expose every callable in `core`.
# Names are the ADAPTER function in `core`, which is not always the MCP tool
# name (the tool `population_reform_impact` is `core.pe_population_impact`,
# and `dynamic_reform_impact` is `core.dynamic_population_reform_impact`).
# test_every_allow_listed_tool_resolves_to_a_real_adapter pins that these
# resolve -- it caught two names that did not.
JOB_TOOLS: tuple[str, ...] = (
    "score_reform",
    "obr_shock",
    "dynamic_population_reform_impact",
    "frbus_shock",
    "hank_shock",
    "pe_population_impact",
)

# The longest a get_job_result call may block. The transport ceiling is 150s;
# this leaves room for request overhead so the poll itself never becomes the
# thing that times out.
MAX_WAIT_SECONDS = 120

_spawn: Callable[[str, dict], str] | None = None
_poll: Callable[[str, int], Any] | None = None


def set_backend(spawn, poll) -> None:
    """Install the job backend. Called once, by the hosted server at startup."""
    global _spawn, _poll
    _spawn, _poll = spawn, poll


def backend_available() -> bool:
    return _spawn is not None and _poll is not None


class NoBackend(RuntimeError):
    """Raised where jobs are not available -- i.e. everywhere but the hosted server."""


_NO_BACKEND_MESSAGE = (
    "Background jobs run only on the hosted PolicyEngine Macro server. This "
    "process has no job backend, so there is nothing to queue the work onto. "
    "Call the tool directly instead ({tools}) -- running locally there is no "
    "150-second HTTP ceiling to work around."
)


def resolve(tool: str) -> Callable[..., Any]:
    """Look up an allow-listed adapter callable by tool name."""
    if tool not in JOB_TOOLS:
        raise ValueError(
            f"{tool!r} cannot be run as a job. Allowed: {', '.join(JOB_TOOLS)}. "
            "Fast tools should be called directly -- they return well inside "
            "the transport's 150-second ceiling."
        )
    return getattr(core, tool)


def run(tool: str, arguments: dict | None) -> dict:
    """Execute an allow-listed adapter call. This is what the worker runs."""
    return resolve(tool)(**(arguments or {}))


def start(tool: str, arguments: dict | None = None) -> dict:
    """Queue an adapter call and return a handle without waiting for it."""
    resolve(tool)  # validate before spawning, so a typo fails in milliseconds
    if not backend_available():
        raise NoBackend(_NO_BACKEND_MESSAGE.format(tools=", ".join(JOB_TOOLS)))
    job_id = _spawn(tool, arguments or {})
    return {
        "job_id": job_id,
        "tool": tool,
        "status": "running",
        "next_step": (
            f"Call get_job_result(job_id={job_id!r}). It blocks until the job "
            f"finishes or up to wait_seconds (max {MAX_WAIT_SECONDS}); if it "
            "returns status 'running', call it again with the same job_id."
        ),
    }


def result(job_id: str, wait_seconds: int = 60) -> dict:
    """Poll a job. Blocks up to wait_seconds, then reports back either way."""
    if not backend_available():
        raise NoBackend(_NO_BACKEND_MESSAGE.format(tools=", ".join(JOB_TOOLS)))
    wait = max(0, min(int(wait_seconds), MAX_WAIT_SECONDS))
    done, payload = _poll(job_id, wait)
    if done:
        return {"job_id": job_id, "status": "done", "result": payload}
    return {
        "job_id": job_id,
        "status": "running",
        "waited_seconds": wait,
        "next_step": (
            "Not finished yet. Call get_job_result again with the same "
            "job_id; a score_reform over the default five-year window "
            "typically needs two or three polls."
        ),
    }
