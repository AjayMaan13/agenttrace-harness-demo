# agenttrace-harness-demo

An example agent workflow, written separately from [AgentTrace](https://github.com/AjayMaan13/AgentTrace), that records its runs into AgentTrace through the **Connect your agents** steps.

Three Claude agents, built on the Claude Agent SDK, write an account health brief:

```
researcher  ->  analyst  ->  writer
(looks up the account's tickets and open deals)   (judges renewal risk)   (writes the brief and states the numbers)
```

A check written in code decides whether the brief is right: the open-ticket count and the open pipeline in the brief must match the data. The data is a small built-in company (`acct-1` with 40 tickets and 3 open deals, `acct-2` with 5 tickets), so nothing outside this repo is needed.

`--bug` plants a failure that shows up far from its cause: the researcher's ticket reader stops after the first 20 tickets and reports that page as if it were all of them. The writer then states the wrong count, the check fails, and AgentTrace can follow the number back to the researcher.

## Run it

```bash
python3.11 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env        # then fill in .env yourself; it is gitignored
.venv/bin/pytest            # offline: no network, no tokens
.venv/bin/python -m account_health.run --offline        # stand-in agents: no Anthropic key, no tokens
.venv/bin/python -m account_health.run                  # a good run, on Claude
.venv/bin/python -m account_health.run --bug            # the planted bug: the check fails
```

Each Claude run makes three small calls (Haiku) and needs `ANTHROPIC_API_KEY`. `--offline` swaps the three agents for stand-ins that answer from the same lookups with a simple rule. It is for trying the AgentTrace connection first; the stand-ins' steps are labelled `offline-stand-in` so nobody mistakes them for Claude.

## Drive it from a page

```bash
.venv/bin/python -m account_health.ui        # then open http://127.0.0.1:8765
```

One page, three buttons: **Start worker** (turns green when AgentTrace has answered), **Send the right run** and **Send the wrong run**. It calls the same code as `run.py` and `worker.py`, shows the check's verdict and the brief, and lists what the worker is doing. It listens on this machine only. Use it instead of the two commands, not next to the worker command (that would start a second worker).

## Connect it to AgentTrace

1. In AgentTrace, open **Connect your agents** and **make a key** that can send runs. Put it in `.env` as `AGENTTRACE_INGEST_KEY`, with your API address as `AGENTTRACE_API_URL`.
2. The recorder is already wired in (`account_health/run.py`): `RunRecorder` records one turn per agent, with the tools it called, and the check gives the run a verdict.
3. Run it. The run appears in AgentTrace under your workspace; a `--bug` run shows as wrong with the check's reason, and goes to Slack if you set up alerts.

Without those two settings the run is printed here instead of sent.

## Fork it (optional)

Make a second key that can **run forks** and put it in `.env` as `AGENTTRACE_WORKER_KEY`, then:

```bash
.venv/bin/python -m account_health.worker
```

The worker connects out to AgentTrace; nothing connects in. It runs `WORKER_JOBS_AT_ONCE` jobs side by side (default 3), so a fork finishes sooner; AgentTrace hands each job to only one of them. In AgentTrace, open a `--bug` run, fork at the researcher with the right facts, and the analyst and writer run again here, live, with and without the change. Live steps are sampled, so AgentTrace repeats each side and reports k of N with a p-value, labelled directional.

`safe_to_rerun=True` in `account_health/worker.py` is a statement that re-running these agents is harmless. It is, because they only read data.

## What is here

| File | What it does |
| --- | --- |
| `account_health/pipeline.py` | The three stages, and the loop that records each as a turn. A stage is skipped if the state already holds its answer, which is how a fork resumes. |
| `account_health/agents.py` | Runs one agent with the Claude Agent SDK and collects its answer and tool calls; also the offline stand-ins. |
| `account_health/tools.py` | The lookups (and the planted bug), offered to the researcher as tools. |
| `account_health/data.py` | The built-in company. |
| `account_health/check.py` | The right-or-wrong check. |
| `account_health/run.py`, `worker.py` | Run once; run as a fork worker. |
| `account_health/ui.py`, `ui.html` | The page with the three buttons. |

## Limits

- This is one example workflow, not an adapter. It shows that an agent built on the Claude Agent SDK can report into AgentTrace by calling the recorder; it does not make the Claude Agent SDK "supported".
- Results from forks are directional, never proof.
