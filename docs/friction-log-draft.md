# Friction log — Amazon Developer Hackathon, Alexa+ track

Genuine issues hit while building this submission, with expected vs actual and
the workaround. All entries below are real events from the Oct 22–23 build.

## 1. The MCP integration I expected to build already existed

- **Expected:** The Alexa+ track rewards an MCP integration, so I planned to build one.
- **Actual:** The continuity layer already shipped 7 read-only MCP tools over the real
  forensic report schema on Oct 20 (45/45 tests green) — an external review had
  assumed they were missing without checking the repo.
- **Workaround:** Skipped new MCP work entirely. The sim's "what happened?" answers
  call the existing ledger tools instead of rebuilding them.

## 2. An external review analyzed a week-stale remote

- **Expected:** Review feedback grounded in the current code.
- **Actual:** The analysis was run against the public remote, which was ~7 days behind
  local: it hadn't seen the MCP ledger tools or the checkpoint-restoration + shared
  fencing fixes. Its build plan duplicated work that was already done.
- **Workaround:** Re-based the plan on the actual local tree before writing any code;
  the sim reuses the real engine, ledger, and fencing rather than re-implementing them.

## 3. Merging the MCP/showcase branch into main produced 6 conflicts

- **Expected:** Clean merge of `feature/mcp-and-showcase` into `main`.
- **Actual:** 6 conflicts, all between the newer credit-safety hardening and older code
  paths (live opt-in threading; the Nemotron zero-HTTP tripwire vs a socket-level
  duplicate guard).
- **Workaround:** Resolved by letting the newer credit-safety code win everywhere;
  the tripwire supersedes the socket-level duplicate. Re-ran the full suite:
  50/50 green post-merge, demo runs offline end-to-end.

## 4. Chose the simulated Alexa+ route over a real self-hosted MCP server

- **Expected:** A compliant self-hosted MCP server (spec 2025-11-25+, Streamable HTTP)
  for the Alexa+ track.
- **Actual:** With ~24 hours to the deadline, a spec-compliant server plus the demo
  plus the video was not feasible alongside a second hackathon finish the same week.
- **Workaround:** The official rules explicitly permit a simulated Alexa+ experience in
  a web app with the simulation's source in the repo — so I built the conversational
  sim on the real engine (additive only, no MCP surface), source committed on
  `alexa-plus-sim`.

## 5. Bundle downloads through chat became the bottleneck

- **Expected:** Keep shipping git bundles through chat for her to clone and push.
- **Actual:** After the third bundle she said downloading and applying them was too
  painful to repeat — the manual handoff was eating build time the night before
  the deadline.
- **Workaround:** Connected the GitHub App (OAuth under her identity) with access
  scoped to just this repo, and pushed branches through the connector instead.
  No tokens exchanged, no terminal work for her; she approves each push.

## 6. The test suite was green while a showcase route 500'd

- **Expected:** The suite guards every user-facing route.
- **Actual:** `/showcase/duplicates` returned 500 (KeyError: 'epoch' from stale
  pre-rework store/checkpoint APIs) while its 6/6 tests passed — no test ever
  exercised that scenario end to end.
- **Workaround:** Fixed the stale API calls and added the missing regression test
  that drives the route itself. Lesson applied to the new work: the challenge-mode
  tests hit the HTTP endpoints, not just the functions behind them.

---

## Feature updates during the Submission Period (required for pre-existing projects)

Per the rules, pre-existing projects must "clearly describe and demo the feature
updates during the Submission Period." Everything below was built Oct 22–23, 2026,
on `alexa-plus-sim` (merged to `main` via PR #1) and the follow-up
hardening branch:

1. **Conversational Alexa+-style sim control surface** — start tasks in natural
   language, inject a gray failure mid-run, ask "what happened?", resume with context.
2. **Baseline-vs-protected ablation runner** — runs the same scenario through a naive
   baseline and through the continuity layer; real outputs from both runs, no
   hard-coded comparison numbers.
3. **Per-scenario reliability scorecard** — TSFD / TRV / AFR, duplicates prevented,
   affected-work buckets (completed / recovered / needs-human-review), and the rerun
   command, computed by the real metrics functions from the ledger.
4. **Ledger-backed "what happened?" answers** — the sim answers recovery questions
   through the existing 7 MCP read-only tools, not a new Q&A layer.
5. **Commit-aware recovery (flagship)** — SQLite operation journal with
   reconcile-before-retry: the action commits, the ack is lost, the gateway
   persists the receipt, the agent retries through the journal and reuses the
   receipt. Baseline double-books; the protected run books exactly once.
6. **Recovery receipt** — per-operation + global receipt built from real records
   (journal + ledger + store), rendered as a card on `/sim` with JSON export.
7. **Break-it challenge mode** — three buttons (lost ack, unsafe action, stale
   write) with baseline-vs-layer comparison and receipt for each.
8. **Review hardening** — agent/gateway information boundary (the agent never
   holds the receipt; the retry reconstructs it from SQLite after a journal
   reload), full-operation fingerprinting (service/op/target/params), and
   cross-operation key-reuse rejection.
