"""Unit tests for remote_jobs.run_via_job, with a scripted server.

No network: the remote suite that uses this helper only runs against the live
deployment, so the polling contract is pinned here instead.
"""

from __future__ import annotations

import asyncio

import pytest

from remote_jobs import MAX_POLL_ERRORS, run_via_job

RUNNING = {"job_id": "fc-x", "status": "running", "waited_seconds": 30}
RESULT = {"budgetary_impact_bn": 7.1}
DONE = {"job_id": "fc-x", "status": "done", "result": RESULT}


class Server:
    def __init__(self, polls, clock=None):
        self.polls = list(polls)
        self.calls = []
        self.clock = clock

    async def __call__(self, tool, arguments):
        self.calls.append((tool, arguments))
        if tool == "start_job":
            return {"job_id": "fc-x", "status": "running", "next_step": "get_job_result"}
        if self.clock is not None:
            self.clock[0] += 30
        reply = self.polls.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply


async def _no_sleep(_):
    return None


def run(server, deadline=600, clock=None):
    kw = {"sleep": _no_sleep}
    if clock is not None:
        kw["clock"] = lambda: clock[0]
    return asyncio.run(run_via_job(server, "obr_shock", {"var": "CGG"}, deadline, **kw))


def test_starts_a_job_and_polls_until_done():
    server = Server([RUNNING, DONE])
    assert run(server) == RESULT
    assert server.calls[0] == ("start_job", {"tool": "obr_shock", "arguments": {"var": "CGG"}})
    assert [tool for tool, _ in server.calls[1:]] == ["get_job_result"] * 2
    assert all(args["wait_seconds"] <= 60 for _, args in server.calls[1:])


def test_the_tool_is_never_called_directly():
    server = Server([DONE])
    run(server)
    assert "obr_shock" not in [tool for tool, _ in server.calls]


def test_a_transport_error_on_a_poll_is_retried():
    server = Server([RUNNING, OSError("303 not followed"), DONE])
    assert run(server) == RESULT


def test_repeated_transport_errors_fail_with_the_job_id():
    server = Server([OSError("down")] * (MAX_POLL_ERRORS + 1))
    with pytest.raises(AssertionError, match="fc-x"):
        run(server)


def test_a_job_error_fails_without_polling_again():
    server = Server([AssertionError("job raised"), DONE])
    with pytest.raises(AssertionError, match="job raised"):
        run(server)
    assert server.polls == [DONE]


def test_a_job_still_running_at_the_deadline_fails_with_its_id():
    clock = [0.0]
    server = Server([RUNNING] * 50, clock=clock)
    with pytest.raises(AssertionError, match="fc-x did not finish within 90s"):
        run(server, deadline=90, clock=clock)
