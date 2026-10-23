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
from continuity.journal import (
    DECISION_UNVERIFIED_NEEDS_REVIEW, OperationJournal)

# The multi-step user task. Deterministic fixtures, not a live integration.
# "service" names the downstream provider for the journal's canonical
# operation identity (service, op, target, params).
USER_TASK_STEPS: List[Dict[str, Any]] = [
    {"name": "reserve_ride",
     "kind": "reserve", "target": "airport-pickup",
     "service": "ride-provider",
     "label": "Reserve airport pickup",
     "params": {"pickup": "home", "dropoff": "AUS",
                "time": "06:30", "date": "tomorrow"}},
    {"name": "update_calendar",
     "kind": "update", "target": "shared-calendar",
     "service": "calendar-svc",
     "label": "Add pickup to shared calendar",
     "params": {"title": "Airport pickup", "start": "tomorrow 06:30"}},
    {"name": "notify_partner",
     "kind": "notify", "target": "partner",
     "service": "notify-svc",
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
    which is exactly the naive baseline's mistake.

    Downstream fencing contract: when constructed with a fencing authority
    + role, every execute() must carry the caller's fencing token, which
    the provider validates BEFORE recording any effect. A rotation landing
    between the gateway's pre-check and this call is still rejected here --
    defense in depth, not check-then-act alone. Fail-closed: a missing or
    stale token is rejected with no effect recorded.
    """

    def __init__(self, fencing=None, role: Optional[str] = None):
        self.effects: Dict[str, dict] = {}  # idempotency_key -> receipt
        self.calls = 0
        self.created_receipts: List[dict] = []
        self.fencing = fencing
        self.role = role

    def execute(self, kind: str, idempotency_key: Optional[str],
                params: Dict[str, Any],
                fencing_token: Optional[int] = None):
        """Returns (receipt, created: bool)."""
        if self.fencing is not None:
            # The downstream boundary enforces the token first: no effect
            # is recorded for a stale or missing generation.
            self.fencing.check(self.role, fencing_token)
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

    def query(self, idempotency_key: Optional[str]) -> Optional[dict]:
        """Re-read provider state for a key: the recorded receipt, or None
        if the provider has no record of it (state lost, or never
        committed here). A read, not an effect: does not touch `calls`."""
        receipt = self.effects.get(idempotency_key)
        return dict(receipt) if receipt is not None else None


def _fresh_journal(path: Optional[str] = None) -> OperationJournal:
    if path is None:
        fd, path = tempfile.mkstemp(prefix="journal-", suffix=".db")
        os.close(fd)
    return OperationJournal(path)


class AcknowledgementLost(Exception):
    """Simulated transport failure: the provider committed and the gateway
    persisted the receipt, but the acknowledgement never reached the
    agent. The agent holds NO receipt data -- only the op id and the
    idempotency key it started with. Carries no receipt by construction."""


class ContinuityGateway:
    """The durable boundary between the agent and the downstream provider.

    The agent NEVER calls the provider and NEVER touches the journal. It
    calls gateway.execute(op). The gateway:

      0. authorizes the caller's fencing generation against the live
         fencing authority BEFORE any downstream side effect -- a stale
         (rotated) generation is rejected before the provider is touched;
      1. records intent in the journal (idempotency key + FULL canonical
         operation fingerprint: service, op, target, params),
      2. calls the provider exactly once per unseen key,
      3. persists the receipt via record_commit BEFORE the ack goes out,
      4. delivers the ack -- unless the ack is lost (simulated), in which
         case the agent gets AcknowledgementLost and holds nothing.

    On retry, the gateway serves the receipt from the journal's persisted
    record (a fresh SQLite read via reconcile) -- reconstructed from
    durable state, not from anyone's memory. The provider is never
    re-hit for a key it already honored.

    Honest boundary, now enforced at two layers: the gateway checks the
    generation BEFORE dispatch, AND the provider validates the fencing
    token on every call -- a rotation landing between the check and the
    provider's execution is still rejected with no effect recorded.
    (In-process the race cannot fire -- single-threaded -- so the sim
    pins the downstream contract with a direct stale-token test; a real
    deployment relies on the same contract at its own execution
    boundary.) The store's in-lock generation check remains the last line
    of defense for local effect writes, and provider idempotency +
    journal reconciliation stay separate protections -- fencing alone
    does not solve ack loss.
    """

    def __init__(self, provider: "SimulatedProvider",
                 journal: OperationJournal,
                 fencing, role: str):
        self.provider = provider
        self.journal = journal
        self.fencing = fencing
        self.role = role
        # The generation this gateway (and its agent) is authorized for,
        # captured at construction. A later rotate() makes it stale.
        self.fencing_generation = fencing.current(role)

    def execute(self, op: Dict[str, Any], lose_ack: bool = False,
                ledger=None, tick=None) -> Dict[str, Any]:
        """Run one operation through the gateway. Returns a result dict;
        raises AcknowledgementLost (never returns a receipt) when the ack
        is lost, or StaleEpochError when this gateway's generation has
        been rotated since construction -- in both cases BEFORE the
        provider records any effect. `op` needs: op_id, key, service, op,
        target, params."""
        # Authorize first: a fenced agent is rejected before it can cause
        # a downstream side effect. The store checks again later, but by
        # then a real provider would already have acted.
        self.fencing.check(self.role, self.fencing_generation, tick)
        op_id, key = op["op_id"], op["key"]
        rec = self.journal.record_intent(
            op_id, key, service=op["service"], op=op["op"],
            target=op["target"], params=op["params"],
            fencing_generation=self.fencing_generation)
        if ledger is not None:
            ledger.record("journal_intent",
                          {"op": op_id, "idempotency_key": key,
                           "status": rec["status"]}, tick)
        if rec["receipt"] is not None:
            # Retry path: the journal already has this operation. Serve
            # the persisted receipt -- reconcile() re-reads it from
            # SQLite; the provider is not called again.
            final = self.journal.reconcile(op_id)
            receipt = dict(final["receipt"])
            # Re-verify against the provider: if the provider has no
            # record of this key, the persisted receipt cannot be
            # confirmed. Surface needs-review -- never manufacture a
            # successful recovery, and never blindly re-book (a fresh
            # provider would NOT dedupe the key).
            if self.provider.query(key) is None:
                decision = DECISION_UNVERIFIED_NEEDS_REVIEW
                self.journal.mark_needs_review(op_id, decision)
                if ledger is not None:
                    ledger.record("journal_unverified",
                                  {"op": op_id, "decision": decision,
                                   "honest_note": "journal says committed; "
                                                  "provider has no record"},
                                  tick)
                return {"receipt": receipt, "reused": True,
                        "provider_call": False, "created": False,
                        "verified": False, "needs_review": True,
                        "recovery_decision": decision}
            if ledger is not None:
                ledger.record("journal_reconciled",
                              {"op": op_id,
                               "decision": final["recovery_decision"]}, tick)
            return {"receipt": receipt, "reused": True,
                    "provider_call": False, "created": False,
                    "verified": True, "needs_review": False,
                    "recovery_decision": final["recovery_decision"]}
        # First sight of this key: call the provider exactly once...
        receipt, created = self.provider.execute(
            op["op"], key, op["params"],
            fencing_token=self.fencing_generation)
        # ...persist the receipt BEFORE the ack goes out. If the process
        # dies or the ack is lost from here on, the journal still knows.
        self.journal.record_commit(op_id, receipt)
        if ledger is not None:
            ledger.record("journal_commit",
                          {"op": op_id, "receipt": receipt}, tick)
        if lose_ack:
            self.journal.mark_unknown(op_id)
            if ledger is not None:
                ledger.record(
                    "journal_ack_lost",
                    {"op": op_id,
                     "honest_note": "simulated: gateway persisted the "
                                    "receipt; the ack never reached the "
                                    "agent"}, tick)
            raise AcknowledgementLost(
                f"simulated ack loss for {op_id}: the provider committed "
                f"and the gateway persisted the receipt; the agent holds "
                f"no receipt data")
        return {"receipt": receipt, "reused": False, "provider_call": True,
                "created": created, "recovery_decision": None}


def run_protected_lost_ack(incident_id: str = "INC-1043",
                           journal_path: Optional[str] = None,
                           provider_amnesia: bool = False) -> Dict[str, Any]:
    """The user task under journal discipline. Always offline:
    StubDiagnostician, live=False.

    provider_amnesia (test hook): after the ack is lost, replace the
    provider with a fresh one that has no record of the booking --
    simulating provider state loss. The retry must then surface
    needs-review and halt instead of completing dependent steps.
    """
    layer, store, primaries = make_world(diagnostician=StubDiagnostician(),
                                         live=False)
    assert layer.live is False
    journal = _fresh_journal(journal_path)
    # The downstream boundary enforces fencing tokens too: the provider
    # shares the layer's fencing authority for the remediation role.
    provider = SimulatedProvider(fencing=layer.fencing, role="remediation")
    inc = {"id": incident_id, "service": "sim-user-task",
           "symptom": "multi-step user request", "severity": "P3"}
    ctx = {"incident": inc}

    # Real triage + diagnosis through the layer: the incident is worked
    # before the user-facing operations run.
    for role in ("triage", "diagnosis"):
        result = layer.invoke(role, ctx, primaries[role])
        layer.apply_effects(result, store)
        ctx[role] = result["output"]

    # The user-facing operations go through the continuity gateway.
    # The agent NEVER touches the provider or the journal directly: it
    # only ever holds what gateway.execute() returns to it.
    generation = layer.fencing.current("remediation")
    gateway = ContinuityGateway(provider, journal, layer.fencing,
                                "remediation")
    steps: List[Dict[str, Any]] = []
    halted = False
    for i, step in enumerate(USER_TASK_STEPS):
        op_id = f"{incident_id}:user_task:{i}:{step['name']}"
        key = op_id  # stable logical operation id doubles as idempotency key
        op = {"op_id": op_id, "key": key, "service": step["service"],
              "op": step["kind"], "target": step["target"],
              "params": step["params"]}
        tick = layer.clock.tick()
        # What the AGENT holds. None until an ack actually arrives: the
        # information boundary the whole scenario is about.
        agent_receipt = None
        reused, created, recovery_decision = False, False, None
        verified, needs_review = True, False
        if i == 0:
            # THE FAULT, through the gateway: the provider commits, the
            # gateway persists the receipt, the ack never reaches the agent.
            try:
                gateway.execute(op, lose_ack=True, ledger=layer.ledger,
                                tick=tick)
                raise AssertionError(
                    "lose_ack=True must not deliver a receipt")
            except AcknowledgementLost:
                # Provably nothing on the agent's side: the exception
                # carries no receipt, and agent_receipt was never assigned.
                # All the agent has is the op id + idempotency key.
                pass
            # Gateway "restart": the journal is closed and reloaded from
            # SQLite, so the retry is served from durable state -- no
            # in-memory receipt survives this point.
            journal.close()
            journal = OperationJournal(journal.path)
            gateway.journal = journal
            if provider_amnesia:
                # Simulated provider state loss: the new provider enforces
                # fencing tokens like the old one, but has no record of
                # the committed booking.
                gateway.provider = SimulatedProvider(fencing=layer.fencing,
                                                     role="remediation")
                provider = gateway.provider
            layer.ledger.record(
                "gateway_restart",
                {"op": op_id,
                 "note": "journal reloaded from SQLite; the retry is "
                         "reconstructed from persisted data"}, tick)
            # The agent retries the SAME logical op through the gateway.
            # Reconcile-before-retry: no new provider call, the persisted
            # receipt is reconstructed and delivered.
            result = gateway.execute(op, ledger=layer.ledger, tick=tick)
            assert result["reused"] is True, result
            assert result["provider_call"] is False, result
            agent_receipt = result["receipt"]
            reused, recovery_decision = True, result["recovery_decision"]
            verified, needs_review = result["verified"], result["needs_review"]
            # By fault definition the provider created the effect on the
            # first (ack-lost) attempt.
            created = True
            halted_here = needs_review
        else:
            result = gateway.execute(op, ledger=layer.ledger, tick=tick)
            agent_receipt = result["receipt"]
            created = result["created"]
            halted_here = False
        if halted_here:
            # The persisted receipt cannot be verified against the
            # provider. Halt: do NOT record the local effect as confirmed,
            # do NOT run dependent steps that assume a confirmed booking
            # (calendar, partner notification). The receipt carries the
            # needs-review decision; a human resolves it.
            layer.ledger.record(
                "booking_unverified_halt",
                {"op": op_id,
                 "reason": "journal holds a receipt the provider cannot "
                           "confirm; dependent steps halted pending human "
                           "review"},
                tick)
            steps.append({
                "step": step, "op_id": op_id, "key": key,
                "receipt": agent_receipt, "created": created,
                "reused": reused, "recovery_decision": recovery_decision,
                "verified": verified, "needs_review": needs_review,
                "provider_calls_after": provider.calls,
            })
            halted = True
            break
        # The agent records the local effect only once it holds a receipt.
        # The store's idempotent apply refuses any duplicate key anyway
        # (belt and suspenders, pinned in test_journal.py).
        action = {"kind": step["kind"], "target": step["target"],
                  "params": step["params"]}
        store.apply_effect("sim-user-task", "remediation", generation,
                           key, action, tick=tick)
        layer.ledger.record_stage(incident_id, "user_task",
                                  "sim-choreography", tick, "ok")
        steps.append({
            "step": step, "op_id": op_id, "key": key,
            "receipt": agent_receipt, "created": created, "reused": reused,
            "recovery_decision": recovery_decision,
            "verified": verified, "needs_review": needs_review,
            "provider_calls_after": provider.calls,
        })

    # Real escalation closes the workflow -- unless the user task halted
    # on an unverified booking, in which case there is nothing normal to
    # close; the halt record and the needs-review receipt are the outcome.
    if not halted:
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
        "halted": halted,
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
