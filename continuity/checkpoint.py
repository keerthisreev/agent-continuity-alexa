"""Continuity packages: what the standby needs to RESUME, not restart.

Captured after every healthy agent output. On failover the standby receives
the last known-good package: which actions are already done (never redo),
what was planned, and the evidence/role state to continue from.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Dict, List


@dataclass
class ContinuityPackage:
    agent_id: str          # logical agent, e.g. "remediation"
    role: str
    incident_id: str
    tick: int              # last known-good tick
    planned_action_ids: List[str] = field(default_factory=list)
    completed_action_ids: List[str] = field(default_factory=list)
    evidence_refs: List[str] = field(default_factory=list)
    state: Dict = field(default_factory=dict)


def remediation_state_adapter(output: dict) -> Dict:
    return {
        "remediation": output.get("remediation"),
        "planned_actions": [
            f"{a.get('kind')}:{a.get('target')}" for a in output.get("actions", [])
        ],
    }


def generic_state_adapter(output: dict) -> Dict:
    return {"output_keys": sorted(output.keys())}


STATE_ADAPTERS: Dict[str, Callable[[dict], Dict]] = {
    "triage": generic_state_adapter,
    "diagnosis": generic_state_adapter,
    "remediation": remediation_state_adapter,
    "escalation": generic_state_adapter,
}


def capture_package(agent_id: str, role: str, incident_id: str, output: dict,
                    tick: int, state_adapter: Callable[[dict], Dict],
                    planned_action_ids: List[str]) -> ContinuityPackage:
    return ContinuityPackage(
        agent_id=agent_id,
        role=role,
        incident_id=incident_id,
        tick=tick,
        planned_action_ids=list(planned_action_ids),
        evidence_refs=list(output.get("evidence", [])),
        state=state_adapter(output),
    )
