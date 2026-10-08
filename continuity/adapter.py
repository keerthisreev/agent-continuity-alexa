"""The adapter boundary: the continuity layer underneath existing agents.

Usage:

    layer = ContinuityLayer()                      # diagnostician optional
    layer.register(agent_id="remediation",
                   role_contract=REMEDIATION_CONTRACT,
                   state_adapter=remediation_state_adapter,
                   standby=StandbyController(make_standby("remediation")),
                   primary=remediation_agent)

    result = layer.invoke("remediation", ctx, remediation_agent)
    layer.apply_effects(result, store)

Agents are never modified. The layer observes inputs/outputs, checkpoints
healthy outputs, routes to the standby on failover, and fences epochs.
"""
from __future__ import annotations

from .canary import CANARY_TASKS, CanaryRunner
from .checkpoint import STATE_ADAPTERS, capture_package
from .diagnostician import Diagnostician
from .fencing import FencingAuthority, StaleEpochError
from .ledger import ForensicLedger
from .sentinel import (FAILOVER, HEALTHY, RECOVERING, REJOIN, Sentinel)


class Clock:
    """Logical clock: deterministic ticks, no wall time."""

    def __init__(self):
        self.t = 0

    def tick(self) -> int:
        self.t += 1
        return self.t

    def now(self) -> int:
        return self.t


