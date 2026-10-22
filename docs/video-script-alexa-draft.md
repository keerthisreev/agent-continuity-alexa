# Video script skeleton — Amazon Alexa+ track (DRAFT, UI-agnostic)

Target: **≤ 2:50** (hard cap 3:00). Film the actual sim UI; narration lines are
hers to adapt — keep her voice, not this draft's. Rules reminders: no background
music, no third-party trademarks, public YouTube/Vimeo, English.

Positioning (adopted): **"The agent is green. Its decisions aren't."** Lead with
trustworthiness-of-work, not persistence or the chat UI. The conversational
interface is the access layer; the reliability layer is the entry.

Honesty hardening (adopted — applies to the video, the sim UI, and the Devpost
text): the gray failure is a *deterministic preconfigured violation*. Label every
fault as simulated, name the enforced invariants on screen, and never claim
generalized AI-failure detection. TSFD/TRV are reported in ticks, not seconds.

## 0:00–0:20 — Hook (Quality of the Idea)

- On screen: healthy dashboard, all agents green, heartbeat alive.
- Narration: "Every monitor says this agent is healthy. Its process is alive, its
  heartbeat is steady. But the work it just produced can't be trusted — and no
  dashboard caught it."

## 0:20–0:50 — Start the task conversationally (Design)

- On screen: sim chat. User types: "Investigate incident INC-1043 and prepare a
  remediation plan. Don't execute an unsafe action."
- Show the multi-agent workflow starting, progress visible.
- Narration: "The task starts the way a user would start it — in conversation."

## 0:50–1:20 — The gray failure (Tech Implementation)

- Inject the gray failure into the remediation agent. It stays alive and returns a
  plausible, structurally valid response that violates a business invariant
  (e.g. recommends a prohibited database restart).
- On screen: outside view — process ALIVE, dashboard sees nothing wrong.
  (Demo.py's killer frame: the "[outside view]" lines right before the sentinel fires.)
- Narration: "Watch the outside view. The process is alive. The dashboard sees
  nothing wrong. The agent just recommended something it was told never to do."

## 1:20–2:00 — Detection, fencing, failover (Tech Implementation)

- Show, in order: the failing canary → quarantine → epoch change → standby
  activation → a stale write from the original agent getting rejected.
- Ablation insert (real outputs, no hard-coded numbers): the naive baseline
  executes the unsafe action; the layer blocks it. Side-by-side if the UI allows,
  otherwise sequential.
- Narration: "The sentinel caught what monitoring never could. The faulty agent is
  fenced with an epoch token so it can't split-brain — even its late writes get
  rejected. The standby resumes from the last valid checkpoint. Same scenario,
  without the layer: the unsafe action goes through."

## 2:00–2:40 — Proof, not a success message (Potential Impact)

- On screen: the recovery report — three buckets: completed / recovered /
  needs-human-review. Below it the scorecard: TSFD, TRV, AFR, duplicates
  prevented, the rerun command.
- Ask "what happened?" in the sim; show the ledger-backed answer.
- Narration: "Not a success message — evidence. What completed, what the standby
  recovered, what needs a human, and the numbers behind it. That's the difference
  between an agent that's alive and an agent that's safe to trust."

## 2:40–2:50 — Close

- Narration: "The Agent Continuity Layer — a reliability layer beneath AI agents
  that detects silent failure, isolates the untrustworthy agent, and recovers the
  work. Trust the work, not the process."
- End card: repo link, her name.

## Filming checklist (from the official rules)

- [ ] Under 3 minutes, public YouTube or Vimeo, English
- [ ] Simulation source is in the repo and visibly shown working
- [ ] Devpost text rewritten for the Alexa+ track (the repo's old devpost draft
      still carries the Nebius "Best Apps and Agents" framing — do not reuse it);
      text describes the feature updates built during the submission period
      (see docs/friction-log-draft.md § "Feature updates")
- [ ] Product feedback written for every tool/API/SDK used (required submission field)
- [ ] Friction log attached (up to 10% judging bonus — genuine entries only)
- [ ] Submit by **Fri Oct 23, 12:00pm PT / 2:00pm CT**; share the private repo with
      the five Amazon collaborators (knmeiss, giolaq, anishamalde, mosesroth,
      emersonsklar) AND testing@devpost.com at submit time — invitations expire
      in 7 days
