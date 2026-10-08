"""Shared incident store (existing workflow infrastructure).

Not part of the continuity layer: this is the store the *existing*
workflow already writes to. Every write carries the writer's epoch; the
fencing authority rejects stale epochs, and duplicate action ids are
refused (counted, not applied twice).
"""
from __future__ import annotations


class IncidentStore:
    def __init__(self, fencing, ledger):
        self.fencing = fencing
        self.ledger = ledger
        self.applied: dict = {}   # action_id -> effect record
        self.incidents: dict = {}

    def apply_effect(self, agent_id: str, epoch: int, action_id: str,
                     action: dict) -> bool:
        """Apply one action effect. Returns False if it was a duplicate."""
        self.fencing.check(agent_id, epoch)  # raises StaleEpochError
        if action_id in self.applied:
            return False
        self.applied[action_id] = {
            "agent": agent_id, "epoch": epoch,
            "kind": action.get("kind"), "target": action.get("target"),
            "params": action.get("params", {}),
        }
        return True

    def effects_for(self, incident_id: str):
        prefix = incident_id + ":"
        return {k: v for k, v in self.applied.items() if k.startswith(prefix)}
