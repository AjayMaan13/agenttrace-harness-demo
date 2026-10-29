"""A page to drive the demo: start the worker, then send a right run or a wrong one.

    python -m account_health.ui        # then open http://127.0.0.1:8765

It is a convenience around run.py and worker.py, nothing more. It listens on this machine only, and its
buttons only work from its own page (they need a header that another website cannot send).
"""

import asyncio
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from account_health import worker
from account_health.config import WORKER_JOBS_AT_ONCE
from account_health.run import run_workflow

PORT = int(os.environ.get("DEMO_UI_PORT", "8765"))
PAGE = Path(__file__).with_name("ui.html")

tasks: list[asyncio.Task] = []  # the running workers; kept so they are not garbage collected
runs: list[dict[str, Any]] = []  # newest first
run_lock = asyncio.Lock()


def denied(request: Request) -> Response | None:
    """A page on another website cannot add this header to a request, so only our own page gets through."""
    if request.headers.get("x-demo") != "1":
        return JSONResponse({"error": "Use the buttons on the page."}, status_code=403)
    return None


def worker_state() -> dict[str, Any]:
    host = urlparse(os.environ.get("AGENTTRACE_API_URL", "")).netloc
    return {"started": bool(tasks), "host": host, "jobs_done": worker.jobs_done, **worker.STATUS}


async def page(_: Request) -> Response:
    return HTMLResponse(PAGE.read_text())


async def state(_: Request) -> Response:
    return JSONResponse({
        "worker": worker_state(),
        "log": list(worker.LOG)[-25:],
        "runs": runs[:5],
        "running": run_lock.locked(),
        # Which settings exist, never their values.
        "setup": {name: bool(os.environ.get(name)) for name in ("AGENTTRACE_API_URL", "AGENTTRACE_INGEST_KEY", "AGENTTRACE_WORKER_KEY", "ANTHROPIC_API_KEY")},
    })


async def start_worker(request: Request) -> Response:
    if (no := denied(request)) is not None:
        return no
    missing = [n for n in ("AGENTTRACE_API_URL", "AGENTTRACE_WORKER_KEY") if not os.environ.get(n)]
    if missing:
        return JSONResponse({"error": f"Add {' and '.join(missing)} to .env, then restart this page."}, status_code=400)
    if not tasks:
        worker.say("worker", f"started {WORKER_JOBS_AT_ONCE} workers, asking {worker_state()['host']} for fork jobs every few seconds")
        tasks.extend(asyncio.create_task(w.run_forever()) for w in worker.make_workers(WORKER_JOBS_AT_ONCE))
    return JSONResponse({"started": True})


async def send_run(request: Request) -> Response:
    if (no := denied(request)) is not None:
        return no
    if run_lock.locked():
        return JSONResponse({"error": "A run is already going."}, status_code=409)
    try:
        body = await request.json()
    except ValueError:
        body = {}
    bug, offline = bool(body.get("bug")), bool(body.get("offline"))
    async with run_lock:
        try:
            result = await run_workflow(os.environ.get("DEMO_ACCOUNT_ID", "acct-1"), bug, offline)
        except Exception as exc:  # shown on the page; the message never holds a key
            return JSONResponse({"error": f"{type(exc).__name__}: {str(exc)[:200]}"}, status_code=500)
    item = {**asdict(result), "bug": bug, "offline": offline, "time": time.strftime("%H:%M:%S")}
    runs.insert(0, item)
    del runs[10:]
    return JSONResponse(item)


app = Starlette(routes=[
    Route("/", page),
    Route("/api/state", state),
    Route("/api/worker/start", start_worker, methods=["POST"]),
    Route("/api/run", send_run, methods=["POST"]),
])

if __name__ == "__main__":
    print(f"Open http://127.0.0.1:{PORT}  (Ctrl+C to stop)", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
