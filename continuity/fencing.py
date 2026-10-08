"""Epoch fencing: no split brain, ever.

Every agent holds an epoch (lease). Any write to the incident store must
carry the agent's *current* epoch. On failover the dead agent's epoch is
revoked and the standby is issued a fresh one. A recovered primary that
tries to write with its stale epoch is REJECTED until it is revalidated
and issued a new epoch at rejoin.
"""
from __future__ import annotations


class StaleEpochError(Exception):
    """Raised when a write carries a revoked or outdated epoch."""


class FencingAuthority:
    def __init__(self):
        self._epoch: dict = {}
        self._revoked: set = set()

    def issue(self, agent_id: str) -> int:
        """Issue (or re-issue) the current epoch for an agent."""
        self._revoked.discard(agent_id)
        self._epoch[agent_id] = self._epoch.get(agent_id, 0) + 1
        return self._epoch[agent_id]

    def current(self, agent_id: str) -> int:
        return self._epoch.get(agent_id, 0)

    def revoke(self, agent_id: str) -> None:
        """Revoke write authority immediately (failover)."""
        self._revoked.add(agent_id)

    def check(self, agent_id: str, epoch: int) -> None:
        """Fail closed: stale or revoked epochs are rejected."""
        if agent_id in self._revoked or epoch != self._epoch.get(agent_id, 0):
            raise StaleEpochError(
                f"write rejected: {agent_id} presented epoch {epoch}, "
                f"current is {self._epoch.get(agent_id, 0)}"
                + (" (revoked)" if agent_id in self._revoked else "")
            )
