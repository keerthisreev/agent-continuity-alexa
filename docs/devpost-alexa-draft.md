# Devpost submission text — Amazon Developer Hackathon, Alexa+ track (DRAFT for her review)

Prepared 2026-10-22 evening for the Fri Oct 23, 12pm PT / 2pm CT submission.
Paste-ready once she reviews. NOTE: the Product feedback section below is
drafted from the real build events — review it and make sure every word is
genuinely hers before submitting.

---

## Project name
Agent Continuity Layer

## Tagline
Continuity control for AI workflows — recover ambiguous failures without replaying work or trusting unverified results.

## Track
Alexa+ — simulated Alexa+ experience in a web app (per the official rules, the
simulated path needs no MCP surface; the simulation source is in this repo).

## Description (paste into Devpost)

**The agent is green. Its decisions aren't — and when an action's outcome turns
ambiguous, the recovery shouldn't be a guess.**

The failure no monitor catches: an AI assistant performs an action, loses the
acknowledgement, and tries again. The user gets charged twice, booked twice, the
same task executed twice. The Agent Continuity Layer is the continuity control
layer that recovers the workflow without replaying completed work — and never
trusts a result it can't verify: a **continuity gateway** sits between the agent and
the downstream provider, persists every effect receipt to a **SQLite operation
journal before the acknowledgement goes out**, and serves retries from the
journal instead of re-executing. Same idempotency key, same full operation
(service, op, target, params) → the committed receipt is reused. Same key, a
different operation → rejected loudly, never silently conflated.

**Why not just idempotency keys?** A per-operation key stops a repeated request
from creating a second effect — established practice, and this layer relies on
it. But a key alone doesn't establish the outcome of a *multi-step workflow*
after a restart, doesn't resolve an *unknown* provider state, and doesn't stop
a *stale agent* from acting after failover. That's the gap this closes: the
durable journal plus reconcile-before-retry, fencing generations enforced at
the gateway *and* the provider, and a recovery receipt that proves what happened
— or says "needs human review" when the outcome can't be verified.

**This submission: a conversational, Alexa+-style simulated experience.**
"Arrange an airport pickup for 6:30 tomorrow, add it to my calendar, and send
my partner the details." The ride provider commits the booking — then the ack
is lost. The baseline agent retries blindly and books twice. The protected run
reconciles the journal, reuses the receipt, and finishes the remaining steps:
**one booking, calendar updated, partner notified, with a recovery receipt
proving it.** Run the booking scenario on `/sim` — the recovery timeline, the
three-way comparison (naive retry vs idempotency-only vs the full layer), and
the receipt all render from the run's own records — then explore the other
failure modes (unsafe action, stale write after failover), plus a per-scenario
reliability scorecard (TSFD/TRV/AFR in logical ticks, duplicates prevented,
the rerun command).

**Evidence:** the full results table — naive retry vs idempotency-only vs the
full layer across lost acknowledgement, provider state loss, stale writes,
unsafe actions, and the healthy run — is measured from real runs in
`docs/results-table.md` (regenerate: `python3 scripts/gen_results_table.py`;
machine-readable receipts at `GET /sim/api/receipt/<incident_id>`).

**Underneath:** the continuity engine that earned this submission its
foundation — independent health contracts per role, gray-failure detection
(alive but wrong), epoch fencing so a recovered primary can't split-brain, hot
standby resuming unfinished work from the continuity package, and a forensic
ledger — also exposed through 7 read-only MCP tools; the sim chat answers
"what happened?" through the shared ledger-view logic.

**Honesty note (also enforced in the UI):** every fault in the demo is a
deterministic, preconfigured, labeled-simulated fault; the enforced invariants
are named on screen; times are reported in logical ticks, not seconds. The
journal's exactly-once discipline is real, and its documented limit is real
too: against a provider that ignores idempotency keys, the guarantee needs
provider cooperation or reliable state reconciliation. This demo proves the
mechanism — commit, persist, reconcile, prove — not generalized AI-failure
detection.

