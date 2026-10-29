"""The page's server, offline: stand-in agents, nothing sent anywhere, no tokens."""

import pytest
from agenttrace_sdk import Worker
from starlette.testclient import TestClient

from account_health import ui, worker

OK = {"X-Demo": "1"}


@pytest.fixture
def client(monkeypatch):
    # .env may hold real AgentTrace settings; a test must never send a run there.
    for name in ("AGENTTRACE_API_URL", "AGENTTRACE_INGEST_KEY", "AGENTTRACE_WORKER_KEY"):
        monkeypatch.delenv(name, raising=False)
    ui.runs.clear()
    return TestClient(ui.app)


def test_the_page_is_served(client):
    res = client.get("/")
    assert res.status_code == 200 and "Start worker" in res.text and "Send the wrong run" in res.text


def test_the_buttons_refuse_a_request_that_did_not_come_from_the_page(client):
    assert client.post("/api/run", json={"bug": False, "offline": True}).status_code == 403
    assert client.post("/api/worker/start").status_code == 403


def test_the_right_run_passes(client):
    res = client.post("/api/run", headers=OK, json={"bug": False, "offline": True})
    body = res.json()
    assert res.status_code == 200 and body["outcome"] == "pass" and body["sent_to"] is None
    assert client.get("/api/state").json()["runs"][0]["run_id"] == body["run_id"]


def test_the_wrong_run_fails_and_says_why(client):
    body = client.post("/api/run", headers=OK, json={"bug": True, "offline": True}).json()
    assert body["outcome"] == "fail" and "said 10 open tickets, the data has 20" in body["reason"]


def test_starting_the_worker_without_its_settings_says_what_is_missing(client):
    res = client.post("/api/worker/start", headers=OK)
    assert res.status_code == 400 and "AGENTTRACE_WORKER_KEY" in res.json()["error"]
    assert client.get("/api/state").json()["worker"]["started"] is False


def test_the_state_says_which_settings_exist_but_never_their_values(client, monkeypatch):
    monkeypatch.setenv("AGENTTRACE_WORKER_KEY", "at_live_this_must_not_leak")
    res = client.get("/api/state")
    assert res.json()["setup"]["AGENTTRACE_WORKER_KEY"] is True
    assert "this_must_not_leak" not in res.text


async def test_the_worker_notes_whether_its_last_ask_got_an_answer():
    class Answers:
        def __init__(self, reply):
            self.reply = reply

        async def call(self, method, path, payload=None):
            if isinstance(self.reply, Exception):
                raise self.reply
            return self.reply

    class Refused(Exception):
        detail = "Invalid ingest key"

    quiet = worker._Tracked(client=Answers({"job": None}))
    quiet.register("w", lambda state, rec: state, oracle=lambda s: (True, ""), safe_to_rerun=True)
    assert await quiet.run_once() is False and worker.STATUS["connected"] is True

    refused = worker._Tracked(client=Answers(Refused()))
    refused.register("w", lambda state, rec: state, oracle=lambda s: (True, ""), safe_to_rerun=True)
    with pytest.raises(Refused):
        await refused.run_once()
    assert worker.STATUS == {"connected": False, "detail": "Invalid ingest key"}
    assert isinstance(refused, Worker)
