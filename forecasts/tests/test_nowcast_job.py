"""nowcast.py must reach the hosted forecast through the job API.

Archive run 42963724470 (11 Nov 2026) was due (uk_gdp_cvm releases 12 Nov)
and passed the edge gate, then failed after ~160s in the direct forecast_uk
call:

    httpx.HTTPStatusError: Redirect to https://policyengine--policyengine-
    macro-mcp-serve.modal.run/mcp not followed

Modal answers any web request past 150s with a 303, and a 6000-draw forecast
takes ~5.5 minutes. These tests drive ``run_as_job`` with a fake ``call`` so
the polling contract is pinned without a network or a Modal container.
"""

import ast
import unittest
from pathlib import Path
from unittest import mock

from forecasts import nowcast

ROOT = Path(__file__).resolve().parents[2]
ARGS = {"horizons": 13, "draws": 6000}
RESULT = {"gdp_growth_yoy": [{"quarter": "2026Q3", "median": 1.2}]}


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class FakeServer:
    """Scripted replies to start_job / get_job_result, in order."""

    def __init__(self, polls, start=None, clock=None, poll_seconds=30):
        self.polls = list(polls)
        self.start = start or {"job_id": "fc-test", "status": "running"}
        self.calls = []
        self.clock = clock
        self.poll_seconds = poll_seconds

    def __call__(self, tool, arguments):
        self.calls.append((tool, arguments))
        if tool == "start_job":
            if isinstance(self.start, Exception):
                raise self.start
            return self.start
        assert tool == "get_job_result", tool
        if self.clock is not None:
            self.clock.now += self.poll_seconds
        reply = self.polls.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


RUNNING = {"job_id": "fc-test", "status": "running", "waited_seconds": 30}
DONE = {"job_id": "fc-test", "status": "done", "result": RESULT}


class RunAsJobTests(unittest.TestCase):
    def run_job(self, server, **kw):
        return nowcast.run_as_job(server, ARGS, sleep=lambda s: None, **kw)

    def test_starts_the_forecast_adapter_as_a_job_and_polls_to_done(self):
        server = FakeServer([RUNNING, RUNNING, DONE])
        self.assertEqual(self.run_job(server), RESULT)
        tool, arguments = server.calls[0]
        self.assertEqual(tool, "start_job")
        self.assertEqual(arguments, {"tool": "svar_forecast", "arguments": ARGS})
        polls = server.calls[1:]
        self.assertEqual(len(polls), 3)
        for tool, arguments in polls:
            self.assertEqual(tool, "get_job_result")
            self.assertEqual(arguments["job_id"], "fc-test")
            # Each poll must stay well inside Modal's 150s ceiling.
            self.assertLessEqual(arguments["wait_seconds"], 60)

    def test_never_calls_forecast_uk_directly(self):
        server = FakeServer([DONE])
        self.run_job(server)
        self.assertNotIn("forecast_uk", [tool for tool, _ in server.calls])

    def test_a_transport_error_on_a_poll_is_retried(self):
        server = FakeServer([RUNNING, OSError("303 not followed"), DONE])
        self.assertEqual(self.run_job(server), RESULT)

    def test_too_many_failed_polls_in_a_row_give_up(self):
        errors = [OSError("down")] * (nowcast.MAX_POLL_ERRORS + 1)
        with self.assertRaises(SystemExit) as ctx:
            self.run_job(FakeServer(errors))
        self.assertIn("fc-test", str(ctx.exception))

    def test_a_job_error_is_fatal_not_retried(self):
        server = FakeServer([nowcast.HostedToolError("get_job_result: LinAlgError"), DONE])
        with self.assertRaises(SystemExit) as ctx:
            self.run_job(server)
        self.assertIn("failed", str(ctx.exception))
        self.assertEqual(len(server.polls), 1, "polled again after the job failed")

    def test_a_server_without_the_allow_list_entry_says_redeploy(self):
        refused = nowcast.HostedToolError(
            "start_job: 'svar_forecast' cannot be run as a job. Allowed: score_reform"
        )
        with self.assertRaises(SystemExit) as ctx:
            self.run_job(FakeServer([], start=refused))
        self.assertIn("Redeploy", str(ctx.exception))

    def test_deadline_stops_polling_with_the_job_id(self):
        clock = FakeClock()
        server = FakeServer([RUNNING] * 100, clock=clock)
        with self.assertRaises(SystemExit) as ctx:
            self.run_job(server, deadline=95, clock=clock)
        self.assertIn("fc-test", str(ctx.exception))
        self.assertIn("not done", str(ctx.exception))
        self.assertLessEqual(len(server.calls), 1 + 4)

    def test_deadline_is_inside_the_workflow_step_timeout(self):
        workflow = (ROOT / ".github/workflows/nowcast-round.yml").read_text()
        step = workflow[workflow.index("- name: Generate and archive the round"):]
        minutes = int(step.split("timeout-minutes:")[1].split()[0])
        self.assertLess(nowcast.JOB_DEADLINE_SECONDS, minutes * 60)


