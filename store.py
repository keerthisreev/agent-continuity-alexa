"""Shared incident store (existing workflow infrastructure).

Not part of the continuity layer: this is the store the *existing*
workflow already writes to. Every write carries the writer's epoch; the
fencing authority rejects stale epochs, and duplicate action ids are
refused (counted, not applied twice).

Thread-safe: safe under concurrent role invocations.
"""
from __future__ import annotations

import threading

from continuity.log import ContinuityLogger


class IncidentStore:
    def __init__(self, fencing, ledger, logger=None):
        self.fencing = fencing
        self.ledger = ledger
        self.logger = logger or getattr(ledger, "logger", None) or ContinuityLogger()
        self.applied: dict = {}   # action_id -> effect record
        self.incidents: dict = {}
        self._lock = threading.RLock()

    def apply_effect(self, agent_id: str, epoch: int, action_id: str,
                     action: dict, tick: int | None = None) -> bool:
        """Apply one action effect. Returns False if it was a duplicate.

        `action_id` is the explicit idempotency key: the same key is never
        applied twice, no matter which side (primary or standby) retries.
        """
        self.fencing.check(agent_id, epoch, tick)  # raises StaleEpochError
        with self._lock:
            if action_id in self.applied:
                self.logger.log("duplicate_refused", agent=agent_id, tick=tick,
                                idempotency_key=action_id)
                return False
            self.applied[action_id] = {
                "agent": agent_id, "epoch": epoch,
                "kind": action.get("kind"), "target": action.get("target"),
                "params": action.get("params", {}),
            }
        self.logger.log("effect_applied", agent=agent_id, tick=tick,
                        idempotency_key=action_id,
                        kind=action.get("kind"), target=action.get("target"))
        return True

    def effects_for(self, incident_id: str):
        prefix = incident_id + ":"
        with self._lock:
            return {k: v for k, v in self.applied.items() if k.startswith(prefix)}
