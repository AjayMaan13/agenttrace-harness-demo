"""Offline tests: no network, no tokens. A fake agent stands in for Claude but uses the real tools and pipeline."""

import pytest
from agenttrace_sdk import ListSink, RunRecorder
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolResultBlock, ToolUseBlock, UserMessage

from account_health.agents import claude_agent, offline_agent, parse_json
from account_health.check import brief_matches_data
from account_health.data import FixtureSource
from account_health.pipeline import run_pipeline
from account_health.tools import build_server, ground_truth

SOURCE = FixtureSource()


def fake_agent(bug=False, seen=None):
    """The offline stand-ins: real lookups and the real pipeline, no model. `seen` collects the stages that ran."""
    inner = offline_agent(SOURCE, bug)

    async def agent(stage, inp):
        if seen is not None:
            seen.append(stage.name)
        return await inner(stage, inp)

    return agent


async def record(account, agent, start=None):
    sink = ListSink()
    state = start or {"account_id": account, "expected": await ground_truth(SOURCE, account)}
    async with RunRecorder(sink, "account-health-brief", oracle=brief_matches_data) as rec:
        rec.final_state = await run_pipeline(state, rec, agent)
    return rec, sink


async def test_good_run_passes_and_records_every_agent():
    rec, sink = await record("acct-1", fake_agent())
    assert rec.outcome == "pass"
    steps = sink.steps_for(rec.id)
    assert [s["agent"] for s in steps if s["kind"] == "llm"] == ["researcher", "analyst", "writer"]
    assert {s["model"] for s in steps if s["kind"] == "llm"} == {"offline-stand-in"}  # stand-ins say so; they are not Claude
    assert [s["tool_name"] for s in steps if s["kind"] == "tool"] == ["ticket_summary", "pipeline_summary"]
    assert steps[-1]["state_after"]["open_tickets"] == 20  # the state is kept, so a fork can resume from it
    assert {s["agent"]: s["writes"] for s in steps if s["kind"] == "llm"}["researcher"] == ["facts"]


async def test_planted_bug_gives_a_wrong_brief_and_the_check_says_why():
    rec, _ = await record("acct-1", fake_agent(bug=True))
    assert rec.outcome == "fail"
    ok, reason = brief_matches_data(rec.final_state)
    assert not ok and "said 10 open tickets, the data has 20" in reason


async def test_bug_cannot_change_a_small_account():
    rec, _ = await record("acct-2", fake_agent(bug=True))
    assert rec.outcome == "pass"


async def test_resume_with_the_fixed_facts_skips_the_researcher_and_passes():
    truth = await ground_truth(SOURCE, "acct-1")
    start = {"account_id": "acct-1", "expected": truth, "facts": {"open_tickets": 20, "open_pipeline_usd": 77000.5}}
    seen: list[str] = []
    rec, _ = await record("acct-1", fake_agent(seen=seen), start)
    assert seen == ["analyst", "writer"] and rec.outcome == "pass"


async def test_resume_without_the_change_keeps_the_wrong_facts_and_fails():
    truth = await ground_truth(SOURCE, "acct-1")
    start = {"account_id": "acct-1", "expected": truth, "facts": {"open_tickets": 10, "open_pipeline_usd": 77000.5}}
    rec, _ = await record("acct-1", fake_agent(), start)
    assert rec.outcome == "fail"


def test_check_handles_missing_and_text_numbers():
    want = {"open_tickets": 20, "open_pipeline_usd": 77000.5}
    assert brief_matches_data({"expected": want, "open_tickets": "20", "open_pipeline_usd": "77000.50"})[0]
    assert brief_matches_data({"expected": want})[1] == "the brief did not state both numbers"


def test_parse_json_accepts_a_code_fence_and_refuses_prose():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(ValueError):
        parse_json("no json here")


async def test_claude_agent_collects_the_answer_tool_calls_and_tokens():
    options_seen = []

    async def fake_query(*, prompt, options):
        options_seen.append(options)
        yield AssistantMessage(content=[ToolUseBlock(id="t1", name="mcp__data__ticket_summary", input={"account_id": "acct-1"})], model="m")
        yield UserMessage(content=[ToolResultBlock(tool_use_id="t1", content=[{"type": "text", "text": '{"open_tickets": 20}'}])])
        yield AssistantMessage(content=[TextBlock(text="done")], model="m")
        yield ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=2, session_id="s",
                            result='{"open_tickets": 20, "open_pipeline_usd": 1}', usage={"input_tokens": 5, "cache_creation_input_tokens": 20, "cache_read_input_tokens": 25, "output_tokens": 7})

    from account_health.pipeline import STAGES

    reply = await claude_agent(SOURCE, query_fn=fake_query)(STAGES[0], {"account_id": "acct-1"})
    assert reply.data["open_tickets"] == 20
    assert reply.tool_calls == [{"name": "ticket_summary", "args": {"account_id": "acct-1"}, "result": {"open_tickets": 20}}]
    assert (reply.tokens_in, reply.tokens_out) == (50, 7)
    assert options_seen[0].tools == [] and "data" in options_seen[0].mcp_servers  # the researcher gets the lookups

    await claude_agent(SOURCE, query_fn=fake_query)(STAGES[2], {"facts": {}, "risk": {}})
    assert options_seen[1].mcp_servers == {} and options_seen[1].allowed_tools == []  # the writer gets none


async def test_claude_agent_raises_when_the_agent_fails():
    async def failing(*, prompt, options):
        yield ResultMessage(subtype="error_during_execution", duration_ms=1, duration_api_ms=1, is_error=True, num_turns=1, session_id="s")

    from account_health.pipeline import STAGES

    with pytest.raises(RuntimeError, match="researcher agent failed"):
        await claude_agent(SOURCE, query_fn=failing)(STAGES[0], {"account_id": "acct-1"})


def test_the_worker_runs_several_jobs_side_by_side(monkeypatch):
    from account_health import worker as worker_module

    monkeypatch.setenv("AGENTTRACE_API_URL", "http://localhost:1")
    monkeypatch.setenv("AGENTTRACE_WORKER_KEY", "not-a-real-key")
    workers = worker_module.make_workers(3)
    assert [w.name for w in workers] == ["account-health-1", "account-health-2", "account-health-3"]
    assert all("account-health-brief" in w._flows for w in workers)
    assert 1 <= worker_module.WORKER_JOBS_AT_ONCE <= 6


async def test_a_fork_job_prints_when_it_starts_and_when_it_ends(monkeypatch, capsys):
    from account_health import worker as worker_module

    monkeypatch.setenv("AGENTTRACE_API_URL", "http://localhost:1")
    monkeypatch.setenv("AGENTTRACE_WORKER_KEY", "not-a-real-key")
    monkeypatch.setattr(worker_module, "claude_agent", lambda source: fake_agent())  # no model call
    resume = worker_module.make_worker("w1")._flows["account-health-brief"].resume
    truth = await ground_truth(SOURCE, "acct-1")
    state = {"account_id": "acct-1", "expected": truth, "facts": {"open_tickets": 20, "open_pipeline_usd": 77000.5}}
    async with RunRecorder(ListSink(), "account-health-brief", oracle=brief_matches_data) as rec:
        rec.final_state = await resume(state, rec)
    out = capsys.readouterr().out
    assert "[w1] fork job taken, starting from facts = {'open_tickets': 20" in out
    assert "[w1] fork job done" in out and ": pass (" in out


def test_the_lookups_are_offered_as_an_in_process_server():
    server = build_server(SOURCE)
    assert server["type"] == "sdk" and server["name"] == "data"