**Pre-existing work disclosure.** The continuity engine predates this hackathon
(private repo, built for a prior AI-infrastructure project). Everything demoed as
new was built during the submission window, Oct 22–23, 2026: (1) the
conversational sim control surface, now with the advertised booking request
wired to the working recovery flow (type the airport-pickup sentence — the
chat narrates commit → lost ack → journal check → one booking + receipt); (2) the baseline-vs-protected ablation
runner; (3) the per-scenario reliability scorecard from the real metrics
functions; (4) forensic ledger with 7 read-only MCP tools, plus
ledger-backed "what happened?" answers in the sim chat via the shared view
logic;
(5) the SQLite operation journal + continuity gateway + lost-ack scenario;
(6) the recovery receipt (card + JSON export); (7) break-it challenge mode;
(8) review hardening — the agent/gateway information boundary, full-operation
fingerprinting, cross-operation key-reuse rejection, and pre-dispatch fencing
authorization at the gateway; the provider itself validates the fencing token
on every call (defense in depth against the check-then-act race); plus the
honest restart proof — if the provider's state can't be re-verified after a
restart, the receipt says "needs human review" instead of manufacturing a
success. **91/91 tests green, zero skipped** (full output in
`docs/test-evidence.md`). The demo path is fully deterministic
and offline — no API key needed to reproduce it.

**Try it.** `python3 -m sim.ablation --failure lost_ack` for the flagship
comparison, or run the dashboard and open `/sim` for the chat + break-it panel.

## Built with
Python, SQLite (WAL), Flask, the Agent Continuity Layer engine (deterministic
offline demo path), read-only MCP ledger tools.

## Product feedback (required field — drafted from real events; she reviews)

**The Alexa+ simulated-experience path.** What for: entered a reliability layer
as a conversational simulated experience instead of an MCP server. What worked:
the rule text explicitly permits a simulated Alexa+ experience in a web app with
the simulation source in the repo — that clarity made a 24-hour honest build
possible. What needs work: "clearly shows it working" is implicit; an example
acceptance checklist (fault labels, before/after evidence, rerun command) would
help builders self-check. Onboarding: fine. Would build this way again: yes —
for infrastructure whose value is behavioral evidence, not API surface.

**The official Alexa+ simulator.** What for: looked for the Alexa+ developer
toolkit / web simulator to build against. What worked: nothing — it is not
available to ordinary hackathon participants, which the organizers have
confirmed. What needs work: the track page should say that up front instead of
letting builders discover it mid-sprint. Workaround: built the simulation as a
web app per the permitted path. Concrete suggestion: publish the simulator or
mark the track "simulation path" explicitly.

**The private-repo collaborator flow.** What for: plan to share the private repo with
testing@devpost.com plus the five Amazon reviewers at submit time (not yet done —
invitations expire in 7 days, so they must go out at submission, not earlier).
What worked so far: the GitHub App installation flow scoped access to just this repo
during the build. What needs work: surfacing the 7-day expiry as a gotcha on the
rules page itself, since "invite at submit time" is easy to get wrong.

**Video.** Screen recording with voiceover, trimmed to under 3 minutes.

## Friction log
Attach `docs/friction-log-draft.md` from the repo.

---

## Submission checklist (for her — from the official rules)
- [x] Merge to `main` (PR #1 squash-merged; `alexa-plus-sim` branch deleted)
- [x] Merge the review-hardening PR (PR #3 squash-merged)
- [x] Merge the gateway-fencing PR (PR #4 squash-merged)
- [x] Merge the honest-restart + /sim first-screen PR (PR #5 squash-merged)
- [x] Merge the booking-flow + provider-fencing PR (PR #6 squash-merged)
- [ ] Repo: private is fine IF shared with testing@devpost.com AND the five
      Amazon GitHub users — knmeiss, giolaq, anishamalde, mosesroth, emersonsklar
      — at submit time (invites expire in 7 days; do not send earlier)
- [ ] Demo video: under 3 minutes, public YouTube or Vimeo, English, no
      background music, no third-party trademarks
- [ ] Paste this Devpost text (track + mini-challenge selected on the form)
- [ ] Friction log attached
- [ ] Submit by Fri Oct 23, 12:00pm PT / 2:00pm CT
