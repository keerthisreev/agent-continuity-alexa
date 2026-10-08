# Agent Continuity Layer — brutal proof

> **The undercover agent is always watching.**

An independent continuity layer that sits **underneath** an existing
multi-agent incident workflow (triage → diagnosis → remediation →
escalation) **without modifying the agents**. When an agent's *role*
stops functioning — even while its process stays alive — the layer
detects it, fences it, resumes the work from a continuity package via a
hot standby, and keeps a forensic ledger. "The undercover agent is always
watching."

This is the ugly prototype: deterministic, keyless, no network, no UI.
It answers one question: *"Did it catch all three failures without
touching the agents?"*

## The three failures it catches

| Mode | What happens | How it's caught |
|---|---|---|
| **A — hard death** | remediation process killed | liveness → immediate quarantine → failover |
| **B — silent dependency** | LLM connection broken, agent alive, returns well-formed `remediation: null` | contract anomaly → suspicion canary → confirmed degradation → failover |
| **C — gray semantic** | plausible but wrong: proposes a forbidden DB restart, no evidence | business-invariant violation → targeted canary → quarantine → failover |

## Layout

```
agents/                 the existing workflow -- knows NOTHING about the layer
  base.py               IncidentAgent, ScriptedBackend (deterministic model stub)
  triage|diagnosis|remediation|escalation.py
  standbys.py           healthy standby per role
continuity/             the continuity layer (the product)
  adapter.py            ContinuityLayer: register() + invoke() + apply_effects()
  sentinel.py           deterministic health vector + hysteresis state machine
  contracts.py          role contracts: must/must-not + business invariants
  canary.py             suspicion-triggered canaries, behavioral oracles
  checkpoint.py         continuity packages (resume, not restart)
  fencing.py            epoch fencing -- stale writes rejected, no split brain
  standby.py            standby lifecycle
  ledger.py             forensic ledger: windows, affected-work map, timeline
  diagnostician.py      OPTIONAL reasoning: Nemotron via Nebius when
                        NEBIUS_API_KEY is set, stub otherwise. Never authoritative.
store.py                the existing shared incident store (epoch-fenced writes)
test_continuity.py      10 tests, plain asserts -- the brutal proof
demo.py                 the 3-minute-video surface: timestamped timeline +
                        the $20K screen. --failure hard|silent|gray|all
```

## Run it

```bash
python3 test_continuity.py     # 10/10: the proof
python3 demo.py                # the story, zero narration
python3 demo.py --failure gray # one failure mode
```

## Design rules (frozen)

- **Agents are never modified.** The layer observes inputs/outputs/effects
  through the adapter boundary only.
- **Deterministic sentinel, always.** The Nemotron diagnostician only
  annotates the ledger; verdicts are identical with it disabled.
- **Canaries are suspicion-triggered, never continuous.** Economics matter.
- **No split brain.** Epoch fencing: a recovered primary's stale writes are
  rejected until revalidation issues a new epoch.
- **Resume, not restart.** Standbys continue from continuity packages;
  completed actions are never redone (ledger counts prevented duplicates).

## The $20K screen

`demo.py` ends each scenario with: last-known-good → role anomaly →
canary fail → fenced epoch → standby activated → continuity restored →
affected-work map (entered window / completed / replay / human-review /
duplicates prevented) → primary rejoin at new epoch → recovery complete.

## Nebius / NVIDIA seam

`continuity/diagnostician.py`: `NemotronDiagnostician` calls a Nemotron
model through the Nebius Token Factory OpenAI-compatible chat-completions
endpoint when `NEBIUS_API_KEY` is set (`NEBIUS_BASE_URL` /
`NEBIUS_MODEL` overridable; default `nvidia/Nemotron-3-Nano-30B`).
Without the key it falls back to the stub — no network call is ever made
without the key, and no test touches the network. At demo time, set the
key and the ledger's diagnostician notes are visibly Nemotron-generated.
