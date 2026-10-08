# Devpost description (DRAFT)

## Agent Continuity Layer — the undercover agent is always watching

**The problem.** Multi-agent workflows fail in a way no monitor catches: an
agent's process stays alive while its *role* stops functioning. The LLM stops
responding, the container keeps running, the pipeline keeps producing output —
and nobody knows which work was affected or when outputs became trustworthy
again. I hit this exact failure in production.

**What it is.** An independent continuity layer that sits *underneath* an
existing multi-agent workflow without modifying the agents. An undercover
Sentinel continuously evaluates a four-layer health vector per role —
liveness, role contract, capability (suspicion-triggered canary tasks with a
deterministic oracle), and business invariants — with hysteresis so one bad
response never causes flapping.

**What happens on failure.** Gray failure detected → agent fenced via epoch
tokens (a recovered primary cannot cause split-brain) → hot standby resumes
from the continuity package (mid-workflow state, not a restart) → forensic
ledger records the failure window, the affected-work map, and duplicates
prevented → primary revalidated through recovery probes and rejoined at a new
epoch. Metrics: time-to-semantic-failure-detection (TSFD), verified recovery
time, affected-work recovery rate.

**How it's built.** Python. Deterministic sentinel core — fully functional
with zero model calls. Nemotron (via Nebius Token Factory) powers the
optional diagnostician: role-specific probes and diagnostic hypotheses, never
load-bearing for a continuity decision. Set `NEBIUS_API_KEY` to see
Nemotron-generated notes in the forensic ledger.

**Try it.** `python3 demo.py --failure gray` — kill nothing, watch the layer
catch a failure that looks healthy.

## Built with
Nebius Token Factory (Nemotron inference for the diagnostician), NVIDIA
Nemotron open models.
