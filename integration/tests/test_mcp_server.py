"""End-to-end MCP server test over stdio using the official mcp client."""

import json
import sys

import pytest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = StdioServerParameters(command=sys.executable, args=["-m", "macromod.mcp_server"])

EXPECTED_TOOLS = {
    "score_reform",
    "list_reform_variables",
    "forecast_uk",
    "latest_shocks",
    "model_summary",
}


def _payload(result):
    assert not result.isError, result.content
    return json.loads(result.content[0].text)


@pytest.mark.anyio
async def test_mcp_tools_and_calls():
    async with stdio_client(SERVER) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            assert EXPECTED_TOOLS <= names

            res = await session.call_tool("model_summary", {})
            summary = _payload(res)
            assert "replication" in summary

            res = await session.call_tool(
                "score_reform", {"var": "CGG", "shock": 1250, "periods": 4}
            )
            score = _payload(res)
            assert score["var"] == "CGG"
            assert score["results"][0]["delta_gdp_bn"] > 0


@pytest.fixture
def anyio_backend():
    return "asyncio"
