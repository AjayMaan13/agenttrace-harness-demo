"""Run the workflow once and report it to AgentTrace.

    python -m account_health.run                     # a good run
    python -m account_health.run --bug               # the planted bug: the researcher reads only the first 20 tickets
    python -m account_health.run --account acct-2
    python -m account_health.run --offline           # stand-in agents instead of Claude: no Anthropic key, no tokens

With AGENTTRACE_API_URL and AGENTTRACE_INGEST_KEY set, the run is sent to AgentTrace. Without them it is
printed here, so you can try the workflow before connecting it. `run_workflow` is the same thing as a function,
which is what the page in ui.py calls.
"""

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from agenttrace_sdk import HttpSink, ListSink, RunRecorder

from account_health.agents import claude_agent, offline_agent
from account_health.check import brief_matches_data
from account_health.config import WORKFLOW
from account_health.data import FixtureSource
from account_health.pipeline import run_pipeline
from account_health.tools import ground_truth, ticket_summary


@dataclass
class RunResult:
    run_id: str
    outcome: str  # pass | fail | error
    reason: str  # why, in words: the check's answer
    brief: str
    said: dict[str, Any]  # the numbers the brief stated
    expected: dict[str, Any]  # the numbers the data has
    sent_to: str | None  # the AgentTrace host the run went to, or None if it was only printed
    note: str | None = None


def make_sink():
    url, key = os.environ.get("AGENTTRACE_API_URL"), os.environ.get("AGENTTRACE_INGEST_KEY")
    return HttpSink(url, key) if url and key else ListSink()


async def run_workflow(account: str, bug: bool = False, offline: bool = False) -> RunResult:
    """Run the three agents on one account and record it. Raises LookupError for an unknown account."""
    source = FixtureSource()
    expected = await ground_truth(source, account)
    note = None
    if bug and (await ticket_summary(source, account, bug=True))["open_tickets"] == expected["open_tickets"]:
        note = f"{account} has too few tickets for the bug to change the answer, so this run will probably pass"

    sink = make_sink()
    agent = (offline_agent if offline else claude_agent)(source, bug)
    async with RunRecorder(sink, WORKFLOW, oracle=brief_matches_data) as rec:
        rec.final_state = await run_pipeline({"account_id": account, "expected": expected}, rec, agent)

    state = rec.final_state
    sent_to = urlparse(os.environ["AGENTTRACE_API_URL"]).netloc if isinstance(sink, HttpSink) else None
    return RunResult(
        run_id=rec.id, outcome=rec.outcome, reason=brief_matches_data(state)[1], brief=state["brief"],
        said={"open_tickets": state["open_tickets"], "open_pipeline_usd": state["open_pipeline_usd"]},
        expected=expected, sent_to=sent_to, note=note,
    )


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", default=os.environ.get("DEMO_ACCOUNT_ID", "acct-1"))
    ap.add_argument("--bug", action="store_true", help="plant the bug: the researcher reads only the first page of tickets")
    ap.add_argument("--offline", action="store_true", help="use stand-in agents that answer from the lookups, instead of calling Claude")
    args = ap.parse_args()

    try:
        result = await run_workflow(args.account, args.bug, args.offline)
    except LookupError as e:
        print(e)
        return 2
    if result.note:
        print(f"note: {result.note}")
    print(f"run {result.run_id}  ({'sent to AgentTrace' if result.sent_to else 'not sent: no AGENTTRACE_* settings'})")
    print(f"brief: {result.brief}")
    print(f"said {result.said['open_tickets']} open tickets and ${float(result.said['open_pipeline_usd']):,.2f}; "
          f"the data has {result.expected['open_tickets']} and ${result.expected['open_pipeline_usd']:,.2f}")
    print(f"check: {result.outcome}")
    return 0 if result.outcome == "pass" else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
