"""Settings in one place. The model id lives here and nowhere else."""

import os

from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-haiku-5-5"
WORKFLOW = "account-health-brief"  # the name this workflow has in AgentTrace
OPEN_STATUSES = ("new", "open", "pending", "hold")  # "open" for the check: everything not yet solved or closed
# How many fork jobs the worker runs at once. Each one starts a Claude process, so keep it small on a small laptop.
WORKER_JOBS_AT_ONCE = max(1, min(int(os.environ.get("WORKER_JOBS_AT_ONCE", "3")), 6))
