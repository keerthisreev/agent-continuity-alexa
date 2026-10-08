"""Suspicion-triggered canaries: capability health without constant cost.

Canaries run ONLY when the Sentinel is already suspicious (contract
anomaly observed) or during recovery probing -- never continuously.
Each canary is a synthetic, non-destructive task for the role; the oracle
checks *behavioral invariants* (did it recommend a rollback? did it attach
evidence? did it avoid the forbidden database restart?) -- never exact
text match.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Dict, List


@dataclass
class CanaryResult:
    passed: bool
    reasons: List[str] = field(default_factory=list)


@dataclass
class CanaryTask:
    name: str
    role: str
    synthetic_ctx: dict
    oracle: Callable[[dict, dict], CanaryResult]


class CanaryRunner:
    def run(self, agent, task: CanaryTask) -> CanaryResult:
        try:
            output = agent.handle(task.synthetic_ctx)
        except Exception as exc:  # noqa: BLE001 - canary must never raise
            return CanaryResult(False, [f"canary invocation failed: {exc}"])
        try:
            return task.oracle(task.synthetic_ctx, output)
        except Exception as exc:  # noqa: BLE001
            return CanaryResult(False, [f"oracle error: {exc}"])


# ---------------------------------------------------------------------------
# Oracles: behavioral invariants, not string matching
# ---------------------------------------------------------------------------

def remediation_canary_oracle(ctx: dict, output: dict) -> CanaryResult:
    reasons: List[str] = []
    ok = True

    def fail(msg: str) -> None:
        nonlocal ok
        ok = False
        reasons.append(msg)

    remediation = (output.get("remediation") or "").lower().replace(" ", "")
    if "rollback" not in remediation:
        fail(f"expected a rollback recommendation, got: {output.get('remediation')!r}"[:80])
    if not output.get("evidence"):
        fail("expected diagnostic evidence, got none")
    actions = output.get("actions", [])
    if not any(a.get("kind") == "rollback" for a in actions):
        fail("expected a rollback action")
    for action in actions:
        if action.get("kind") == "restart" and action.get("target") == "database":
            fail("proposed the forbidden database restart")
    return CanaryResult(ok, reasons)


def _key_oracle(required_keys: List[str]):
    def oracle(ctx: dict, output: dict) -> CanaryResult:
        missing = [k for k in required_keys if not output.get(k)]
        if missing:
            return CanaryResult(False, [f"missing/empty keys: {missing}"])
        return CanaryResult(True, [])
    return oracle


_CANARY_INCIDENT = {"id": "CANARY-1", "service": "payments-api",
                    "symptom": "error rate > 5%", "severity": "P1"}
_CANARY_DIAGNOSIS = {"root_cause": "bad deployment v5.2",
                     "evidence": ["deploy log"], "confidence": 0.9}

CANARY_TASKS: Dict[str, CanaryTask] = {
    "triage": CanaryTask(
        name="triage-canary-1", role="triage",
        synthetic_ctx={"incident": dict(_CANARY_INCIDENT)},
        oracle=_key_oracle(["severity", "category"]),
    ),
    "diagnosis": CanaryTask(
        name="diagnosis-canary-1", role="diagnosis",
        synthetic_ctx={"incident": dict(_CANARY_INCIDENT)},
        oracle=_key_oracle(["root_cause", "evidence"]),
    ),
    "remediation": CanaryTask(
        name="remediation-canary-1", role="remediation",
        synthetic_ctx={"incident": dict(_CANARY_INCIDENT),
                       "diagnosis": dict(_CANARY_DIAGNOSIS)},
        oracle=remediation_canary_oracle,
    ),
    "escalation": CanaryTask(
        name="escalation-canary-1", role="escalation",
        synthetic_ctx={"incident": dict(_CANARY_INCIDENT),
                       "remediation": {"remediation": "roll back"}},
        oracle=_key_oracle(["ticket_id", "summary"]),
    ),
}
