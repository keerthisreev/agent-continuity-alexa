"""Minimal observable agent interface.

Agents know NOTHING about the continuity layer. They expose only:
  - agent_id / role
  - alive flag (process liveness)
  - handle(ctx) -> output dict   (may raise AgentProcessDead)
  - a ModelBackend they call for "intelligence" (scripted, deterministic)

The continuity layer observes from the outside: lifecycle events, inputs,
outputs, and effects applied to the shared incident store.
"""
from __future__ import annotations
import json
from typing import Optional, Protocol


class BackendError(Exception):
    """The agent's model dependency failed (connection refused, timeout, ...)."""


class AgentProcessDead(Exception):
    """The agent process itself is gone (hard failure)."""


class ModelBackend(Protocol):
    def complete(self, prompt: str) -> str: ...


class ScriptedBackend:
    """Deterministic stub of a model endpoint.

    modes:
      healthy  -> returns the canned healthy response
      llm_down -> raises BackendError (dependency broken, agent stays alive)
      gray     -> returns a plausible-but-useless response
    """

    def __init__(self, healthy_response: str, gray_response: Optional[str] = None,
                 mode: str = "healthy"):
        self.healthy_response = healthy_response
        self.gray_response = gray_response
        self.mode = mode

    def complete(self, prompt: str) -> str:
        if self.mode == "llm_down":
            raise BackendError("connection refused by model endpoint")
        if self.mode == "gray" and self.gray_response is not None:
            return self.gray_response
        return self.healthy_response


class IncidentAgent:
    """A plain incident-workflow agent. No continuity-layer imports here."""

    def __init__(self, agent_id: str, role: str, backend: ModelBackend):
        self.agent_id = agent_id
        self.role = role
        self.backend = backend
        self.alive = True

    def handle(self, ctx: dict) -> dict:
        if not self.alive:
            raise AgentProcessDead(f"{self.agent_id}: process is dead")
        return self._run(ctx)

    def _run(self, ctx: dict) -> dict:  # pragma: no cover - overridden
        raise NotImplementedError

    def __repr__(self) -> str:  # pragma: no cover
        return f"<{self.role}:{self.agent_id} alive={self.alive}>"