class AllowListTests(unittest.TestCase):
    def test_the_hosted_server_allow_lists_the_forecast_adapter(self):
        """The job path only works if the server will run the adapter."""
        tree = ast.parse(
            (ROOT / "integration/src/policyengine_macro/jobs.py").read_text()
        )
        job_tools = next(
            ast.literal_eval(n.value) for n in tree.body
            if isinstance(n, ast.AnnAssign) and getattr(n.target, "id", "") == "JOB_TOOLS"
        )
        self.assertIn(nowcast.JOB_ADAPTER, job_tools)

    def test_the_adapter_is_what_forecast_uk_calls(self):
        server = (
            ROOT / "integration/src/policyengine_macro/mcp_server.py"
        ).read_text()
        body = server[server.index("def forecast_uk("):]
        body = body[: body.index("@mcp.tool()")]
        self.assertIn(f"core.{nowcast.JOB_ADAPTER}(", body)


try:
    import anyio  # noqa: F401 - the workflow installs it with the MCP client
except ImportError:  # the plain-python CI gates run without it
    anyio = None


@unittest.skipIf(anyio is None, "needs anyio, as the round step installs it")
class RealCallPathTests(unittest.TestCase):
    """fetch_forecast's own call function, with the MCP client replaced by
    fakes that hold a live anyio task group the way the real ones do.

    The real streamablehttp_client and ClientSession both run task groups,
    and anything raised inside a task group leaves it as an ExceptionGroup.
    A tool error raised in there would reach run_as_job as a "transport
    error" and be retried, and the redeploy message would never print.
    """

    def fake_mcp(self, replies):
        import contextlib
        import sys
        import types

        import anyio

        @contextlib.asynccontextmanager
        async def background_group():
            async with anyio.create_task_group() as tg:
                tg.start_soon(anyio.sleep_forever)
                try:
                    yield
                finally:
                    tg.cancel_scope.cancel()

        @contextlib.asynccontextmanager
        async def streamablehttp_client(url, timeout):
            async with background_group():
                yield (None, None, None)

        class Result:
            def __init__(self, is_error, text):
                self.isError = is_error
                self.content = [types.SimpleNamespace(text=text)]

        class ClientSession:
            def __init__(self, read, write):
                self._group = background_group()

            async def __aenter__(self):
                await self._group.__aenter__()
                return self

            async def __aexit__(self, *exc):
                return await self._group.__aexit__(*exc)

            async def initialize(self):
                return None

            async def call_tool(self, tool, arguments):
                return Result(*replies[tool])

        mcp = types.ModuleType("mcp")
        mcp.ClientSession = ClientSession
        client = types.ModuleType("mcp.client")
        transport = types.ModuleType("mcp.client.streamable_http")
        transport.streamablehttp_client = streamablehttp_client
        modules = {"mcp": mcp, "mcp.client": client,
                   "mcp.client.streamable_http": transport}
        return mock.patch.dict(sys.modules, modules)

    def test_a_refused_job_tool_says_redeploy_through_real_task_groups(self):
        refused = (True, "'svar_forecast' cannot be run as a job. Allowed: score_reform")
        with self.fake_mcp({"start_job": refused}):
            with self.assertRaises(SystemExit) as ctx:
                nowcast.fetch_forecast(6000, 13)
        self.assertIn("Redeploy", str(ctx.exception))

    def test_a_failed_job_is_fatal_through_real_task_groups(self):
        replies = {
            "start_job": (False, '{"job_id": "fc-test", "status": "running"}'),
            "get_job_result": (True, "LinAlgError: singular matrix"),
        }
        with self.fake_mcp(replies), mock.patch.object(nowcast.time, "sleep"):
            with self.assertRaises(SystemExit) as ctx:
                nowcast.fetch_forecast(6000, 13)
        self.assertIn("hosted job fc-test failed", str(ctx.exception))
        self.assertIn("LinAlgError", str(ctx.exception))

    def test_a_finished_job_returns_its_result_through_real_task_groups(self):
        replies = {
            "start_job": (False, '{"job_id": "fc-test", "status": "running"}'),
            "get_job_result": (False, '{"status": "done", "result": {"ok": 1}}'),
        }
        with self.fake_mcp(replies):
            self.assertEqual(nowcast.fetch_forecast(6000, 13), {"ok": 1})


if __name__ == "__main__":
    unittest.main()
