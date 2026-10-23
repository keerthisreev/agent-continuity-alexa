# Agent Continuity Layer

> **The undercover agent is always watching.**
>
> *Kubernetes keeps services alive. We keep agent workflows alive.*

## The problem (origin story)

I built an AI pipeline that processed thousands of records. One day the
LLM stopped responding. **The container stayed alive. The pipeline kept
running.** When it recovered, I couldn't answer three questions: *when*
did trustworthy output stop, *which* records were affected, and *when*
did the outputs become trustworthy again.

That is not a crash. Every dashboard said healthy. It was an **agent
failure nobody could see**: the process was alive, but the *role* was
dead. This layer exists so that failure is caught, contained, mapped,
and recovered from — with proof.

## What it is

An **independent continuity layer** that sits *underneath* an existing
multi-agent workflow **without modifying the agents**. A deterministic
Sentinel watches every role through a four-layer health vector —
liveness, role contract, capability, business invariants — with
hysteresis so one bad output never causes flapping.

On failure it: **detects** the gray failure → **fences** the dead role
via epoch tokens (no split brain) → **resumes** unfinished work from a
continuity package via a hot standby (never restarts) → **maps** exactly
which work was affected → **verifies** recovery with probes before the
original agent rejoins at a new epoch → **records** everything in a
forensic ledger.

```
                    YOUR AGENTS (untouched)
   triage ---> diagnosis ---> remediation ---> escalation
      |            |              |               |
      +------------+------+-------+---------------+   observation only:
      v            v      v       v                   inputs, outputs, effects
  +=================================================+
  |            CONTINUITY LAYER                      |
  |  adapter.py    register / invoke / apply_effects |
  |  sentinel.py   4-layer health + hysteresis       |
  |  canary.py     suspicion-triggered capability    |
  |                probes (behavioral oracles)       |
  |  checkpoint.py continuity packages (resume)     |
  |  fencing.py    epoch authority (no split brain)  |
  |  standby.py    hot-standby lifecycle             |
  |  ledger.py     forensic record + affected-work   |
  |  metrics.py    TSFD / TRV / AFR                  |
  |  diagnostician.py  OPTIONAL model notes +        |
  |                    narratives (advisory only)    |
  +=================================================+
      v
  incident store (your existing infrastructure,
                  epoch-fenced + idempotent writes)
```

**Design rules (frozen):**
- Agents are never modified — the layer observes inputs/outputs/effects
  through the adapter boundary only (`agents/` never imports `continuity/`).
- The deterministic sentinel is always authoritative. The model writes
  canary scenarios and forensic narratives; the deterministic oracle judges
  every probe and verdicts are identical with the model disabled.
- Canaries are suspicion-triggered, never continuous.
- No split brain: stale epochs are rejected until revalidation.
- Resume, not restart: completed actions are never redone.

## Quickstart

**Local:**
```bash
pip install -r requirements.txt
python3 test_continuity.py   # 13/13: the brutal proof
python3 test_robust.py       #  9/9: hardening (config, threads, export, dashboard, client)
python3 test_nemotron.py     # 12/12: model seam, offline-safe
python3 test_mcp.py          # 11/11: MCP read-only ledger
python3 test_showcase.py     #  7/7: dashboard scenario gallery
python3 test_sim.py          # 18/18: Alexa+ sim (initiate -> interrupt -> resume + booking flow)
python3 test_journal.py      # 21/21: operation journal + gateway + lost-ack scenario
python3 demo.py              # the story, zero narration
python3 demo.py --failure gray
python3 dashboard/app.py     # live dashboard -> http://127.0.0.1:5000/
python3 examples/wrap_existing.py   # wrap YOUR agent shape without touching it
```

Run everything at once:
```bash
for t in test_continuity test_robust test_nemotron test_mcp test_showcase test_sim test_journal; do python3 $t.py; done
# expected: 91/91 green, zero network calls, no API keys required
```

**Alexa+ track submission (simulated Alexa+ experience, this repo's `main` branch):**
```bash
python3 dashboard/app.py     # -> http://127.0.0.1:5000/sim  (chat: "Arrange an airport pickup for 6:30 tomorrow, add it to my calendar, and send my partner the details." -> narrated booking recovery + receipt)
python3 -m sim.ablation --failure lost_ack --incident INC-1043  # commit-aware recovery: the ack is lost after commit
python3 -m sim.ablation --failure gray --incident INC-1043   # baseline vs protected, side-by-side from real runs
python3 test_sim.py          # 18/18: the sim's own proof
```
No API keys, no network — everything above runs fully offline and deterministic.

**Commit-aware recovery (the continuity demo):** the `/sim` page opens with the
booking task card and a run button — the recovery timeline, the three-way
comparison (naive retry vs idempotency-only vs full layer), and the **recovery
receipt** render from the run's own records (per-operation effect receipt,
retry decision, checkpoint, fencing decision, final verified state — every
field read off the journal + forensic ledger, never hard-coded; JSON at
`GET /sim/api/receipt/<incident_id>`). The measured results table is
`docs/results-table.md` (regenerate: `python3 scripts/gen_results_table.py`).
The engine underneath is
`continuity/journal.py`: a SQLite operation journal (WAL, explicit commits,
crash-safe) with reconcile-before-retry discipline — same idempotency key +
same full operation (service, op, target, params) reuses the committed
receipt; same key + a different operation, or a key shared across operations,
is a loud conflict, never a silent reuse. A `ContinuityGateway`
(`sim/lost_ack.py`) separates the agent from the provider and the journal:
it authorizes the caller's fencing generation *before* dispatching any
downstream effect, persists the receipt *before* the ack goes out, so on ack
loss the agent provably never holds the original — the retry reconstructs it
from SQLite.

