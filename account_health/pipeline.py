"""The workflow: researcher -> analyst -> writer, one recorded turn each.

The shared state is a dict. A stage runs only if the state does not already hold what it writes, which is
also what lets a fork resume: AgentTrace hands back the state up to the fork point (with the edit applied) and
the stages after it run again, live.
"""

import time
from dataclasses import dataclass
from typing import Any



@dataclass(frozen=True)
class Stage:
    name: str
    system: str
    reads: tuple[str, ...]
    writes: tuple[str, ...]
    wrap: str | None = None  # store the whole answer under this key; None keeps the answer's own keys
    uses_tools: bool = False

    def apply(self, data: dict[str, Any]) -> dict[str, Any]:
        return {self.wrap: data} if self.wrap else {k: data.get(k) for k in self.writes}


STAGES = [
    Stage(
        "researcher",
        "You are the researcher for an account health brief. Call ticket_summary and pipeline_summary for the account, "
        'then reply with ONLY a JSON object: {"open_tickets": <int>, "open_pipeline_usd": <number>}. '
        "Copy the numbers the tools return; never estimate.",
        reads=("account_id",), writes=("facts",), wrap="facts", uses_tools=True,
    ),
    Stage(
        "analyst",
        "You are the analyst. Judge the renewal risk from the facts. Many open tickets mean higher risk. "
        'Reply with ONLY a JSON object: {"risk": "low" | "medium" | "high", "reason": "<one sentence>"}.',
        reads=("facts",), writes=("risk",), wrap="risk",
    ),
    Stage(
        "writer",
        "You are the writer. Write a three-sentence account health brief from the facts and the risk. "
        'Reply with ONLY a JSON object: {"brief": "<the brief>", "open_tickets": <int>, "open_pipeline_usd": <number>}. '
        "Copy both numbers exactly from the facts.",
        reads=("facts", "risk"), writes=("brief", "open_tickets", "open_pipeline_usd"),
    ),
]


async def run_pipeline(state: dict[str, Any], rec: Any, agent: Any) -> dict[str, Any]:
    """Run every stage the state has not already got the answer to, recording each as a turn. Returns the final state."""
    for stage in STAGES:
        if stage.writes[0] in state:
            continue  # already there: recorded before the fork point, or edited
        inp = {k: state[k] for k in stage.reads}
        started = time.monotonic()
        reply = await agent(stage, inp)
        state = {**state, **stage.apply(reply.data)}
        await rec.turn(
            stage.name, input=inp, output=reply.data, model=reply.model, tool_calls=reply.tool_calls,
            state_after=state, reads=list(stage.reads), writes=list(stage.writes),
            tokens_in=reply.tokens_in, tokens_out=reply.tokens_out, latency_ms=int((time.monotonic() - started) * 1000),
        )
    return state
