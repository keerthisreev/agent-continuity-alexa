"""Lost-acknowledgement scenario: the action committed, the ack didn't arrive.

The signature demo for commit-aware recovery. A simulated user asks for a
multi-step task (reserve ride -> update calendar -> notify partner). The
first side effect COMMITS, then the acknowledgement is lost -- the agent
cannot tell whether the action happened.

  protected: the agent consults the operation journal before retrying.
             reconcile-before-retry reuses the committed receipt: exactly
             one booking, remaining steps complete.
  baseline:  no journal, no idempotency keys. The agent retries blindly:
             the provider books twice.

SIMULATED: the provider, the ack loss, and the user task. REAL: the
SQLite journal (continuity/journal.py), the store's fencing + idempotent
apply (store.py), triage/diagnosis/escalation through the real
ContinuityLayer, and the forensic ledger timeline.

Honesty note: the protected run avoids the duplicate BECAUSE the
simulated provider honors idempotency keys (and because the agent checks
the journal before retrying). Against a real provider that ignores
idempotency keys, reconcile-before-retry is still the right discipline,
but exactly-once needs provider cooperation -- see journal.py.
"""
from __future__ import annotations

import os
import sys
import tempfile
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_continuity import make_world
from continuity.diagnostician import StubDiagnostician
from continuity.journal import OperationJournal

# The multi-step user task. Deterministic fixtures, not a live integration.
USER_TASK_STEPS: List[Dict[str, Any]] = [
    {"name": "reserve_ride",
     "kind": "reserve", "target": "airport-pickup",
     "label": "Reserve airport pickup",
     "params": {"pickup": "home", "dropoff": "AUS",
                "time": "06:30", "date": "tomorrow"}},
    {"name": "update_calendar",
     "kind": "update", "target": "shared-calendar",
     "label": "Add pickup to shared calendar",
     "params": {"title": "Airport pickup", "start": "tomorrow 06:30"}},
    {"name": "notify_partner",
     "kind": "notify", "target": "partner",
     "label": "Send partner the details",
     "params": {"channel": "sms",
                "body": "Airport pickup booked for 06:30 tomorrow"}},
]

FAULT_LABEL = ("Simulated fault (deterministic, preconfigured): the ride "
               "provider commits the booking, but the acknowledgement never "
               "reaches the agent.")


class SimulatedProvider:
    """Deterministic simulated downstream services with idempotency-key
    support: the same key never creates a second effect. A None key means
    the caller passed no idempotency key -- every call creates an effect,
    which is exactly the naive baseline's mistake."""

    def __init__(self):
        self.effects: Dict[str, dict] = {}  # idempotency_key -> receipt
        self.calls = 0
        self.created_receipts: List[dict] = []

    def execute(self, kind: str, idempotency_key: Optional[str],
                params: Dict[str, Any]):
        """Returns (receipt, created: bool)."""
        self.calls += 1
        if idempotency_key is not None and idempotency_key in self.effects:
            return dict(self.effects[idempotency_key]), False
        n = len(self.created_receipts) + 1
        receipt = {"effect_id": f"{kind.upper()}-{n:04d}", "kind": kind,
                   "params": dict(params), "status": "confirmed"}
        self.created_receipts.append(receipt)
        if idempotency_key is not None:
            self.effects[idempotency_key] = receipt
        return dict(receipt), True


def _fresh_journal(path: Optional[str] = None) -> OperationJournal:
    if path is None:
        fd, path = tempfile.mkstemp(prefix="journal-", suffix=".db")
        os.close(fd)
    return OperationJournal(path)


