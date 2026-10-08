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
"""
from __future__ import annotations
import json
import os
import urllib.request
from typing import List, Protocol


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


class NemotronDiagnostician:
    """Reasoning assistant via Nebius Token Factory (OpenAI-compatible).

    Env overrides:
      NEBIUS_API_KEY   bearer token (required; her key, never committed)
      NEBIUS_BASE_URL  default https://api.tokenfactory.nebius.ai/v1
      NEBIUS_MODEL     default nvidia/Nemotron-3-Nano-30B
    """

    DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.ai/v1"
    DEFAULT_MODEL = "nvidia/Nemotron-3-Nano-30B"

    def __init__(self, api_key: str = "", base_url: str = "",
                 model: str = "", timeout_s: int = 20):
        self.api_key = api_key or os.environ.get("NEBIUS_API_KEY", "")
        self.base_url = (base_url or os.environ.get("NEBIUS_BASE_URL",
                                                    self.DEFAULT_BASE_URL)).rstrip("/")
        self.model = model or os.environ.get("NEBIUS_MODEL", self.DEFAULT_MODEL)
        self.timeout_s = timeout_s

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def diagnose(self, agent_id: str, health_vector: dict,
                 recent_violations: List[str]) -> str:
        if not self.available:
            return StubDiagnostician().diagnose(agent_id, health_vector,
                                                recent_violations)
        prompt = (
            "You are a reliability engineer watching an AI incident-management "
            "agent. A deterministic watchdog already decided the agent's health; "
            "your job is to explain it in one or two sentences for the incident "
            "record. Do not hedge about the verdict.\n\n"
            f"Agent: {agent_id}\n"
            f"Health vector: {json.dumps(health_vector)}\n"
            f"Recent violations: {recent_violations}\n\n"
            "Explain what failed and what it means operationally."
        )
        try:
            text = self._chat(prompt)
        except Exception as exc:  # noqa: BLE001 - never break the sentinel
            return (f"nemotron-diagnosis({agent_id}): model call failed ({exc}); "
                    f"deterministic verdict stands")
        return f"nemotron-diagnosis({agent_id}) [{self.model}]: {text.strip()[:600]}"

    def _chat(self, prompt: str) -> str:
        body = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system",
                 "content": "You are a terse reliability engineer. Two sentences max."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 300,
        }).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=body,
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return payload["choices"][0]["message"]["content"]


def default_diagnostician() -> Diagnostician:
    """Nemotron via Nebius when NEBIUS_API_KEY is set, stub otherwise."""
    candidate = NemotronDiagnostician()
    return candidate if candidate.available else StubDiagnostician()
