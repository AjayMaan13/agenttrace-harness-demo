"""The workflow: researcher -> analyst -> writer, one recorded turn each, run as a LangGraph graph.

Each stage is a node of a LangGraph `StateGraph`; the edges run them in order over one shared state. LangGraph
decides what runs next. What each node does is unchanged: call the Claude agent for that stage and record a turn.

A node runs its stage only if the state does not already hold what it writes, which is also what lets a fork
resume: AgentTrace hands back the state up to the fork point (with the edit applied) and the nodes after it run
again, live. The nodes record their own turns with the AgentTrace recorder (tool calls, tokens, state), so the run
stays forkable; the SDK's `record_langgraph` adapter reads only the update stream and would give a view-only run.
"""

import time
from dataclasses import dataclass
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph



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


class AccountState(TypedDict, total=False):
    """The graph's shared state: every key a stage reads or writes, plus the two the run starts with."""

    account_id: str
    expected: dict[str, Any]  # what the data says, for the check; no stage reads it
    facts: dict[str, Any]  # researcher
    risk: dict[str, Any]  # analyst
    brief: str  # writer
    open_tickets: Any
    open_pipeline_usd: Any


def _node(stage: Stage, rec: Any, agent: Any):
    """One graph node: run the stage's agent, record a turn, return the keys it wrote."""

    async def run(state: AccountState) -> dict[str, Any]:
        if stage.writes[0] in state:
            return {}  # already there: recorded before the fork point, or edited
        inp = {k: state[k] for k in stage.reads}
        started = time.monotonic()
        reply = await agent(stage, inp)
        update = stage.apply(reply.data)
        await rec.turn(
            stage.name, input=inp, output=reply.data, model=reply.model, tool_calls=reply.tool_calls,
            state_after={**state, **update}, reads=list(stage.reads), writes=list(stage.writes),
            tokens_in=reply.tokens_in, tokens_out=reply.tokens_out, latency_ms=int((time.monotonic() - started) * 1000),
        )
        return update

    return run


def build_graph(rec: Any, agent: Any):
    """The compiled LangGraph graph: START -> researcher -> analyst -> writer -> END."""
    graph = StateGraph(AccountState)
    previous = START
    for stage in STAGES:
        graph.add_node(stage.name, _node(stage, rec, agent))
        graph.add_edge(previous, stage.name)
        previous = stage.name
    graph.add_edge(previous, END)
    return graph.compile()


async def run_pipeline(state: dict[str, Any], rec: Any, agent: Any) -> dict[str, Any]:
    """Run the graph from `state`: every node whose answer the state does not already hold, recording each as a turn.
    Returns the final state."""
    return await build_graph(rec, agent).ainvoke(state)
