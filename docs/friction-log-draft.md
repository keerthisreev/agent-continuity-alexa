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
- **Steps attempted:** Read the track docs; sketched an MCP build plan; searched the
  repo for existing ledger/MCP surfaces before writing code; found the 7 tools
  with 45/45 tests already green.
- **Severity:** Low — a lucky discovery that saved half a day.
- **Suggestion:** Hackathon briefs could include a "check what already exists"
  prompt in the getting-started guide; it would have short-circuited the plan
  even earlier.

## 2. An external review analyzed a week-stale remote

- **Expected:** Review feedback grounded in the current code.
- **Actual:** The analysis was run against the public remote, which was ~7 days behind
  local: it hadn't seen the MCP ledger tools or the checkpoint-restoration + shared
  fencing fixes. Its build plan duplicated work that was already done.
- **Workaround:** Re-based the plan on the actual local tree before writing any code;
  the sim reuses the real engine, ledger, and fencing rather than re-implementing them.
- **Steps attempted:** Received the external review; started implementing its build
  plan; noticed the proposed work duplicated existing modules; diffed the public
  remote against the local tree and confirmed a ~7-day gap.
- **Severity:** Medium — about an hour of planning spent before the mismatch surfaced.
- **Suggestion:** Anyone reviewing a repo (human or AI) should check `git log`
  recency on the remote first; stale-remote analysis is a quiet, common failure.

## 3. Merging the MCP/showcase branch into main produced 6 conflicts

- **Expected:** Clean merge of `feature/mcp-and-showcase` into `main`.
- **Actual:** 6 conflicts, all between the newer credit-safety hardening and older code
  paths (live opt-in threading; the Nemotron zero-HTTP tripwire vs a socket-level
  duplicate guard).
- **Workaround:** Resolved by letting the newer credit-safety code win everywhere;
  the tripwire supersedes the socket-level duplicate. Re-ran the full suite:
  50/50 green post-merge, demo runs offline end-to-end.
- **Steps attempted:** Ran the merge; inspected all 6 conflicts; confirmed each was
  newer-hardening vs older-code (not two competing features); resolved; re-ran suite.
- **Severity:** Medium — resolved in under an hour, no data loss.
- **Suggestion:** Smaller, more frequent merges between parallel hardening tracks;
  the conflicts came from two tracks touching the same live opt-in paths.

## 4. Chose the simulated Alexa+ route over a real self-hosted MCP server

- **Expected:** A compliant self-hosted MCP server (spec 2025-11-25+, Streamable HTTP)
  for the Alexa+ track.
- **Actual:** With ~24 hours to the deadline, a spec-compliant server plus the demo
  plus the video was not feasible alongside a second hackathon finish the same week.
- **Workaround:** The official rules explicitly permit a simulated Alexa+ experience in
  a web app with the simulation's source in the repo — so I built the conversational
  sim on the real engine (additive only, no MCP surface), source committed on
  `alexa-plus-sim`.
- **Steps attempted:** Read the MCP spec (2025-11-25+, Streamable HTTP); estimated
  server + demo + video effort against the ~24h remaining; read the official
  rules and FAQ on permitted submission routes; chose the simulated path.
- **Severity:** Low — a scope decision, not a blocker; the permitted route fit.
- **Suggestion:** Keep the "simulated experience" route explicitly documented in
  future hackathons — that FAQ entry was the single deciding factor, and its
  clarity saved a bad last-minute scramble.

## 5. Bundle downloads through chat became the bottleneck

- **Expected:** Keep shipping git bundles through chat for her to clone and push.
- **Actual:** After the third bundle she said downloading and applying them was too
  painful to repeat — the manual handoff was eating build time the night before
  the deadline.
- **Workaround:** Connected the GitHub App (OAuth under her identity) with access
  scoped to just this repo, and pushed branches through the connector instead.
  No tokens exchanged, no terminal work for her; she approves each push.
- **Steps attempted:** Shipped three bundles through chat; watched the download /
  apply cycle eat build time; asked what hurt; connected the GitHub App scoped
  to the single repo; verified blob SHAs matched before each push.
- **Severity:** High — on deadline eve, the manual handoff was the bottleneck.
- **Suggestion:** For agent platforms: a first-class "push a branch to the user's
  repo" flow (with per-push approval) beats file downloads for code handoff.

## 6. The test suite was green while a showcase route 500'd

- **Expected:** The suite guards every user-facing route.
- **Actual:** `/showcase/duplicates` returned 500 (KeyError: 'epoch' from stale
  pre-rework store/checkpoint APIs) while its 6/6 tests passed — no test ever
  exercised that scenario end to end.
- **Workaround:** Fixed the stale API calls and added the missing regression test
  that drives the route itself. Lesson applied to the new work: the challenge-mode
  tests hit the HTTP endpoints, not just the functions behind them.
- **Steps attempted:** Ran the suite (green); manually opened the route (500);
  traced the KeyError to stale pre-rework store/checkpoint APIs; fixed; added
  the route-level regression test; re-ran green.
- **Severity:** High — a judge clicking through the demo could have hit it.
- **Suggestion:** For the project itself: every user-facing route gets an
  end-to-end test that drives the HTTP layer, not just the functions behind it.
  (Applied: the new challenge-mode tests hit the endpoints.)

## 7. The advertised booking sentence didn't work in the chat

- **Expected:** Typing "Arrange an airport pickup for 6:30 tomorrow…" starts the booking recovery flow.
- **Actual:** The chat's keyword parser only knew incident terms (payments, checkout,
  database) — the advertised sentence fell through to generic help text. The page
  promised a booking flow the chat couldn't start.
- **Workaround:** Added a `book_ride` intent (airport/pickup/taxi) with a narrated
  handler that runs the real protected scenario end to end; the help text and page
  chips now lead with the booking story. Pinned by a test on the exact advertised
  sentence.
- **Steps attempted:** An external review typed the advertised sentence and got help
  text; reproduced locally; traced it to the TASK_KEYWORDS table; added the intent
  + handler + test; verified live against a local server (6 messages, receipt
  rendered, download link returns 200).
- **Severity:** High — a judge doing the obvious thing would have doubted the product.
- **Suggestion:** For the project: every sentence quoted in the UI or docs gets a
  test that types it verbatim. (Applied: the new booking test uses the exact
  advertised utterance.)

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
