# Devpost submission text — Amazon Developer Hackathon, Alexa+ track (DRAFT for her review)

Prepared 2026-10-22 evening for the Fri Oct 23, 12pm PT / 2pm CT submission.
Paste-ready once she reviews. Sections marked [FILL] need her input.

---

## Project name
Agent Continuity Layer

## Tagline
Reliability infrastructure for AI agent workflows — the agent is green; its decisions aren't.

## Track
Alexa+ — simulated Alexa+ experience in a web app (per the official rules, the
simulated path needs no MCP surface; the simulation source is in this repo).

## Description (paste into Devpost)

**The agent is green. Its decisions aren't.**

Multi-agent workflows fail in a way no monitor catches: an agent's process stays
alive while its *role* silently stops functioning — the LLM goes off-track, the
container keeps running, the pipeline keeps producing output nobody can trust.
The Agent Continuity Layer is the reliability layer underneath the workflow that
catches exactly that failure: independent health contracts per role (liveness,
role contract, suspicion-triggered canary probes, business invariants), gray-
failure detection, epoch fencing so a recovered primary can't split-brain, and a
hot standby that resumes unfinished work from the continuity package — resume,
not restart.

**This submission: a conversational, Alexa+-style simulated experience.** Start
an incident-response task in natural language, inject a gray failure mid-run,
watch the sentinel catch what the dashboard never could, ask "what happened?"
and get a ledger-backed recovery report: what completed, what the standby
recovered, what needs a human — plus a per-scenario reliability scorecard (TSFD,
TRV, AFR in logical ticks, duplicates prevented, the rerun command) and a
baseline-vs-protected ablation showing the same scenario with and without the
layer. The unsafe action executes in the baseline; the layer blocks it. Real
outputs from both runs — nothing hard-coded.

**Honesty note (also enforced in the UI):** the gray failure in the demo is a
deterministic, preconfigured contract violation. Every fault is labeled
simulated, the enforced invariants are named on screen, and detection/recovery
times are reported in logical ticks, not seconds. This demo proves the
mechanism — detection, fencing, resume, evidence — not generalized
AI-failure detection.

**Pre-existing work disclosure.** The continuity layer predates this hackathon
(private repo, built for the Nebius × NVIDIA hackathon). Everything demoed as
new was built during the submission window, Oct 22–23, 2026, on the
`alexa-plus-sim` branch: (1) the conversational sim control surface — start
tasks in natural language, inject faults, ask "what happened?", resume with
context; (2) the baseline-vs-protected ablation runner; (3) the per-scenario
reliability scorecard computed by the real metrics functions from the ledger;
(4) ledger-backed "what happened?" answers through the existing 7 read-only MCP
tools. 67/67 tests green. The demo path is fully deterministic and offline —
no API key needed to reproduce it.

**Try it.** Clone the repo, `python3 demo.py --failure gray` for the engine, or
run the dashboard and open `/sim` for the conversational experience.

## Built with
Python, Flask, the Agent Continuity Layer engine (deterministic offline demo
path), read-only MCP ledger tools.

## Product feedback (required field — draft; [FILL] = hers to complete)

**The Alexa+ simulated-experience path.** What for: entered a reliability layer
as a conversational simulated experience instead of an MCP server. What worked:
the rule text explicitly permits a simulated Alexa+ experience in a web app with
the simulation source in the repo — that clarity let me scope a honest 24-hour
build. What needs work: "clearly shows it working" is implicit; an example
acceptance checklist (fault labels, before/after evidence, rerun command) would
help builders self-check. Onboarding: fine. Would build this way again: yes —
for infrastructure whose value is behavioral evidence, not API surface.

**The private-repo collaborator flow.** What for: shared the private repo with
testing@devpost.com plus the five Amazon reviewers at submit time. What worked:
[FILL after she does it]. What needs work: invitations expire in 7 days, so they
must be sent at submit time, not earlier — worth surfacing on the rules page
itself as a gotcha.

**The continuity-layer engine (my own tool, used as the system under test).**
What for: gray-failure detection, epoch fencing, standby resume. What worked: the
deterministic diagnostic seam (stub diagnostician, live inference off) made the
demo fully reproducible with no key; the 7 read-only MCP ledger tools answered
"what happened?" with no new Q&A code. What needs work: [FILL if she hit
anything]. Would build on it again: yes.

**Video tooling.** [FILL — whatever she records/edits with.]

## Friction log
Attach `docs/friction-log-draft.md` from the repo (fill the two bracketed TODOs
from the sim build first — genuine entries only, thin-but-honest).

---

## Submission checklist (for her — from the official rules)
- [ ] Merge `alexa-plus-sim` → `main` (judges land on the default branch)
- [ ] Repo: private is fine IF shared with testing@devpost.com AND the five
      Amazon GitHub users — knmeiss, giolaq, anishamalde, mosesroth, emersonsklar
      — at submit time (invites expire in 7 days; do not send earlier)
- [ ] Demo video: under 3 minutes, public YouTube or Vimeo, English, no
      background music, no third-party trademarks
- [ ] Paste this Devpost text (track + mini-challenge selected on the form)
- [ ] Friction log attached
- [ ] Submit by Fri Oct 23, 12:00pm PT / 2:00pm CT
