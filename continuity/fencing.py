"""Epoch fencing: no split brain, ever.

Every agent holds an epoch (lease). Any write to the incident store must
carry the agent's *current* epoch. On failover the dead agent's epoch is
revoked and the standby is issued a fresh one. A recovered primary that
tries to write with its stale epoch is REJECTED until it is revalidated
and issued a new epoch at rejoin.

Optional epoch TTL (``epoch.ttl_ticks`` in continuity.yaml, 0 = off):
when enabled, an epoch that outlives its TTL is rejected like a stale
one. TTL is off by default, reproducing the brutal-proof behavior.

Thread-safe: safe under concurrent role invocations.
"""
from __future__ import annotations

import threading


class StaleEpochError(Exception):
    """Raised when a write carries a revoked, outdated, or expired epoch."""


class FencingAuthority:
    def __init__(self, ttl_ticks: int = 0, logger=None):
        self.ttl_ticks = ttl_ticks
        self.logger = logger
        self._epoch: dict = {}
        self._issued_tick: dict = {}
        self._revoked: set = set()
        self._lock = threading.RLock()

    def _log(self, event, **kw):
        if self.logger is not None:
            self.logger.log(event, **kw)

    def issue(self, agent_id: str, tick: int | None = None) -> int:
        """Issue (or re-issue) the current epoch for an agent."""
        with self._lock:
            self._revoked.discard(agent_id)
            self._epoch[agent_id] = self._epoch.get(agent_id, 0) + 1
            if tick is not None:
                self._issued_tick[agent_id] = tick
            epoch = self._epoch[agent_id]
        self._log("epoch_issued", agent=agent_id, tick=tick, epoch=epoch)
        return epoch

    def current(self, agent_id: str) -> int:
        with self._lock:
            return self._epoch.get(agent_id, 0)

    def revoke(self, agent_id: str, tick: int | None = None) -> None:
        """Revoke write authority immediately (failover)."""
        with self._lock:
            self._revoked.add(agent_id)
            epoch = self._epoch.get(agent_id, 0)
        self._log("epoch_revoked", agent=agent_id, tick=tick, epoch=epoch)

    def check(self, agent_id: str, epoch: int, tick: int | None = None) -> None:
        """Fail closed: stale, revoked, or expired epochs are rejected."""
        with self._lock:
            current = self._epoch.get(agent_id, 0)
            revoked = agent_id in self._revoked
            expired = (
                self.ttl_ticks > 0
                and tick is not None
                and agent_id in self._issued_tick
                and tick - self._issued_tick[agent_id] > self.ttl_ticks
            )
        if revoked or epoch != current or expired:
            reason = (
                "revoked" if revoked
                else "expired" if expired
                else f"stale (presented {epoch}, current {current})"
            )
            self._log("fencing_rejection", agent=agent_id, tick=tick,
                      level="WARNING", epoch=epoch, current=current,
                      reason=reason)
            raise StaleEpochError(
                f"write rejected: {agent_id} presented epoch {epoch}, "
                f"current is {current} ({reason})"
            )
