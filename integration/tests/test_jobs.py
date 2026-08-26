"""The background-job escape hatch from the transport's 150-second ceiling.

Modal abandons any HTTP request to a web endpoint after 150 seconds. Its
documented escape hatch -- a 303 to a polling URL -- does not work for an MCP
server: 303 means "re-issue as GET", and Modal's polling URL answers GET with
`400 modal-http: bad redirect method`. Measured against the live deployment,
every correctly-behaving client gets a 400 and every other client gets a bare
303. So score_reform, which needs longer than 150s over its default five-year
window, could not be called on the hosted server at all.

These cover the parts that are testable without Modal: the allow-list, the
handle contract, and what happens where no backend is installed (which is
everywhere except the hosted server -- the local stdio server, the CLI, and
this test process). The Modal round-trip itself is covered by the post-deploy
smoke test in test_remote_mcp.py.
"""

from __future__ import annotations

import pytest

from policyengine_macro import jobs


@pytest.fixture(autouse=True)
def _no_backend():
    """Every test here runs with no backend, and none may leak to the next."""
    before = (jobs._spawn, jobs._poll)
    jobs.set_backend(None, None)
    yield
    jobs.set_backend(*before)


def test_score_reform_is_runnable_as_a_job():
    """The tool the ceiling actually blocks must be on the allow-list."""
    assert "score_reform" in jobs.JOB_TOOLS
    assert jobs.resolve("score_reform").__name__ == "score_reform"


def test_every_allow_listed_tool_resolves_to_a_real_adapter():
    """No entry may name a callable that does not exist."""
    for tool in jobs.JOB_TOOLS:
        assert callable(jobs.resolve(tool)), tool


def test_unknown_tool_is_refused_with_the_allowed_set():
    """`tool` comes from an MCP client, so it is an allow-list, not getattr.

    Resolving a caller-supplied name straight onto the module would expose
    every callable in `core` -- including private helpers -- to anyone who
    can reach the server.
    """
    with pytest.raises(ValueError) as excinfo:
        jobs.resolve("__import__")
    message = str(excinfo.value)
    assert "cannot be run as a job" in message
    assert "score_reform" in message, "the refusal does not say what IS allowed"


def test_fast_tools_are_not_job_runnable():
    """Only the slow tools. A job handle for a sub-second call is pure overhead."""
    for tool in ("list_model_capabilities", "calculate_household", "forecast_uk"):
        with pytest.raises(ValueError):
            jobs.resolve(tool)


def test_without_a_backend_start_says_so_and_says_what_to_do_instead():
    """Locally there is no ceiling and no backend: say that, do not pretend.

    Silently accepting the call and handing back a job id that nothing will
    ever run would be the worst outcome -- the caller would poll forever.
    """
    with pytest.raises(jobs.NoBackend) as excinfo:
        jobs.start("score_reform", {"country": "uk"})
    message = str(excinfo.value)
    assert "hosted" in message
    assert "Call the tool directly instead" in message


def test_without_a_backend_result_also_refuses():
    with pytest.raises(jobs.NoBackend):
        jobs.result("fc-whatever")


def test_a_bad_tool_name_fails_before_anything_is_spawned():
    """Validation precedes the spawn, so a typo costs milliseconds, not a container."""
    spawned = []
    jobs.set_backend(lambda t, a: spawned.append((t, a)) or "fc-1", lambda j, w: (True, {}))
    with pytest.raises(ValueError):
        jobs.start("not_a_tool", {})
    assert spawned == [], "a rejected tool still reached the backend"


def test_start_returns_a_handle_that_says_how_to_collect_it():
    calls = []
    jobs.set_backend(lambda t, a: calls.append((t, a)) or "fc-abc", lambda j, w: (True, {}))
    out = jobs.start("score_reform", {"country": "uk", "model": "obr"})
    assert out["job_id"] == "fc-abc"
    assert out["tool"] == "score_reform"
    assert out["status"] == "running"
    # The handle has to carry the next step: an agent that gets a job id and
    # no instruction has no way to know get_job_result exists.
    assert "get_job_result" in out["next_step"]
    assert calls == [("score_reform", {"country": "uk", "model": "obr"})]


def test_start_passes_an_empty_dict_rather_than_none():
    """The worker calls fn(**arguments); None would raise inside the container."""
    calls = []
    jobs.set_backend(lambda t, a: calls.append(a) or "fc-1", lambda j, w: (True, {}))
    jobs.start("obr_shock")
    assert calls == [{}]


def test_finished_job_returns_the_result():
    jobs.set_backend(lambda t, a: "fc-1", lambda j, w: (True, {"gdp": -1.0}))
    out = jobs.result("fc-1")
    assert out["status"] == "done"
    assert out["result"] == {"gdp": -1.0}


def test_unfinished_job_tells_the_caller_to_poll_again():
    jobs.set_backend(lambda t, a: "fc-1", lambda j, w: (False, None))
    out = jobs.result("fc-1", wait_seconds=30)
    assert out["status"] == "running"
    assert out["job_id"] == "fc-1"
    assert out["waited_seconds"] == 30
    assert "again" in out["next_step"]


def test_wait_is_capped_well_below_the_transport_ceiling():
    """A poll that outlived the 150s ceiling would be the bug it works around.

    The cap sits far below it, not just inside it. Measured end-to-end through
    a real Claude Code session: polls at 60-120s repeatedly hit transport
    timeouts and one Modal `InternalFailure: Server has lost track of input`,
    while 30s polls came back reliably. The flakiness tracks how long the
    connection is held open rather than how close it gets to 150s.
    """
    seen = []
    jobs.set_backend(lambda t, a: "fc-1", lambda j, w: (seen.append(w), (False, None))[1])
    jobs.result("fc-1", wait_seconds=10_000)
    assert seen == [jobs.MAX_WAIT_SECONDS]
    assert jobs.MAX_WAIT_SECONDS <= 60, "long blocking polls are unreliable"
    assert jobs.DEFAULT_WAIT_SECONDS <= 30, "the default poll must be short"


def test_default_wait_is_the_short_one():
    """Callers who pass nothing get the interval that actually works."""
    seen = []
    jobs.set_backend(lambda t, a: "fc-1", lambda j, w: (seen.append(w), (False, None))[1])
    jobs.result("fc-1")
    assert seen == [jobs.DEFAULT_WAIT_SECONDS]


def test_negative_wait_is_clamped_not_passed_through():
    seen = []
    jobs.set_backend(lambda t, a: "fc-1", lambda j, w: (seen.append(w), (False, None))[1])
    jobs.result("fc-1", wait_seconds=-5)
    assert seen == [0]


def test_job_tools_are_on_the_mcp_surface():
    """They are useless if a client cannot see them."""
    import asyncio

    from policyengine_macro.mcp_server import mcp

    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert {"start_job", "get_job_result"} <= names


def test_start_job_tool_description_names_score_reform():
    """An agent hitting the ceiling has to be able to find the way round it.

    The description is the only place a client learns that score_reform needs
    the job path on the hosted server, so this pins the pointer rather than
    the prose.
    """
    import asyncio

    from policyengine_macro.mcp_server import mcp

    tools = {t.name: t for t in asyncio.run(mcp.list_tools())}
    description = tools["start_job"].description
    assert "score_reform" in description
    assert "150" in description