Honesty boundary: the journal provides reconcile-before-retry *discipline*,
not a magic exactly-once guarantee. Exactly-once against an arbitrary external
service additionally needs the provider to honor idempotency keys (the
simulated provider does) or a reliable way to re-read provider state first.
The sim is explicit about which one it uses; all faults are labeled simulated
and all times are ticks, never seconds.

**Docker:**
```bash
cp .env.example .env   # add MODEL_API_KEY + CONTINUITY_LIVE=1 for the live model beat (optional)
docker compose up      # dashboard on :5000 + the terminal demo
```

## Adapter API (with a real example)

```python
from continuity.adapter import ContinuityLayer
from continuity.contracts import CONTRACTS
from continuity.checkpoint import STATE_ADAPTERS
from continuity.standby import StandbyController
from store import IncidentStore

layer = ContinuityLayer()                      # deterministic; add
                                               # diagnostician=default_diagnostician()
                                               # for model notes
store = IncidentStore(layer.fencing, layer.ledger)

layer.register("remediation",
               CONTRACTS["remediation"],       # role contract: must/must-not + checks
               state_adapter=STATE_ADAPTERS["remediation"],
               standby=StandbyController(make_standby("remediation")),
               primary=remediation_agent)      # your agent object, unmodified

# Your workflow loop, unchanged in shape:
ctx = {"incident": inc}
result = layer.invoke("remediation", ctx, remediation_agent)  # may fail over inside
layer.apply_effects(result, store)            # idempotent, epoch-fenced
ctx["remediation"] = result["output"]

# ...later, when the primary recovers:
if layer.attempt_rejoin("remediation"):       # probes first; standby stays
    ...                                       # authoritative until they pass
```

The agents never import the layer. `invoke` observes the output, `apply_effects`
carries an explicit idempotency key per action, and a recovered primary's
stale writes are rejected until `attempt_rejoin` issues it a new epoch.
See `examples/wrap_existing.py` for wrapping a LangChain-style agent
(own tools/state/`run()`) without touching its code.

Configuration: copy `continuity.example.yaml` to `continuity.yaml` to
override thresholds, canary behavior, epoch TTL, model settings, and
the JSONL log path. Secrets come from the environment only
(`MODEL_API_KEY`).

## The three failure modes

| Mode | What happens | How it's caught |
|---|---|---|
| **A — hard death** | remediation process killed | liveness → immediate quarantine → failover |
| **B — silent dependency** | LLM connection broken; agent alive, returns well-formed `remediation: null` | contract anomaly → suspicion canary → confirmed degradation → failover |
| **C — gray semantic** | plausible but wrong: proposes a forbidden DB restart, no evidence | business-invariant violation → targeted canary → quarantine → failover; flagged for human review |

`demo.py` runs each mode and prints the timestamped timeline plus the
**incident summary**: last-known-good → anomaly → canary fail → fenced epoch →
standby activated → affected-work map (completed clean / replayed by
standby / human review / duplicates prevented) → primary rejoin at a new
epoch → recovery complete.

## Metrics

Computed from the forensic ledger (`continuity/metrics.py`,
`ledger.export_json(path)`):

- **TSFD — Time to Semantic Failure Detection:** ticks from the first
  observed anomaly to the confirmed failover. How fast the layer catches a
  role that *looks* healthy.
- **TRV — Time to Verified Recovery:** ticks from failover to the end of
  the failure window (verified recovery + rejoin). How fast trustworthy
  operation is restored.
- **AFR — Affected Work Recovery Rate:** recovered incidents (completed
  clean / replayed or recovered via standby) over all affected incidents.

## Live model seam (optional, not used in this submission)

The model does two jobs a deterministic layer cannot do for itself — both via
an OpenAI-compatible chat-completions endpoint (configurable in
`continuity.yaml`, key via `MODEL_API_KEY`):

1. **Canary generation** (`continuity/canary.py`): with explicit live
   opt-in (`demo.py --live` or `CONTINUITY_LIVE=1`) **and** `MODEL_API_KEY`
   set, the model invents diverse, adversarial probe
   scenarios per role. The deterministic `CanaryOracle` still judges every
   probe — the model writes scenarios, the oracle judges. Otherwise → the
   frozen static probe.
