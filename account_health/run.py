"""Run the workflow once and report it to AgentTrace.

    python -m account_health.run                     # a good run
    python -m account_health.run --bug               # the planted bug: the researcher reads only the first 20 tickets
    python -m account_health.run --account acct-2
    python -m account_health.run --offline           # stand-in agents instead of Claude: no Anthropic key, no tokens

With AGENTTRACE_API_URL and AGENTTRACE_INGEST_KEY set, the run is sent to AgentTrace. Without them it is
printed here, so you can try the workflow before connecting it.
"""

import argparse
import asyncio
import os
import sys

from agenttrace_sdk import HttpSink, ListSink, RunRecorder

from account_health.agents import claude_agent, offline_agent
from account_health.check import brief_matches_data
from account_health.config import WORKFLOW
from account_health.data import FixtureSource
from account_health.pipeline import run_pipeline
from account_health.tools import ground_truth, ticket_summary


def make_sink():
    url, key = os.environ.get("AGENTTRACE_API_URL"), os.environ.get("AGENTTRACE_INGEST_KEY")
    return HttpSink(url, key) if url and key else ListSink()


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", default=os.environ.get("DEMO_ACCOUNT_ID", "acct-1"))
    ap.add_argument("--bug", action="store_true", help="plant the bug: the researcher reads only the first page of tickets")
    ap.add_argument("--offline", action="store_true", help="use stand-in agents that answer from the lookups, instead of calling Claude")
    args = ap.parse_args()

    account, source = args.account, FixtureSource()
    try:
        expected = await ground_truth(source, account)
    except LookupError as e:
        print(e)
        return 2
    if args.bug and (await ticket_summary(source, account, bug=True))["open_tickets"] == expected["open_tickets"]:
        print(f"note: {account} has too few tickets for --bug to change the answer, so this run will probably pass")

    sink = make_sink()
    agent = (offline_agent if args.offline else claude_agent)(source, args.bug)
    async with RunRecorder(sink, WORKFLOW, oracle=brief_matches_data) as rec:
        rec.final_state = await run_pipeline({"account_id": account, "expected": expected}, rec, agent)

    state = rec.final_state
    print(f"run {rec.id}  ({'sent to AgentTrace' if isinstance(sink, HttpSink) else 'not sent: no AGENTTRACE_* settings'})")
    print(f"brief: {state['brief']}")
    print(f"said {state['open_tickets']} open tickets and ${float(state['open_pipeline_usd']):,.2f}; the data has {expected['open_tickets']} and ${expected['open_pipeline_usd']:,.2f}")
    print(f"check: {rec.outcome}")
    return 0 if rec.outcome == "pass" else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
