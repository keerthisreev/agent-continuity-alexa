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

- On screen: /sim chat. The task, in plain language: book an airport ride,
  update the calendar, notify the partner. A normal multi-step assistant task.
- Narration: "The task starts the way a user would start it — in conversation.
  Three steps, one real side effect: the ride booking."

## 0:45–1:30 — The fault: baseline books twice, the layer books once (45s)

- On screen: click **"▶ Break it: lose the acknowledgement."**
- Show the BASELINE first: the ack is lost, the agent retries blindly —
  **two bookings**. Freeze on it. Let the duplicate sit on screen.
- Then the protected run: the ack is lost, the gateway reconciles the
  operation journal, reuses the committed receipt, completes the calendar
  and notification steps. **One booking.**
- Narration (short — let the before/after do the work): "Same fault. Without
  the layer: booked twice. With it: the journal remembers what actually
  happened, so the retry reuses the receipt instead of repeating the action."

## 1:30–1:55 — The other two challenges (25s)

- Quick pass, no deep dive: **B — unsafe action**: the compromised agent
  proposes restarting the database; the layer blocks it. **C — stale write**:
  the fenced agent retries with a revoked generation; rejected before the
  provider is touched.
- Narration: "Same idea in two more shapes: an unsafe action that never
  executes, and a stale agent stopped before it can cause a side effect."

## 1:55–2:25 — Proof, not a success message (30s)

- On screen: the recovery receipt. Walk it once: one booking listed, the
  retry decision ("reused"), what was verified, the remaining steps completed.
  If the provider's state can't be confirmed, the receipt says
  "needs human review" — it never manufactures a success.
- Narration: "Not a success message — evidence. What was booked, what the
  retry decided, what was actually verified. And when the outcome can't be
  confirmed, it says so instead of pretending."

## 2:25–2:40 — Close (15s)

- Narration: "The Agent Continuity Layer — the AI that doesn't do it twice.
  Trust the work, not the process."
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
