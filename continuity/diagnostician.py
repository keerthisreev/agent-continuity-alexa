"""Optional reasoning component -- the Nemotron seam.

The deterministic Sentinel is ALWAYS authoritative. The diagnostician only
attaches explanatory notes to the forensic ledger; it can never change a
verdict. The sentinel reaches correct verdicts with the diagnostician
disabled (None).

When the NEBIUS_API_KEY environment variable is set, NemotronDiagnostician
calls a Nemotron model through the Nebius Token Factory OpenAI-compatible
chat-completions endpoint, so the demo video visibly shows Nebius/NVIDIA
usage. When the key is absent (all tests, all offline builds) it falls back
to the deterministic stub. No network call is ever made without the key.

Reliability contract (this is what makes it production-grade rather than a
demo client):
  - 20s timeout, 2 retries with exponential backoff (configurable)
  - circuit breaker: 3 consecutive failures -> 60s open -> silent stub
    fallback while open (configurable)
  - diagnose() NEVER raises into the sentinel path: every failure degrades
    to stub text with a log line
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Callable, List, Protocol

import requests

from .config import CONFIG, get as _cfg_get
from .log import ContinuityLogger


class Diagnostician(Protocol):
    def diagnose(self, agent_id: str, health_vector: dict,
                 recent_violations: List[str]) -> str: ...


class StubDiagnostician:
    """Deterministic fallback. No network, no model, no surprises."""

    def diagnose(self, agent_id: str, health_vector: dict,
                 recent_violations: List[str]) -> str:
        unhealthy = [k for k, v in health_vector.items() if v is False]
        return ("stub-diagnosis(%s): deterministic verdict stands; "
                "failing layers=%s; violations=%d; no model consulted"
                % (agent_id, unhealthy or "none", len(recent_violations)))


class _CircuitOpen(Exception):
    pass


class NemotronDiagnostician:
    """Reasoning assistant via Nebius Token Factory (OpenAI-compatible).

    Secrets come from the environment ONLY (NEBIUS_API_KEY). Everything
    else comes from continuity.yaml / constructor args.
    """

    def __init__(self, api_key: str = "", base_url: str = "",
                 model: str = "", timeout_s: float = None,
                 retries: int = None, circuit_breaker_failures: int = None,
                 circuit_breaker_open_s: float = None,
                 backoff_base_s: float = 0.5,
                 transport: Callable[[dict], str] = None,
                 config: dict = None, logger=None):
        cfg = config if config is not None else CONFIG
        self.api_key = api_key or os.environ.get("NEBIUS_API_KEY", "")
        self.base_url = (base_url or _cfg_get(cfg, "nemotron", "base_url")).rstrip("/")
        self.model = model or _cfg_get(cfg, "nemotron", "model")
        self.timeout_s = (timeout_s if timeout_s is not None
                          else _cfg_get(cfg, "nemotron", "timeout_s", default=20))
        self.retries = (retries if retries is not None
                        else _cfg_get(cfg, "nemotron", "retries", default=2))
        self._breaker_threshold = (
            circuit_breaker_failures if circuit_breaker_failures is not None
            else _cfg_get(cfg, "nemotron", "circuit_breaker_failures", default=3))
        self._breaker_open_s = (
            circuit_breaker_open_s if circuit_breaker_open_s is not None
            else _cfg_get(cfg, "nemotron", "circuit_breaker_open_s", default=60))
        self._backoff_base_s = backoff_base_s
        self._transport = transport or self._requests_transport
        self.logger = logger or ContinuityLogger(name="diagnostician")
        self._lock = threading.RLock()
        self._consecutive_failures = 0
        self._breaker_open_until = 0.0

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    @property
    def circuit_open(self) -> bool:
        with self._lock:
            return time.monotonic() < self._breaker_open_until

    # -- public ----------------------------------------------------------
    def diagnose(self, agent_id: str, health_vector: dict,
                 recent_violations: List[str]) -> str:
        """Advisory note. NEVER raises: degrades to stub text on any failure."""
        try:
            return self._diagnose_inner(agent_id, health_vector, recent_violations)
        except Exception as exc:  # noqa: BLE001 - never break the sentinel
            self.logger.log("diagnostician_failed", level="WARNING",
                            agent=agent_id, error=str(exc))
            return (f"nemotron-diagnosis({agent_id}): model call failed ({exc}); "
                    f"deterministic verdict stands")

    # -- internals ---------------------------------------------------------
    def _diagnose_inner(self, agent_id, health_vector, recent_violations) -> str:
        if not self.available:
            return StubDiagnostician().diagnose(agent_id, health_vector,
                                                recent_violations)
        with self._lock:
            if time.monotonic() < self._breaker_open_until:
                self.logger.log("diagnostician_circuit_open", agent=agent_id,
                                level="WARNING")
                return StubDiagnostician().diagnose(agent_id, health_vector,
                                                    recent_violations)
        prompt = self._prompt(agent_id, health_vector, recent_violations)
        body = {
            "model": self.model,
            "messages": [
                {"role": "system",
                 "content": "You are a terse reliability engineer. Two sentences max."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 300,
        }
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                text = self._transport(body)
            except Exception as exc:  # noqa: BLE001 - transport failure is routine
                last_exc = exc
                if attempt < self.retries:
                    time.sleep(self._backoff_base_s * (2 ** attempt))
                continue
            self._record_success()
            return f"nemotron-diagnosis({agent_id}) [{self.model}]: {text.strip()[:600]}"
        self._record_failure()
        raise RuntimeError(f"all {self.retries + 1} attempts failed: {last_exc}")

    def _prompt(self, agent_id, health_vector, recent_violations) -> str:
        return (
            "You are a reliability engineer watching an AI incident-management "
            "agent. A deterministic watchdog already decided the agent's health; "
            "your job is to explain it in one or two sentences for the incident "
            "record. Do not hedge about the verdict.\n\n"
            f"Agent: {agent_id}\n"
            f"Health vector: {json.dumps(health_vector)}\n"
            f"Recent violations: {recent_violations}\n\n"
            "Explain what failed and what it means operationally."
        )

    def _requests_transport(self, body: dict) -> str:
        resp = requests.post(
            self.base_url + "/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        payload = resp.json()
        return payload["choices"][0]["message"]["content"]

    def _record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0

    def _record_failure(self) -> None:
        with self._lock:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._breaker_threshold:
                self._breaker_open_until = (time.monotonic()
                                            + self._breaker_open_s)
                self.logger.log("diagnostician_circuit_opened", level="ERROR",
                                consecutive_failures=self._consecutive_failures,
                                open_s=self._breaker_open_s)


def default_diagnostician(config: dict = None) -> Diagnostician:
    """Nemotron via Nebius when NEBIUS_API_KEY is set, stub otherwise."""
    candidate = NemotronDiagnostician(config=config)
    return candidate if candidate.available else StubDiagnostician()
