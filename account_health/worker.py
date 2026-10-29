"""Let AgentTrace fork this workflow. Run it next to your code; it connects out to AgentTrace and nothing connects in.

    python -m account_health.worker

Needs a key with the `worker` scope. When you fork a run in AgentTrace, it hands this process the recorded
state up to the fork point (with your edit applied) and the stages after it run again, live, here.

It runs WORKER_JOBS_AT_ONCE jobs side by side (default 3), so a fork of 3 (six jobs) finishes in about two rounds.
"""

import asyncio
import os

from agenttrace_sdk import Worker

from account_health.agents import claude_agent
from account_health.check import brief_matches_data
from account_health.config import WORKER_JOBS_AT_ONCE, WORKFLOW
from account_health.data import FixtureSource
from account_health.pipeline import run_pipeline


def make_worker(name: str = "account-health") -> Worker:
    source = FixtureSource()

    async def resume(state, rec):
        return await run_pipeline(state, rec, claude_agent(source))

    worker = Worker(os.environ["AGENTTRACE_API_URL"], os.environ["AGENTTRACE_WORKER_KEY"], name=name)
    # safe_to_rerun: a fork runs the agents again, live, several times. Ours only read data, so that is safe.
    worker.register(WORKFLOW, resume, oracle=brief_matches_data, safe_to_rerun=True)
    return worker


def make_workers(count: int) -> list[Worker]:
    """A worker takes one job at a time, so several side by side finish a fork sooner. AgentTrace hands each job to one of them."""
    return [make_worker(f"account-health-{i}") for i in range(1, count + 1)]


async def main() -> None:
    await asyncio.gather(*(w.run_forever() for w in make_workers(WORKER_JOBS_AT_ONCE)))


if __name__ == "__main__":
    asyncio.run(main())
