"""Run one agent with the Claude Agent SDK and hand back what it answered and which tools it called.

`claude_agent(...)` returns the function the pipeline calls for each stage. Tests pass a fake in its place.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, ToolResultBlock, ToolUseBlock, UserMessage, query

from account_health.config import MODEL
from account_health.tools import build_server, pipeline_summary, ticket_summary

OFFLINE_MODEL = "offline-stand-in"
TOOL_PREFIX = "mcp__data__"
TOOLS = [TOOL_PREFIX + "ticket_summary", TOOL_PREFIX + "pipeline_summary"]


@dataclass
class Reply:
    data: dict[str, Any]
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    model: str = MODEL


def parse_json(text: str) -> dict[str, Any]:
    """The agent was told to answer with JSON only, but may still wrap it in a code fence."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("the agent did not answer with JSON")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("the agent's JSON was not an object")
    return data


def _result_value(content: Any) -> Any:
    """A tool result arrives as a list of text blocks; ours hold JSON."""
    text = "".join(b.get("text", "") for b in content if isinstance(b, dict)) if isinstance(content, list) else str(content)
    try:
        return json.loads(text)
    except ValueError:
        return text


def claude_agent(source: Any, bug: bool = False, query_fn: Any = query):
    async def agent(stage: Any, inp: dict[str, Any]) -> Reply:
        options = ClaudeAgentOptions(
            system_prompt=stage.system,
            model=MODEL,
            tools=[],  # none of Claude Code's built-in tools: only the lookups below
            mcp_servers={"data": build_server(source, bug)} if stage.uses_tools else {},
            allowed_tools=TOOLS if stage.uses_tools else [],
            max_turns=6 if stage.uses_tools else 1,
            setting_sources=[],  # ignore any CLAUDE.md or settings on this machine
        )
        calls: dict[str, dict[str, Any]] = {}
        final = None
        async for msg in query_fn(prompt=json.dumps(inp), options=options):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, ToolUseBlock):
                        calls[block.id] = {"name": block.name.removeprefix(TOOL_PREFIX), "args": block.input, "result": None}
            elif isinstance(msg, UserMessage) and isinstance(msg.content, list):
                for block in msg.content:
                    if isinstance(block, ToolResultBlock) and block.tool_use_id in calls:
                        calls[block.tool_use_id]["result"] = _result_value(block.content)
            elif isinstance(msg, ResultMessage):
                final = msg
        if final is None or final.is_error:
            raise RuntimeError(f"the {stage.name} agent failed ({getattr(final, 'subtype', 'no result')})")
        usage = final.usage or {}
        return Reply(parse_json(final.result or ""), list(calls.values()), usage.get("input_tokens", 0), usage.get("output_tokens", 0))

    return agent


def offline_agent(source: Any, bug: bool = False):
    """Stand-ins for the three agents that answer from the real lookups and a simple rule, with no model call.
    They let you try the AgentTrace connection with no Anthropic key and no tokens. Their turns say so
    (model "offline-stand-in") so nobody mistakes them for Claude."""

    async def agent(stage: Any, inp: dict[str, Any]) -> Reply:
        if stage.name == "researcher":
            account = inp["account_id"]
            t, p = await ticket_summary(source, account, bug), await pipeline_summary(source, account)
            calls = [{"name": "ticket_summary", "args": {"account_id": account}, "result": t},
                     {"name": "pipeline_summary", "args": {"account_id": account}, "result": p}]
            return Reply({"open_tickets": t["open_tickets"], "open_pipeline_usd": p["open_pipeline_usd"]}, calls, model=OFFLINE_MODEL)
        if stage.name == "analyst":
            n = inp["facts"]["open_tickets"]
            risk = "high" if n >= 15 else "medium" if n >= 5 else "low"
            return Reply({"risk": risk, "reason": f"{n} open tickets"}, model=OFFLINE_MODEL)
        facts, risk = inp["facts"], inp["risk"]["risk"]
        brief = f"{facts['open_tickets']} open tickets and ${facts['open_pipeline_usd']:,.2f} in open deals. Renewal risk is {risk}."
        return Reply({"brief": brief, "open_tickets": facts["open_tickets"], "open_pipeline_usd": facts["open_pipeline_usd"]}, model=OFFLINE_MODEL)

    return agent
