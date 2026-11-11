"""Run a slow hosted tool through start_job / get_job_result.

Modal abandons any web request after 150 seconds and answers HTTP 303, which
the MCP client refuses ("Redirect to .../mcp not followed"). obr_shock and a
microsim score_reform used to fit under that on a warm server; on a cold one
they do not, so test_obr_shock_cgg has failed on most deploys and daily
validations since October, and test_score_reform_microsim_scoreresult on most
since the 30 Oct deploy. Both tools are on jobs.JOB_TOOLS, so the remote tests reach
them the way a real caller should: as a job, polled in short calls that each
stay well inside the ceiling.

Kept out of test_remote_mcp.py so it can be unit-tested without a network
(test_remote_jobs.py); test_remote_mcp.py is skipped unless
POLICYENGINE_MACRO_REMOTE_TESTS=1.
"""

from __future__ import annotations

import asyncio
import time

import json

POLL_WAIT_SECONDS = 30  # jobs.DEFAULT_WAIT_SECONDS: short polls are the reliable ones
POLL_TIMEOUT_SECONDS = 180  # one poll: 30s server-side wait plus a cold start
MAX_POLL_ERRORS = 5


async def run_via_job(call, tool: str, arguments: dict, deadline: float,
                      clock=time.monotonic, sleep=asyncio.sleep) -> dict:
    """Start ``tool`` as a hosted job and return its result.

    ``call(tool, arguments)`` is an async MCP call that returns the decoded
    JSON and raises AssertionError when the server reports a tool error.
    A transport error on a poll is retried (the job runs on regardless of the
    connection watching it); a tool error, or a job still running at
    ``deadline`` seconds, fails with the job id in the message.
    """
    started = await call("start_job", {"tool": tool, "arguments": arguments})
    assert started["status"] == "running", started
    job_id = started["job_id"]
    assert job_id, started

    stop = clock() + deadline
    errors = 0
    out = None
    while clock() < stop:
        try:
            out = await asyncio.wait_for(
                call("get_job_result",
                     {"job_id": job_id, "wait_seconds": POLL_WAIT_SECONDS}),
                timeout=POLL_TIMEOUT_SECONDS,
            )
        except AssertionError:
            raise
        except Exception as exc:  # noqa: BLE001 - a failed poll is not a failed job
            errors += 1
            assert errors <= MAX_POLL_ERRORS, (
                f"{tool} job {job_id}: {errors} polls in a row failed: {exc!r}"
            )
            await sleep(5)
            continue
        errors = 0
        if out["status"] == "done":
            return out["result"]
        assert out["status"] == "running", out
    raise AssertionError(f"{tool} job {job_id} did not finish within {deadline:.0f}s: {out}")


def mcp_caller(url: str, timeout: float = 300):
    """An async ``call(tool, arguments)`` for run_via_job, one session per call.

    The reply is judged only after the MCP contexts have closed. Both
    streamablehttp_client and ClientSession run anyio task groups, which wrap
    anything raised inside them in an ExceptionGroup; an AssertionError for a
    tool error raised in there would reach run_via_job looking like a
    transport error and be retried instead of failing the test.
    """

    async def call(tool: str, arguments: dict) -> dict:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        async with streamablehttp_client(url, timeout=timeout) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool, arguments)
        text = "\n".join(c.text for c in result.content if getattr(c, "text", None))
        assert not result.isError, f"{tool} error: {text[:1000]}"
        return json.loads(text)

    return call
