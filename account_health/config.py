"""Settings in one place. The model id lives here and nowhere else."""

from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-haiku-5-5"
WORKFLOW = "account-health-brief"  # the name this workflow has in AgentTrace
OPEN_STATUSES = ("new", "open", "pending", "hold")  # "open" for the check: everything not yet solved or closed
