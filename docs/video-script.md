# Demo video script — Alexa+ track (DEFINITIVE, ~2:40)

Prepared 2026-10-22 evening. Replaces the old terminal-first gray-failure
choreography. This is the script to record: it centers the lost-acknowledgement
scenario, records the actual /sim experience, and ends on the recovery receipt.
Narration is hers to adapt — keep her voice.

Rules: under 3:00, public YouTube/Vimeo, English, no background music, no
third-party trademarks. Honesty rules stand: label every fault simulated, name
the enforced invariants on screen, times in ticks never seconds, never claim
generalized AI-failure detection.

The signature moment (say it verbatim at the hook):
> "The booking succeeded. The agent didn't know it."

## 0:00–0:20 — Hook (20s)

- On screen: the /sim page hero — "The booking succeeded. The agent didn't know it."
- Narration: "The booking succeeded. The agent didn't know it. When an AI
  assistant loses the acknowledgement for an action it already performed, the
  safe-looking retry is the dangerous one — it books twice. This is the
  recovery problem nobody demos, because recovery is where the duplicate happens."

## 0:20–0:45 — The setup (25s)

- On screen: the /sim task card — the request, what runs, the fault, the
  question ("Does the retry book twice?"), and the run button.
- Narration: "The task starts the way a user would start it — in
  conversation. Three modeled steps: the ride booking, calendar update, and
  partner notification. The fault is fixed and labeled: the simulated provider
  commits, the acknowledgement is lost."

## 0:45–1:30 — The fault: three approaches, one fault (45s)

- On screen: click **"▶ Run the booking scenario."**
- Show the comparison table: **naive retry** — the ack is lost, the agent
  retries blindly — **two bookings**. Freeze on it. Let the duplicate sit
  on screen.
- Then the honest middle column: **idempotency-only** — the provider replays
  the prior result, **one booking**. Say it plainly: where the provider
  honors its key, idempotency already prevents the duplicate.
- Then the **full layer** — one booking, plus the rows idempotency can't
  reach: provider state lost (the layer halts and asks for human review
  instead of duplicating), stale write after failover (rejected), unsafe
  action (blocked).
- Narration (short — let the table do the work): "Same fault, three
  approaches. Without anything: booked twice. With idempotency alone: fine —
  until the provider loses its state. The layer's job is everything the key
  can't cover: uncertain outcomes, dependent steps, stale agents."

## 1:30–1:55 — The other two challenges (25s)

- Quick pass, no deep dive: **B — unsafe action**: the compromised agent
  proposes restarting the database; the layer blocks it. **C — stale write**:
  the fenced agent retries with a revoked generation; rejected at the
  store/effect boundary.
- Narration: "Same idea in two more shapes: an unsafe action that never
  executes, and a stale agent stopped at the effect boundary."

## 1:55–2:25 — Proof, not a success message (30s)

- On screen: the recovery receipt **for the successful run**. Walk it once:
  one booking listed, the retry decision ("reused"), what was verified, the
  remaining steps completed. (The human-review fallback lives in the
  comparison table's provider-state-loss row, shown earlier — this receipt is
  the success case, proven with evidence.)
- Narration: "Not a success message — evidence. What was booked, what the
  retry decided, what was actually verified."
- Beat (10s, to the camera or voiceover): "An idempotency key stops a repeated
  request. It doesn't recover a multi-step workflow after a restart, resolve
  an unknown outcome, or fence a stale agent. That's the layer underneath."

## 2:25–2:40 — Close (15s)

- Narration: "The Agent Continuity Layer — recover the workflow without
  replaying the work, and never trust a result you can't verify."
- End card: repo link, her name.

## Filming checklist

- [ ] Under 3:00 (this script targets ~2:40), public YouTube/Vimeo, English
- [ ] Every fault labeled simulated on screen; invariants named; ticks not seconds
- [ ] Simulation source is in the repo and visibly shown working
- [ ] Product feedback written for every tool/API/SDK used (see the Devpost draft)
- [ ] Friction log attached (docs/friction-log-draft.md)
- [ ] Submit by Fri Oct 23, 12:00pm PT / 2:00pm CT; share the private repo with
      testing@devpost.com + knmeiss, giolaq, anishamalde, mosesroth, emersonsklar
      at submit time

## Superseded

- docs/video-script-alexa-draft.md and docs/video-script-alexa-trimmed.md were
  earlier drafts of this script (gray-failure-centered). This file is the one
  to record.
