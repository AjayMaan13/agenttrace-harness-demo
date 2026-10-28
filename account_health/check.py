"""The right-or-wrong check, written in code: the numbers in the brief must match what the data says.

AgentTrace stores its result as the run's verdict. It is a check on two numbers, not an AI judge.
"""

from typing import Any


def brief_matches_data(state: dict[str, Any]) -> tuple[bool, str]:
    want = state["expected"]
    try:
        tickets = int(state["open_tickets"])
        pipeline = float(state["open_pipeline_usd"])
    except (KeyError, TypeError, ValueError):
        return False, "the brief did not state both numbers"
    problems = []
    if tickets != want["open_tickets"]:
        problems.append(f"said {tickets} open tickets, the data has {want['open_tickets']}")
    if abs(pipeline - want["open_pipeline_usd"]) > 0.5:
        problems.append(f"said ${pipeline:,.2f} open pipeline, the data has ${want['open_pipeline_usd']:,.2f}")
    return (not problems, "; ".join(problems) or "the brief's numbers match the data")
