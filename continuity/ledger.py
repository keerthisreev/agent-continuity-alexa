"""Forensic ledger: the complete, timestamped record of every failure.

Records the failure window (first anomaly -> confirmed -> failover ->
recovery -> rejoin), the affected-work map (which incidents entered the
window and each item's disposition), duplicate writes prevented, and the
full ordered timeline. Timestamps are logical ticks: deterministic.
"""
from __future__ import annotations
from typing import Dict, List, Optional


class ForensicLedger:
    def __init__(self, clock):
        self.clock = clock
        self.timeline: List[dict] = []
        self.windows: List[dict] = []
        self.stage_records: List[dict] = []
        self.duplicates_prevented: int = 0
        self.human_review: List[dict] = []

    # -- primitives ------------------------------------------------------
    def record(self, kind: str, detail: dict, tick: Optional[int] = None) -> None:
        t = self.clock.now() if tick is None else tick
        self.timeline.append({"tick": t, "kind": kind, "detail": detail})

    def record_stage(self, incident_id: str, stage: str, agent_id: str,
                     tick: int, outcome: str) -> None:
        """outcome: ok | bad_output | crashed | standby"""
        self.stage_records.append({
            "incident": incident_id, "stage": stage, "agent": agent_id,
            "tick": tick, "outcome": outcome,
        })

    def flag_human_review(self, incident_id: str, reason: str,
                          tick: Optional[int] = None) -> None:
        t = self.clock.now() if tick is None else tick
        self.human_review.append({"incident": incident_id, "reason": reason, "tick": t})
        self.record("human_review_flagged",
                    {"incident": incident_id, "reason": reason}, t)

    def count_duplicate_prevented(self, action_id: str,
                                  tick: Optional[int] = None) -> None:
        self.duplicates_prevented += 1
        self.record("duplicate_write_prevented", {"action_id": action_id}, tick)

    # -- failure windows ---------------------------------------------------
    def begin_failure_window(self, agent_id: str, tick: int, reason: str,
                             first_anomaly_tick: int) -> None:
        self.windows.append({
            "agent": agent_id,
            "first_anomaly_tick": first_anomaly_tick,
            "quarantined_tick": tick,
            "failover_tick": None,
            "end_tick": None,
            "reason": reason,
            "resolution": None,
        })
        self.record("failure_window_open",
                    {"agent": agent_id, "reason": reason}, tick)

    def mark_failover(self, tick: int, standby_id: str, standby_epoch: int) -> None:
        if self.windows:
            self.windows[-1]["failover_tick"] = tick
        self.record("failover",
                    {"standby": standby_id, "standby_epoch": standby_epoch}, tick)

    def end_failure_window(self, tick: int, resolution: str) -> None:
        if self.windows:
            self.windows[-1]["end_tick"] = tick
            self.windows[-1]["resolution"] = resolution
        self.record("failure_window_closed", {"resolution": resolution}, tick)

    # -- derived views -------------------------------------------------------
    def _incidents_in_window(self, start: int, end: int) -> List[str]:
        seen = []
        for rec in self.stage_records:
            if start <= rec["tick"] <= end and rec["incident"] not in seen:
                seen.append(rec["incident"])
        return seen

    def _disposition(self, incident_id: str) -> str:
        recs = [r for r in self.stage_records if r["incident"] == incident_id]
        outcomes = [r["outcome"] for r in recs]
        flagged = any(h["incident"] == incident_id for h in self.human_review)
        if flagged:
            return "human review"
        if any(o in ("bad_output", "crashed") for o in outcomes):
            if "standby" in outcomes:
                return "replayed by standby"
            return "failed - needs replay"
        if "standby" in outcomes:
            return "recovered via standby"
        if recs and all(o == "ok" for o in outcomes):
            return "completed clean"
        return "incomplete"

    def affected_work(self) -> Dict[str, str]:
        """incident_id -> disposition for every incident the layer has seen."""
        result: Dict[str, str] = {}
        seen: List[str] = []
        for rec in self.stage_records:
            if rec["incident"] not in seen:
                seen.append(rec["incident"])
        for inc_id in seen:
            result[inc_id] = self._disposition(inc_id)
        return result

    def window_incidents(self) -> List[str]:
        """Incidents with stage activity inside the latest failure window."""
        if not self.windows:
            return []
        w = self.windows[-1]
        start = w["first_anomaly_tick"]
        end = w["end_tick"] or w["failover_tick"] or start
        return self._incidents_in_window(start, end)

    def tsfd(self) -> Optional[int]:
        """Time to Semantic Failure Detection: first anomaly -> failover."""
        if not self.windows:
            return None
        w = self.windows[-1]
        if w["failover_tick"] is None:
            return None
        return w["failover_tick"] - w["first_anomaly_tick"]

    def report(self) -> dict:
        return {
            "failure_windows": self.windows,
            "affected_work": self.affected_work(),
            "window_incidents": self.window_incidents(),
            "stage_records": self.stage_records,
            "duplicates_prevented": self.duplicates_prevented,
            "human_review": self.human_review,
            "tsfd_ticks": self.tsfd(),
            "timeline": self.timeline,
        }
