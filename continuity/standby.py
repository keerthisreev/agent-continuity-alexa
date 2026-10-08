"""Standby controller: owns the standby agent lifecycle for one role.

The standby is an ordinary healthy agent. On activation it receives the
last known-good continuity package so it can RESUME mid-workflow instead
of restarting. It stands down on safe rejoin.
"""
from __future__ import annotations


class StandbyController:
    def __init__(self, standby_agent):
        self.agent = standby_agent
        self.active = False
        self.package = None

    def activate(self, package) -> None:
        self.active = True
        self.package = package

    def stand_down(self) -> None:
        self.active = False
        self.package = None
