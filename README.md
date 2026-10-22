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
  |  diagnostician.py  OPTIONAL Nemotron notes +     |
  |                    narratives (advisory only)    |
  +=================================================+
      v
  incident store (your existing infrastructure,
                  epoch-fenced + idempotent writes)
```

**Design rules (frozen):**
- Agents are never modified — the layer observes inputs/outputs/effects
  through the adapter boundary only (`agents/` never imports `continuity/`).
- The deterministic sentinel is always authoritative. Nemotron writes
  canary scenarios and forensic narratives; the deterministic oracle judges
  every probe and verdicts are identical with the model disabled.
- Canaries are suspicion-triggered, never continuous.
- No split brain: stale epochs are rejected until revalidation.
- Resume, not restart: completed actions are never redone.

## Quickstart

**Local:**
```bash
pip install -r requirements.txt
python3 test_continuity.py   # 10/10: the brutal proof
python3 test_robust.py       #  9/9: hardening (config, threads, export, dashboard, client)
python3 demo.py              # the story, zero narration
python3 demo.py --failure gray
python3 dashboard/app.py     # live dashboard -> http://127.0.0.1:5000/
python3 examples/wrap_existing.py   # wrap YOUR agent shape without touching it
```

**Docker:**
```bash
cp .env.example .env   # add NEBIUS_API_KEY + CONTINUITY_LIVE=1 for the live Nemotron beat (optional)
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
                                               # for Nemotron notes
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
override thresholds, canary behavior, epoch TTL, Nemotron settings, and
the JSONL log path. Secrets come from the environment only
(`NEBIUS_API_KEY`).

## The three failure modes

| Mode | What happens | How it's caught |
|---|---|---|
| **A — hard death** | remediation process killed | liveness → immediate quarantine → failover |
| **B — silent dependency** | LLM connection broken; agent alive, returns well-formed `remediation: null` | contract anomaly → suspicion canary → confirmed degradation → failover |
| **C — gray semantic** | plausible but wrong: proposes a forbidden DB restart, no evidence | business-invariant violation → targeted canary → quarantine → failover; flagged for human review |

`demo.py` runs each mode and prints the timestamped timeline plus the
**$20K screen**: last-known-good → anomaly → canary fail → fenced epoch →
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

## Nebius Token Factory + Nemotron

Nemotron does two jobs a deterministic layer cannot do for itself — both via
the Nebius Token Factory OpenAI-compatible chat-completions endpoint
(`https://api.tokenfactory.nebius.com/v1/chat/completions`, default model
`nvidia/Nemotron-3.5-Super-VL`, overridable in `continuity.yaml`):

1. **Canary generation** (`continuity/canary.py`): with explicit live
   opt-in (`demo.py --live` or `CONTINUITY_LIVE=1`) **and** `NEBIUS_API_KEY`
   set, `NemotronCanaryGenerator` invents diverse, adversarial probe
   scenarios per role. The deterministic `CanaryOracle` still judges every
   probe — the model writes scenarios, the oracle judges. Otherwise → the
   frozen static probe.
2. **Forensic narrative** (`continuity/diagnostician.py`): after a failover,
   Nemotron drafts the 2–3 sentence incident summary from the failure window
   + affected-work map. Labeled `nemotron-narrative`, advisory only, never
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

**What the video must show:** run `demo.py --live` with `NEBIUS_API_KEY` set — the
timeline prints `[nemotron] generated 3 canary probes for role=remediation`
and the $20K screen renders the Nemotron-written forensic narrative. Without
`--live`, everything runs fully deterministic on the stub (the demo prints
the `[static]` fallback lines instead); no test touches the network.

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
  config.py             YAML + env config (defaults = brutal-proof behavior)
  log.py                structured JSONL logging with incident correlation ids
dashboard/app.py        live video-readable dashboard (Flask)
examples/wrap_existing.py  wrap a LangChain-style agent without modifying it
store.py                the existing shared incident store (epoch-fenced writes)
test_continuity.py      10 tests -- the brutal proof (frozen)
test_robust.py           9 tests -- hardening (config, threads, export, dashboard, client)
demo.py                 the 3-minute-video surface
docs/video-script.md    3-minute video choreography
docs/devpost-draft.md   Devpost description draft
```

## Submission docs

- [3-minute video choreography](docs/video-script.md)
- [Devpost description draft](docs/devpost-draft.md)

## License

MIT — see [LICENSE](LICENSE).