class ContinuityLayer:
    def __init__(self, diagnostician: Diagnostician = None):
        self.clock = Clock()
        self.fencing = FencingAuthority()
        self.ledger = ForensicLedger(self.clock)
        self.canary_runner = CanaryRunner()
        self.sentinel = Sentinel(
            fencing=self.fencing, ledger=self.ledger,
            canary_runner=self.canary_runner, clock=self.clock,
            diagnostician=diagnostician)
        self._reg: dict = {}
        self._checkpoints: dict = {}  # logical agent_id -> ContinuityPackage

    # -- registration ------------------------------------------------------
    def register(self, agent_id: str, role_contract, state_adapter,
                 standby, primary=None, canary_task=None) -> None:
        role = role_contract.role
        task = canary_task or CANARY_TASKS[role]
        adapter = state_adapter or STATE_ADAPTERS[role]
        self._reg[agent_id] = {
            "role": role, "contract": role_contract,
            "state_adapter": adapter, "standby": standby,
            "canary_task": task,
        }
        self.sentinel.register(agent_id, role_contract, task, primary)
        epoch = self.fencing.issue(agent_id)
        self.ledger.record("registered",
                           {"agent": agent_id, "role": role, "epoch": epoch})

    # -- invocation ----------------------------------------------------------
    @staticmethod
    def _action_id(incident_id: str, role: str, index: int, action: dict) -> str:
        return f"{incident_id}:{role}:{index}:{action.get('kind')}:{action.get('target')}"

    def invoke(self, agent_id: str, ctx: dict, agent_fn):
        """Invoke the authoritative side (primary or standby) for a role.

        Returns a result dict the caller passes to apply_effects().
        On failover the stage is transparently retried with the standby.
        """
        reg = self._reg[agent_id]
        role = reg["role"]
        incident_id = ctx["incident"]["id"]
        for _ in range(2):  # at most one failover per invocation
            active = self.sentinel.active_for(agent_id)
            agent = agent_fn if active == "primary" else reg["standby"].agent
            epoch = self.fencing.current(agent.agent_id)
            tick = self.clock.tick()
            self.ledger.record(
                "invoke",
                {"agent": agent.agent_id, "role": role,
                 "incident": incident_id, "epoch": epoch}, tick)
            try:
                output = agent.handle(ctx)
            except Exception as exc:  # noqa: BLE001 - crash is a signal
                decision = self.sentinel.report_crash(agent_id, tick, exc)
                self.ledger.record_stage(incident_id, role, agent.agent_id,
                                         tick, "crashed")
                if active == "standby":
                    raise RuntimeError(f"standby {agent.agent_id} also crashed")
                self._do_failover(agent_id, tick)
                continue
            decision = self.sentinel.check_output(agent_id, ctx, output, tick)
            if decision == "failover":
                self.ledger.record_stage(incident_id, role, agent.agent_id,
                                         tick, "bad_output")
                crit = [v for v in self.sentinel.last_violations[agent_id]
                        if v.severity == "critical"]
                if crit:
                    # A plausible-but-wrong output was *attempted*: a human
                    # should review what almost went out.
                    self.ledger.flag_human_review(
                        incident_id,
                        f"{agent_id} attempted: {crit[0].message}", tick)
                self._do_failover(agent_id, tick)
                continue
            outcome = "standby" if active == "standby" else "ok"
            self.ledger.record_stage(incident_id, role, agent.agent_id,
                                     tick, outcome)
            if decision == "ok":
                planned = [self._action_id(incident_id, role, i, a)
                           for i, a in enumerate(output.get("actions", []))]
                new_pkg = capture_package(
                    agent_id, role, incident_id, output, tick,
                    reg["state_adapter"], planned)
                # Preserve already-completed work for this incident across
                # the failover boundary: the standby must not redo it.
                prev = self._checkpoints.get(agent_id)
                if prev is not None and prev.incident_id == incident_id:
                    for aid in prev.completed_action_ids:
                        if (aid in new_pkg.planned_action_ids
                                and aid not in new_pkg.completed_action_ids):
                            new_pkg.completed_action_ids.append(aid)
                self._checkpoints[agent_id] = new_pkg
            return {"agent_id": agent_id, "role": role,
                    "incident_id": incident_id, "active": active,
                    "active_agent_id": agent.agent_id, "epoch": epoch,
                    "output": output, "tick": tick}
        raise RuntimeError(f"failover loop for {agent_id}")

    def _do_failover(self, agent_id: str, tick: int) -> None:
        reg = self._reg[agent_id]
        package = self._checkpoints.get(agent_id)
        self.fencing.revoke(agent_id)
        self.ledger.record("fencing",
                           {"agent": agent_id, "action": "epoch revoked"}, tick)
        standby = reg["standby"]
        epoch = self.fencing.issue(standby.agent.agent_id)
        standby.activate(package)
        self.sentinel.set_state(agent_id, FAILOVER, tick)
        self.ledger.mark_failover(tick, standby.agent.agent_id, epoch)
        self.ledger.record(
            "standby_activated",
            {"standby": standby.agent.agent_id, "epoch": epoch,
             "resumed_from_tick": package.tick if package else None,
             "resumed_from_incident": package.incident_id if package else None},
            tick)

    # -- effects -------------------------------------------------------------
    def apply_effects(self, result: dict, store) -> None:
        """Apply an output's actions to the store: idempotent, epoch-fenced."""
        agent_id = result["agent_id"]
        package = self._checkpoints.get(agent_id)
        for i, action in enumerate(result["output"].get("actions", [])):
            action_id = self._action_id(result["incident_id"], result["role"],
                                        i, action)
            if package and action_id in package.completed_action_ids:
                # Standby replays the plan; already-done work is skipped.
                self.ledger.count_duplicate_prevented(action_id)
                continue
            applied = store.apply_effect(result["active_agent_id"],
                                         result["epoch"], action_id, action)
            if not applied:
                self.ledger.count_duplicate_prevented(action_id)
                continue
            if package and action_id not in package.completed_action_ids:
                package.completed_action_ids.append(action_id)

    # -- recovery --------------------------------------------------------------
    def attempt_rejoin(self, agent_id: str) -> bool:
        """Revalidate the primary and return it to service at a new epoch.

        The standby stays authoritative until every probe passes.
        """
        tick = self.clock.tick()
        if self.sentinel.state_of(agent_id) != FAILOVER:
            return False
        self.sentinel.set_state(agent_id, RECOVERING, tick)
        if not self.sentinel.probe_recovery(agent_id, tick):
            self.sentinel.set_state(agent_id, FAILOVER, tick)
            self.ledger.record("rejoin_denied", {"agent": agent_id}, tick)
            return False
        new_epoch = self.fencing.issue(agent_id)
        self.sentinel.set_state(agent_id, REJOIN, tick)
        self._reg[agent_id]["standby"].stand_down()
        self.sentinel.set_state(agent_id, HEALTHY, tick)
        self.ledger.end_failure_window(
            tick, f"primary rejoined at epoch {new_epoch}")
        self.ledger.record("rejoin_complete",
                           {"agent": agent_id, "new_epoch": new_epoch}, tick)
        return True
