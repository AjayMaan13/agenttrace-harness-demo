"""Let AgentTrace fork this workflow. Run it next to your code; it connects out to AgentTrace and nothing connects in.

    python -m account_health.worker

Needs a key with the `worker` scope. When you fork a run in AgentTrace, it hands this process the recorded
state up to the fork point (with your edit applied) and the stages after it run again, live, here.
"""

import asyncio
import os

from agenttrace_sdk import Worker

from account_health.agents import claude_agent
from account_health.check import brief_matches_data
from account_health.config import WORKFLOW
from account_health.data import FixtureSource
from account_health.pipeline import run_pipeline


def make_worker() -> Worker:
    source = FixtureSource()

    async def resume(state, rec):
        return await run_pipeline(state, rec, claude_agent(source))

    worker = Worker(os.environ["AGENTTRACE_API_URL"], os.environ["AGENTTRACE_WORKER_KEY"], name="account-health")
    # safe_to_rerun: a fork runs the agents again, live, several times. Ours only read data, so that is safe.
    worker.register(WORKFLOW, resume, oracle=brief_matches_data, safe_to_rerun=True)
    return worker


if __name__ == "__main__":
    asyncio.run(make_worker().run_forever())
