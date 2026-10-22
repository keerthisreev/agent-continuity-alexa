"""Baseline-vs-protected ablation: workflow alone vs workflow + layer.

Runs the SAME gray/silent-failure scenario twice with the SAME scripted
agents and the SAME step order:

  baseline  -- no sentinel, no fencing, no standby, no checkpoints. The
               workflow accepts each agent's output at face value.
  protected -- the identical steps driven through the real ContinuityLayer.

Framed honestly: this is an ablation, not a strawman competitor. The
baseline is this workflow minus the reliability layer. Every number in
the comparison comes from the two runs' own records -- nothing is
hard-coded.

The injected fault is deterministic and preconfigured (a scripted
backend mode), never generalized AI-failure detection: "gray" returns a
plausible-but-wrong plan violating the invariant "never restart the
database for this incident class"; "silent" simulates a dead model
dependency returning a well-formed but empty plan.

Run:  python3 -m sim.ablation [--failure gray|silent] [--incident INC-1043]
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.triage import TriageAgent
from agents.diagnosis import DiagnosisAgent
from agents.remediation import RemediationAgent
from agents.escalation import EscalationAgent
from store import IncidentStore
from test_continuity import make_world
from continuity.diagnostician import StubDiagnostician

from .scorecard import build_scorecard, render_text

ROLES = ("triage", "diagnosis", "remediation", "escalation")
FAILURE_MODES = {"gray": "gray", "silent": "llm_down"}


def make_incident(incident_id: str) -> dict:
    return {"id": incident_id, "service": "payments-api",
            "symptom": "p99 latency > 2s", "severity": "P1"}


def _action_label(action: dict) -> str:
    return f"{action.get('kind')}:{action.get('target')}"


# ---------------------------------------------------------------------------
# Baseline: the workflow alone. No layer, no checks, no second chances.
# ---------------------------------------------------------------------------

def run_baseline(failure: str = "gray", incident_id: str = "INC-1043") -> Dict[str, Any]:
    """Run the workflow with no continuity layer. Outputs are accepted at
    face value; the invariant-violating action is executed, not blocked."""
    agents = {
        "triage": TriageAgent(),
        "diagnosis": DiagnosisAgent(),
        "remediation": RemediationAgent(),
        "escalation": EscalationAgent(),
    }
    inc = make_incident(incident_id)
    ctx = {"incident": inc}
    effects_allowed: List[str] = []
    steps: List[Dict[str, Any]] = []

    # Same step order as the protected run: triage, diagnosis, a clean
    # remediation pass, a verification pass where the failure is armed,
    # then escalation.
    order = ["triage", "diagnosis", "remediation", "remediation", "escalation"]
    for step_i, role in enumerate(order):
        if role == "remediation" and step_i == 3:
            agents["remediation"].backend.mode = FAILURE_MODES[failure]
        out = agents[role].handle(ctx)
        applied = [_action_label(a) for a in out.get("actions", [])]
        effects_allowed.extend(applied)
        steps.append({"step": step_i, "role": role, "actions": applied,
                      "note": "accepted at face value"})
        ctx[role] = out

    unsafe = [e for e in effects_allowed if e == "restart:database"]
    return {
        "mode": "workflow alone (no continuity layer)",
        "incident_id": incident_id,
        "failure": failure,
        "detected": None,  # nothing watches; nothing is detected
        "effects_allowed": effects_allowed,
        "unsafe_action_executed": bool(unsafe),
        "unsafe_actions": unsafe,
        "steps": steps,
    }


# ---------------------------------------------------------------------------
# Protected: the identical steps through the real ContinuityLayer.
# ---------------------------------------------------------------------------

def run_protected(failure: str = "gray",
                  incident_id: str = "INC-1043") -> Dict[str, Any]:
    """Run the identical steps through the real layer. Always offline:
    StubDiagnostician, live=False (a stray key can never flip the suite)."""
    layer, store, primaries = make_world(diagnostician=StubDiagnostician(),
                                         live=False)
    assert layer.live is False
    inc = make_incident(incident_id)
    ctx = {"incident": inc}
    blocked: List[str] = []
    failover_tick: Optional[int] = None

    def _invoke(role: str) -> dict:
        result = layer.invoke(role, ctx, primaries[role])
        layer.apply_effects(result, store)
        ctx[role] = result["output"]
        return result

    for role in ("triage", "diagnosis", "remediation"):
        _invoke(role)
    # Verification pass: arm the failure, snapshot what the agent proposes
    # (pure read -- the primary has no restore package), then let the layer
    # observe the same output through its own invocation path.
    primaries["remediation"].backend.mode = FAILURE_MODES[failure]
    proposed = primaries["remediation"].handle(dict(ctx))
    blocked = [_action_label(a) for a in proposed.get("actions", [])]
    result = _invoke("remediation")
    if result["active"] == "standby":
        failover_tick = result["tick"]
    _invoke("escalation")

    # Effects the layer actually allowed: completed action ids recorded in
    # the incident-scoped checkpoints (id format incident:role:i:kind:target).
    effects_allowed = []
    for (agent_id, inc_id), pkg in layer._checkpoints.items():
        if inc_id != incident_id:
            continue
        for aid in pkg.completed_action_ids:
            parts = aid.split(":")
            if len(parts) >= 5:
                effects_allowed.append(f"{parts[3]}:{parts[4]}")

    # What the sentinel saw: first anomaly/critical entry for this incident.
    detected = None
    for e in layer.ledger.timeline:
        if e["kind"] in ("critical_violation", "anomaly"):
            d = e["detail"] or {}
            detected = {"tick": e["tick"], "kind": e["kind"],
                        "violations": list(d.get("violations") or [])}
            break

    resume = next(
        ({"standby": e["detail"].get("standby"),
          "generation": e["detail"].get("generation"),
          "resumed_from_tick": e["detail"].get("resumed_from_tick"),
          "resumed_from_incident": e["detail"].get("resumed_from_incident")}
         for e in layer.ledger.timeline if e["kind"] == "standby_activated"),
        None)

    return {
        "mode": "workflow + continuity layer",
        "incident_id": incident_id,
        "failure": failure,
        "layer": layer,
        "detected": detected,
        "blocked_actions": blocked,
        "effects_allowed": effects_allowed,
        "failover_tick": failover_tick,
        "resume": resume,
        "duplicates_prevented": layer.ledger.duplicates_prevented,
        "disposition": layer.ledger.affected_work().get(incident_id),
        "fencing_generations": {
            role: layer.fencing.current(role) for role in ROLES},
    }


# ---------------------------------------------------------------------------
# Comparison: every cell from the two runs' own records.
# ---------------------------------------------------------------------------

def compare(baseline: Dict[str, Any], protected: Dict[str, Any]) -> Dict[str, Any]:
    det = protected["detected"] or {}
    rows = [
        {
            "aspect": "Semantic failure detected",
            "baseline": "No — no independent checks; output accepted at face value.",
            "protected": (
                f"Yes — {det.get('kind')} at tick {det.get('tick')}: "
                f"{(det.get('violations') or [''])[0]}"
                if det else "No failure armed in this run."),
        },
        {
            "aspect": "Invariant-violating action",
            "baseline": (
                f"EXECUTED: {', '.join(baseline['unsafe_actions'])}"
                if baseline["unsafe_action_executed"]
                else "none proposed in this run"),
            "protected": (
                f"BLOCKED before any effect: {', '.join(protected['blocked_actions'])} "
                f"(role fenced at generation "
                f"{protected['fencing_generations'].get('remediation')})"
                if protected["blocked_actions"] else "none proposed in this run"),
        },
        {
            "aspect": "Effects the run allowed",
            "baseline": ", ".join(baseline["effects_allowed"]) or "-",
            "protected": ", ".join(protected["effects_allowed"]) or "-",
        },
        {
            "aspect": "Duplicate writes on replay",
            "baseline": "no fencing — a replay would double-apply",
            "protected": (
                f"{protected['duplicates_prevented']} prevented "
                f"(checkpoint resume, idempotent apply)"),
        },
        {
            "aspect": "Task outcome",
            "baseline": (
                "completed — with the unsafe action executed"
                if baseline["unsafe_action_executed"]
                else "completed — but no remediation was ever applied"),
            "protected": (
                f"{protected['disposition']}"
                + (f"; standby resumed from tick "
                   f"{(protected['resume'] or {}).get('resumed_from_tick')}"
                   if protected.get("resume") else "")),
        },
    ]
    return {
        "incident_id": baseline["incident_id"],
        "failure": baseline["failure"],
        "rows": rows,
        "scorecard": build_scorecard(
            protected["layer"],
            rerun_cmd=(f"python3 -m sim.ablation --failure {baseline['failure']} "
                       f"--incident {baseline['incident_id']}")),
    }


def render_text_comparison(comp: Dict[str, Any]) -> List[str]:
    lines = [
        "ABLATION: workflow alone vs workflow + continuity layer",
        f"incident {comp['incident_id']} | failure: {comp['failure']} "
        f"(same agents, same steps, same scripted outputs)",
        "",
    ]
    for r in comp["rows"]:
        lines.append(f"  {r['aspect']}")
        lines.append(f"    alone : {r['baseline']}")
        lines.append(f"    layer : {r['protected']}")
    lines.append("")
    lines.extend(render_text(comp["scorecard"]))
    return lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Ablation: same gray-failure scenario, with and without "
                    "the continuity layer.")
    ap.add_argument("--failure", choices=("gray", "silent"), default="gray")
    ap.add_argument("--incident", default="INC-1043")
    args = ap.parse_args(argv)

    baseline = run_baseline(args.failure, args.incident)
    protected = run_protected(args.failure, args.incident)
    for line in render_text_comparison(compare(baseline, protected)):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
