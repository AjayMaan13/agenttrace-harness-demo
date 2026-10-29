"""Let AgentTrace fork this workflow. Run it next to your code; it connects out to AgentTrace and nothing connects in.

    python -m account_health.worker

Needs a key with the `worker` scope. When you fork a run in AgentTrace, it hands this process the recorded
state up to the fork point (with your edit applied) and the stages after it run again, live, here.

It runs WORKER_JOBS_AT_ONCE jobs side by side (default 3), so a fork of 3 (six jobs) finishes in about two rounds.
It prints a line when it starts, when it takes a fork job, and when the job is done.
"""

import asyncio
import logging
import os
import time
from collections import deque
from typing import Any
from urllib.parse import urlparse

from agenttrace_sdk import Worker

from account_health.agents import claude_agent
from account_health.check import brief_matches_data
from account_health.config import WORKER_JOBS_AT_ONCE, WORKFLOW
from account_health.data import FixtureSource
from account_health.pipeline import run_pipeline

HEARTBEAT_S = 30
jobs_done = 0

# What the page in ui.py shows: the last lines said, and whether the last call to AgentTrace worked.
LOG: deque[dict[str, str]] = deque(maxlen=60)
STATUS: dict[str, Any] = {"connected": None, "detail": ""}  # connected is None until the first call comes back


def say(who: str, text: str) -> None:
    stamp = time.strftime("%H:%M:%S")
    LOG.append({"time": stamp, "who": who, "text": text})
    print(f"{stamp} [{who}] {text}", flush=True)


class _Tracked(Worker):
    """The SDK worker, noting whether its last ask for a job got an answer (run_once is its public step)."""

    async def run_once(self) -> bool:
        try:
            busy = await super().run_once()
        except Exception as exc:
            STATUS.update(connected=False, detail=str(getattr(exc, "detail", "") or type(exc).__name__))
            raise
        STATUS.update(connected=True, detail="")
        return busy


def make_worker(name: str = "account-health") -> Worker:
    source = FixtureSource()

    async def resume(state, rec):
        global jobs_done
        say(name, f"fork job taken, starting from facts = {state.get('facts', 'none in the state')}")
        started = time.monotonic()
        try:
            final = await run_pipeline(state, rec, claude_agent(source))
        except Exception as exc:  # the SDK counts this job as an error run; say so here too
            say(name, f"fork job failed after {time.monotonic() - started:.0f}s: {type(exc).__name__}")
            raise
        jobs_done += 1
        ok, reason = brief_matches_data(final)
        say(name, f"fork job done in {time.monotonic() - started:.0f}s: {'pass' if ok else 'fail'} ({reason})")
        return final

    worker = _Tracked(os.environ["AGENTTRACE_API_URL"], os.environ["AGENTTRACE_WORKER_KEY"], name=name)
    # safe_to_rerun: a fork runs the agents again, live, several times. Ours only read data, so that is safe.
    worker.register(WORKFLOW, resume, oracle=brief_matches_data, safe_to_rerun=True)
    return worker


def make_workers(count: int) -> list[Worker]:
    """A worker takes one job at a time, so several side by side finish a fork sooner. AgentTrace hands each job to one of them."""
    return [make_worker(f"account-health-{i}") for i in range(1, count + 1)]


async def heartbeat() -> None:
    while True:
        await asyncio.sleep(HEARTBEAT_S)
        say("worker", f"still waiting for forks ({jobs_done} jobs done so far)")


async def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S")  # key and network problems
    host = urlparse(os.environ["AGENTTRACE_API_URL"]).netloc
    say("worker", f"started {WORKER_JOBS_AT_ONCE} workers, asking {host} for fork jobs every few seconds (Ctrl+C to stop)")
    await asyncio.gather(heartbeat(), *(w.run_forever() for w in make_workers(WORKER_JOBS_AT_ONCE)))


if __name__ == "__main__":
    asyncio.run(main())
