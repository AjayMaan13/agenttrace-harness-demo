"""What the researcher can look up. Plain functions first, so tests and the check can call them without an agent.

The planted bug (`bug=True`): the ticket reader stops after the first page of 20 tickets and reports that page
as if it were all of them. The agent cannot tell, and neither can a reader of the trace until they follow the
number back to this step.
"""

import json
from collections import Counter
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from account_health.config import OPEN_STATUSES

TICKET_PAGE = 20


async def ticket_summary(source: Any, account_id: str, bug: bool = False) -> dict[str, Any]:
    tickets = await source.tickets(account_id)
    if bug:
        tickets = tickets[:TICKET_PAGE]
    return {
        "account_id": account_id,
        "open_tickets": sum(t["status"] in OPEN_STATUSES for t in tickets),
        "by_status": dict(Counter(t["status"] for t in tickets)),
    }


async def pipeline_summary(source: Any, account_id: str) -> dict[str, Any]:
    open_deals = [o for o in await source.opportunities(account_id) if not o["IsClosed"]]
    # Summed here, in code: model arithmetic over amounts is flaky.
    return {"account_id": account_id, "open_deals": len(open_deals), "open_pipeline_usd": round(sum(o["Amount"] or 0 for o in open_deals), 2)}


async def ground_truth(source: Any, account_id: str) -> dict[str, Any]:
    """The right answer, read straight from the data and never through the agents."""
    return {
        "open_tickets": (await ticket_summary(source, account_id))["open_tickets"],
        "open_pipeline_usd": (await pipeline_summary(source, account_id))["open_pipeline_usd"],
    }


def build_server(source: Any, bug: bool = False):
    """The two lookups as tools the Claude Agent SDK can call (an in-process MCP server named "data")."""

    def reply(data: dict[str, Any]) -> dict[str, Any]:
        return {"content": [{"type": "text", "text": json.dumps(data)}]}

    @tool("ticket_summary", "Count a customer's open support tickets.", {"account_id": str})
    async def tickets(args: dict[str, Any]) -> dict[str, Any]:
        return reply(await ticket_summary(source, args["account_id"], bug))

    @tool("pipeline_summary", "Total value of a customer's open deals.", {"account_id": str})
    async def pipeline(args: dict[str, Any]) -> dict[str, Any]:
        return reply(await pipeline_summary(source, args["account_id"]))

    return create_sdk_mcp_server("data", tools=[tickets, pipeline])
