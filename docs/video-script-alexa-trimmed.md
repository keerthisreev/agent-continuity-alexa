# Video script — Amazon Alexa+ track (TRIMMED, ~2:35, 25s slack)

Prepared 2026-10-22 evening. Trims ~25s off the 180s skeleton so she lands
under 3:00 with room to breathe. Narration is hers to adapt — keep her voice.
Rules: no background music, no third-party trademarks, public YouTube/Vimeo,
English. Positioning: "The agent is green. Its decisions aren't." Honesty rules
stand: label every fault simulated, name the enforced invariants on screen,
TSFD/TRV in ticks, never claim generalized AI-failure detection.

## 0:00–0:15 — Hook (15s)
- On screen: healthy dashboard, all agents green, heartbeat alive.
- Narration: "Every monitor says this agent is healthy. But the work it just
  produced can't be trusted — and no dashboard caught it."
- (Cut: the process-alive/heartbeat-stable sentence — the screen shows it.)

## 0:15–0:40 — Start the task conversationally (25s)
- On screen: sim chat. "Investigate incident INC-1043 and prepare a remediation
  plan. Don't execute an unsafe action." Show the multi-agent workflow starting.
- Narration: "The task starts the way a user would start it — in conversation."

## 0:40–1:05 — The gray failure (25s)
- Inject the gray failure into the remediation agent: stays alive, returns a
  plausible, structurally valid response that violates a business invariant
  (recommends a prohibited database restart). Outside view: process ALIVE,
  dashboard sees nothing wrong.
- Narration: "Watch the outside view. The process is alive. The agent just
  recommended something it was told never to do."
- (Cut: the "[outside view] lines" setup line — show it, don't explain it.)

## 1:05–1:50 — Detection, fencing, failover + ablation (45s)
- Show in order: failing canary → quarantine → epoch change → standby activation
  → a stale write from the original agent rejected.
- Ablation insert (real outputs, sequential if side-by-side doesn't fit): the
  naive baseline executes the unsafe restart; the layer blocks it.
- Narration: "The sentinel caught what monitoring never could. The faulty agent
  is fenced with an epoch token — even its late writes get rejected. The standby
  resumes from the last valid checkpoint. Same scenario, without the layer: the
  unsafe action goes through."

## 1:50–2:25 — Proof, not a success message (35s)
- On screen: recovery report — completed / recovered / needs-human-review.
  Below: scorecard (TSFD, TRV, AFR, duplicates prevented, rerun command).
  Ask "what happened?" in the sim; show the ledger-backed answer.
- Narration: "Not a success message — evidence. What completed, what the standby
  recovered, what needs a human, and the numbers behind it. That's the difference
  between an agent that's alive and an agent that's safe to trust."

## 2:25–2:35 — Close (10s)
- Narration: "The Agent Continuity Layer — reliability beneath AI agents.
  Trust the work, not the process."
- End card: repo link, her name.
- (Cut: the longer "detects silent failure, isolates the untrustworthy agent,
  and recovers the work" line — the demo already said it.)

## Filming checklist
- [ ] Under 3:00 (this script targets ~2:35), public YouTube/Vimeo, English
- [ ] Simulation source is in the repo and visibly shown working
- [ ] Product feedback written for every tool/API/SDK used (see the Devpost draft)
- [ ] Friction log attached — fill the two bracketed TODOs first, genuine only
- [ ] Submit by Fri Oct 23, 12:00pm PT / 2:00pm CT; share the private repo with
      testing@devpost.com + knmeiss, giolaq, anishamalde, mosesroth, emersonsklar
      at submit time