def run_protected_lost_ack(incident_id: str = "INC-1043",
                           journal_path: Optional[str] = None) -> Dict[str, Any]:
    """The user task under journal discipline. Always offline:
    StubDiagnostician, live=False."""
    layer, store, primaries = make_world(diagnostician=StubDiagnostician(),
                                         live=False)
    assert layer.live is False
    journal = _fresh_journal(journal_path)
    provider = SimulatedProvider()
    inc = {"id": incident_id, "service": "sim-user-task",
           "symptom": "multi-step user request", "severity": "P3"}
    ctx = {"incident": inc}

    # Real triage + diagnosis through the layer: the incident is worked
    # before the user-facing operations run.
    for role in ("triage", "diagnosis"):
        result = layer.invoke(role, ctx, primaries[role])
        layer.apply_effects(result, store)
        ctx[role] = result["output"]

    # The user-facing operations, authorized at the remediation role's
    # current fencing generation (the workflow role executing the request).
    generation = layer.fencing.current("remediation")
    steps: List[Dict[str, Any]] = []
    for i, step in enumerate(USER_TASK_STEPS):
        op_id = f"{incident_id}:user_task:{i}:{step['name']}"
        key = op_id  # stable logical operation id doubles as idempotency key
        tick = layer.clock.tick()
        rec = journal.record_intent(op_id, key, step["params"],
                                    fencing_generation=generation)
        layer.ledger.record(
            "journal_intent",
            {"op": op_id, "idempotency_key": key,
             "status": rec["status"]}, tick)
        receipt, created = provider.execute(step["kind"], key, step["params"])
        action = {"kind": step["kind"], "target": step["target"],
                  "params": step["params"]}
        store.apply_effect("sim-user-task", "remediation", generation,
                           key, action, tick=tick)
        journal.record_commit(op_id, receipt)
        layer.ledger.record(
            "journal_commit", {"op": op_id, "receipt": receipt}, tick)
        layer.ledger.record_stage(incident_id, "user_task",
                                  "sim-choreography", tick, "ok")
        entry: Dict[str, Any] = {
            "step": step, "op_id": op_id, "key": key, "receipt": receipt,
            "created": created, "reused": False,
            "recovery_decision": None,
            "provider_calls_after": provider.calls,
        }
        if i == 0:
            # THE FAULT: acknowledgement lost after commit.
            journal.mark_unknown(op_id)
            layer.ledger.record(
                "journal_ack_lost",
                {"op": op_id,
                 "honest_note": "simulated: ack lost after commit"}, tick)
            # The agent retries the SAME logical op -- but consults the
            # journal first instead of re-executing blindly.
            journal.record_intent(op_id, key, step["params"],
                                  fencing_generation=generation)
            final = journal.reconcile(op_id)
            assert final["receipt"] == receipt, \
                "reconcile must return the committed receipt"
            layer.ledger.record(
                "journal_reconciled",
                {"op": op_id,
                 "decision": final["recovery_decision"]}, tick)
            entry["reused"] = True
            entry["recovery_decision"] = final["recovery_decision"]
            # No second provider call, no second store write: the receipt
            # is reused. (The store would also refuse a duplicate key --
            # belt and suspenders, pinned in test_journal.py.)
        steps.append(entry)

    # Real escalation closes the workflow.
    result = layer.invoke("escalation", ctx, primaries["escalation"])
    layer.apply_effects(result, store)
    ctx["escalation"] = result["output"]

    ride_bookings = sum(1 for r in provider.created_receipts
                        if r["kind"] == "reserve")
    return {
        "mode": "user task + operation journal + continuity layer",
        "incident_id": incident_id,
        "failure": "lost_ack",
        "fault_label": FAULT_LABEL,
        "layer": layer,
        "store": store,
        "journal": journal,
        "journal_path": journal.path,
        "provider": provider,
        "steps": steps,
        "provider_calls": provider.calls,
        "ride_bookings": ride_bookings,
        "fencing_generation": generation,
        "disposition": layer.ledger.affected_work().get(incident_id),
        "duplicates_prevented": layer.ledger.duplicates_prevented,
    }


def run_baseline_lost_ack(incident_id: str = "INC-1043") -> Dict[str, Any]:
    """Naive retry: no journal, no idempotency keys. The lost ack causes
    a blind retry and the provider books the ride twice."""
    provider = SimulatedProvider()
    steps: List[Dict[str, Any]] = []
    for i, step in enumerate(USER_TASK_STEPS):
        receipt, created = provider.execute(step["kind"], None, step["params"])
        steps.append({"step": step, "receipt": receipt, "created": created,
                      "retry": False})
        if i == 0:
            # Ack "lost": the naive agent retries with no record to consult.
            receipt2, created2 = provider.execute(step["kind"], None,
                                                 step["params"])
            steps.append({"step": step, "receipt": receipt2,
                          "created": created2, "retry": True})
    ride_bookings = sum(1 for r in provider.created_receipts
                        if r["kind"] == "reserve")
    return {
        "mode": "naive retry (no journal, no idempotency keys)",
        "incident_id": incident_id,
        "failure": "lost_ack",
        "steps": steps,
        "provider_calls": provider.calls,
        "ride_bookings": ride_bookings,
        "duplicate_effects": ride_bookings - 1,  # one pickup requested
    }


def compare_lost_ack(baseline: Dict[str, Any],
                     protected: Dict[str, Any]) -> Dict[str, Any]:
    """Every cell from the two runs' own records."""
    from .scorecard import build_scorecard

    reused = [s for s in protected["steps"] if s.get("reused")]
    rows = [
        {
            "aspect": "Acknowledgement lost after commit",
            "baseline": ("The agent cannot tell whether the action happened "
                         "-- it retries blindly, with no record to consult."),
            "protected": ("Journal marks the op 'unknown'; "
                          "reconcile-before-retry reuses the committed "
                          "receipt instead of re-executing."),
        },
        {
            "aspect": "Ride bookings created (one pickup requested)",
            "baseline": (f"{baseline['ride_bookings']} -- the user would be "
                         f"charged twice"),
            "protected": (f"{protected['ride_bookings']} -- the existing "
                          f"receipt was reused; no duplicate effect"),
        },
        {
            "aspect": "Downstream provider calls",
            "baseline": str(baseline["provider_calls"]),
            "protected": (f"{protected['provider_calls']} -- the retry never "
                          f"re-hit the provider"),
        },
        {
            "aspect": "Remaining steps (calendar, notify)",
            "baseline": "completed",
            "protected": "completed",
        },
        {
            "aspect": "Proof of what happened",
            "baseline": "none -- no journal, no ledger entries for the retry",
            "protected": ("journal records + forensic ledger timeline + "
                          "recovery receipt below"),
        },
    ]
    return {
        "incident_id": baseline["incident_id"],
        "failure": "lost_ack",
        "rows": rows,
        "reused_receipts": len(reused),
        "scorecard": build_scorecard(
            protected["layer"],
            rerun_cmd=(f"python3 -m sim.ablation --failure lost_ack "
                       f"--incident {baseline['incident_id']}")),
    }