2. **Forensic narrative** (`continuity/diagnostician.py`): after a failover,
   the model drafts the 2–3 sentence incident summary from the failure window
   + affected-work map. Labeled `model-narrative`, advisory only, never
   consulted for a verdict.

**Credit safety:** key presence alone never enables network calls — not in
tests, not in the demo, not in the dashboard. Live calls happen only with
explicit opt-in (`--live` / `CONTINUITY_LIVE=1`) plus the key. Run the suite
with a key exported and it still makes zero network calls (verified by test).

Production behavior: 20s timeout, 2 retries with exponential backoff,
circuit breaker (3 consecutive failures → 60s open → silent stub fallback).
The client **never** raises into the sentinel path and **never** changes a
verdict — the governing principle is that the verifier must be dumber than
the verified.

**Live model (not used in this submission):** run `demo.py --live` with `MODEL_API_KEY`
set — the timeline prints `[model] generated 3 canary probes for role=remediation`
and the evidence screen renders the model-written forensic narrative. Without
`--live`, everything runs fully deterministic on the stub (the demo prints
the `[static]` fallback lines instead); no test touches the network.

## MCP read-only interface

`continuity/mcp_server.py` serves the forensic ledger over MCP (the
`mcp` package, `pip install -r requirements.txt`), so any MCP-capable
coding agent can ask "why did this workflow fail?" — no code changes on
the agent side.

Read-only by design: every tool reads from a forensic report dict (the
schema from `ForensicLedger.export_dict()`). Nothing here writes to the
ledger, changes a verdict, or triggers a standby. The narrative tool uses
the deterministic stub diagnostician — no model, no network.

Tools: `list_incidents`, `get_incident`, `get_affected_work`,
`get_fencing_state`, `get_ledger_entries`, `get_incident_narrative`,
`get_metrics`.

```bash
# serve the gray-failure demo world live
python -m continuity.mcp_server --live

# or export a forensic report first, then serve the file
python -c "
from test_continuity import make_world, incident, process_incident
layer, store, primaries = make_world()
process_incident(layer, store, primaries, incident('INC-1042'))
primaries['remediation'].backend.mode = 'llm_down'
process_incident(layer, store, primaries, incident('INC-1043'))
layer.ledger.export_json('forensic.json')"
python -m continuity.mcp_server --report forensic.json
```

Wire it into a coding agent's MCP config with the command
`python -m continuity.mcp_server --live` (run from the repo root).

## Scenario showcase

The dashboard (`python dashboard/app.py`) has two views:

- `/` — the live replay: role health, affected-work map, scrolling
  timeline, animated while a demo world runs in the background.
- `/showcase` — the scenario gallery: every example in the repo as a
  named card (the three failure modes, the healthy run, the
  no-duplicate-actions case). Pick one and it runs on demand, showing
  the verdict, the affected-work map, and the forensic incident
  narrative side by side. Same dark, video-readable styling as the
  live view.

## Layout

```
agents/                 the existing workflow -- knows NOTHING about the layer
continuity/             the continuity layer (the product)
  adapter.py            ContinuityLayer: register / invoke / apply_effects / rejoin
  sentinel.py           deterministic health vector + hysteresis state machine
  contracts.py          role contracts: must/must-not + business invariants
  canary.py             suspicion-triggered canaries, behavioral oracles
  checkpoint.py         continuity packages with schema versioning (resume, not restart)
  fencing.py            epoch fencing -- stale writes rejected, no split brain
  standby.py            standby lifecycle (rejects unreadable package schemas)
  ledger.py             forensic ledger + JSON export
  metrics.py            TSFD / TRV / AFR
  diagnostician.py      OPTIONAL Nemotron reasoning (advisory only)
  nemotron.py           shared Token Factory client (canary gen + narratives)
  mcp_server.py         MCP read-only interface over the forensic ledger
  config.py             YAML + env config (defaults = brutal-proof behavior)
  log.py                structured JSONL logging with incident correlation ids
dashboard/app.py        live video-readable dashboard (Flask) + scenario showcase (/showcase)
examples/wrap_existing.py  wrap a LangChain-style agent without modifying it
store.py                the existing shared incident store (epoch-fenced writes)
test_continuity.py      10 tests -- the brutal proof (frozen)
test_robust.py           9 tests -- hardening (config, threads, export, dashboard, client)
test_nemotron.py         9 tests -- Nemotron rework (platform fix, canary gen, narrative)
test_mcp.py             11 tests -- MCP read-only interface
test_showcase.py         6 tests -- dashboard scenario showcase
docs/video-script.md    3-minute video choreography
docs/devpost-alexa-draft.md   Devpost description draft
```

## Submission docs

- [3-minute video choreography](docs/video-script.md)
- [Devpost description draft](docs/devpost-alexa-draft.md)
- [Measured results table](docs/results-table.md)
- [Test evidence (91/91)](docs/test-evidence.md)
- [Friction log](docs/friction-log-draft.md)

## License

MIT — see [LICENSE](LICENSE).
