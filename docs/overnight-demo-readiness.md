# Overnight demo-readiness report — Agent Continuity Layer (/sim)

**Branch:** `overnight/demo-readiness` (from `main` at PR #11 merge)
**Commit:** (see push receipt; local HEAD at time of writing)
**Date:** 2026-10-23, overnight run while you slept
**Baseline:** 91/91 tests green, zero skipped. **After:** 94/94 green, zero skipped (+3 new regression tests).

## What changed and why

**P1 — /sim UI rebuilt as a professional light theme** (`dashboard/app.py`, `SIM_PAGE` only)
- The old UI was a dark monospace developer console. The new UI is a restrained light theme:
  system sans-serif prose, monospace only for code/evidence, white cards on a soft-gray page,
  one blue accent, green/amber/red status colors with accessible contrast.
- The 5-second rule is kept: kicker → "The booking succeeded. The agent didn't know it." →
  two-sentence explanation → task card → prominent blue **Run the booking scenario** button.
- Simulated-services disclosure is now explicit and unmissable (was a small gray footnote).
- All element IDs, JS function names, and CSS classes used by the Python renderers are unchanged —
  the backend was not touched for the theme.

**P1 — verdict badges** (`_render_sim_message`, challenge kind)
- Each challenge now opens with a plain-language verdict badge:
  - lost_ack: green "1 booking · retry reused the receipt · no duplicates" + amber
    "provider-state-loss variant: halted · human review required"
  - unsafe: green "unsafe action blocked — no effect executed"
  - stale_write: green "stale write rejected at the store boundary"
- The provider-state-loss row can no longer be mistaken for success: it is labeled
  HALTED + human review in the badge, the table cell, and the receipt.

**P1 — honest halt styling** (`_render_receipt`)
- When a receipt's `final_state.human_review_flags` is non-empty, the receipt renders with
  an amber "halt" treatment and the badge "halted — human review required; dependent steps
  did not run". Clean receipts render exactly as before. The styling is driven by real
  receipt data, never hardcoded.

**P2 — demo experience** (JS in `SIM_PAGE`)
- **Reset demo** button next to the CTA: clears results, chat, and session client-side, then
  re-greets. Safe — no server state touched.
- Loading state with a subtle spinner; the Run button disables while a challenge executes
  (prevents double-clicks stacking results).
- Failed challenge requests show an error message instead of hanging silently.
- Comparison tables auto-wrap in a horizontal-scroll container on narrow screens.
- Responsive CSS: grids collapse to one column under 720px; receipt key/value rows stack.

**P2 — small correctness fix**
- `continuity.example.yaml`: stale comment referenced the renamed `NEBIUS_API_KEY`; now `MODEL_API_KEY`.

**P3 — regression tests** (`test_sim.py`, +3)
- `test_challenge_verdict_badges_render`: all three challenges return the expected verdict badges.
- `test_receipt_halt_styling_on_human_review`: halt styling tracks `human_review_flags` (present → halted look; absent → clean).
- `test_sim_page_has_reset_and_light_theme`: CTA id, reset flow, light-theme tokens, simulated disclosure all present.

**P3 — audit results (no defects found, no changes needed)**
- Idempotency: `_canonical_operation` fingerprints service + op + target + params; key reuse across
  different operations raises `IdempotencyKeyMismatch` loudly. No conflation.
- XSS: all dynamic text in `_render_sim_message`/`_render_receipt` goes through `_sim_escape`;
  automated scan found zero unescaped interpolations. The JS `esc()` covers chat input.
- Booking narration: `_book_ride` branches on `halted` and never narrates a completed booking
  when the provider state is unverifiable (PR #7 behavior preserved).
- Secrets sweep: no API keys, passwords, or `.env` files in the repo; `.env` is gitignored.
- Docs: `docs/test-evidence.md` header already says `main (final freeze)` with `MODEL_API_KEY`;
  README counts (13/9/12/11/7/18/21) and 91/91 references are current.

## Before / after test counts

| Suite | Before | After |
|---|---|---|
| test_continuity | 13/13 | 13/13 |
| test_robust | 9/9 | 9/9 |
| test_nemotron | 12/12 | 12/12 |
| test_mcp | 11/11 | 11/11 |
| test_showcase | 7/7 | 7/7 |
| test_sim | 18/18 | **21/21** (+3 new) |
| test_journal | 21/21 | 21/21 |
| **Total** | **91/91** | **94/94, zero skipped** |

## Exact launch commands

```bash
cd ~/workspace/alexa-continuity        # or wherever you cloned it
git checkout overnight/demo-readiness
git pull
python3 -m venv .venv && source .venv/bin/activate   # if needed
pip install flask "mcp>=2.0" pyyaml requests
python3 dashboard/app.py
# open http://127.0.0.1:5000/sim
```

Works with `MODEL_API_KEY` unset (fully offline, deterministic).

## Click-by-click demo flow

1. Open `http://127.0.0.1:5000/sim`. Read the hero: "The booking succeeded. The agent didn't know it."
2. Click **▶ Run the booking scenario**. Watch the loading spinner, then the results appear:
   verdict badges → recovery timeline → three-way comparison table → scorecard → recovery receipt.
3. Scroll the table to the "Provider loses its state" row: the amber badge up top already told you —
   halted, human review.
4. Click **B · propose an unsafe action** and **C · stale write after failover** chips under
   "Explore other failure modes". Each shows risk → action attempted → observed outcome + receipt.
5. Optional: type the booking sentence in the chat box ("Arrange an airport pickup…") to see the
   narrated booking flow.
6. Click **Reset demo** any time to clear and start over — repeated runs are deterministic.

## Implemented vs simulated (unchanged, still honest)

- **Real:** journal, continuity gateway, fencing authority, operation reconciliation, retry decisions,
  forensic ledger, scorecard metrics, receipts — all execute in-process against the real code.
- **Simulated:** the booking provider, calendar service, notification service, the chat front-end
  (keyword matching), and every injected fault. Labeled "simulated" on screen and in the docs.
- Times are in logical ticks, never seconds. No live Alexa+ backend, no AWS, no network calls.

## Remaining bugs, limitations, unverified claims

- **Mobile layout NOT VERIFIED in a real browser** — responsive CSS is written to standard
  breakpoints and tables scroll horizontally, but I could not drive a real browser here
  (enterprise Chromium blocks local network + headless screenshots broken). Check on your phone
  before recording if you plan a mobile shot.
- **Video script** (`docs/video-script.md`) is still accurate: same button label, same flow.
  The new Reset button and verdict badges don't contradict it.
- The `▶` glyph on the CTA renders via system fonts; if it looks off on your machine, the button
  still reads "Run the booking scenario".
- Pre-existing (not introduced overnight): the gray-failure INC-1043 chat flow is the older,
  more technical demo path — it still works, but the booking scenario is the recording path.

## How to return to main

```bash
git checkout main
```

That's it — nothing on `main` was touched. The branch `overnight/demo-readiness` contains only
the changes above. To abandon: `git branch -D overnight/demo-readiness` (local only; the remote
branch can be deleted from the GitHub UI).
