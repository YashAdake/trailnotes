"""Vision backends. Ollama is the real one; Mock exists so the pipeline is testable without a GPU."""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from typing import Protocol

import requests

PROMPT = """You are helping write a field journal entry for one photo taken on a walk.
Describe only what is visible. Do not guess where it was taken.
Name living things (plants, birds, insects, animals) only if you can see them, and
give an honest confidence: "low", "medium" or "high". If you are unsure, say "low".
Reply with JSON only."""

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "terrain": {"type": "string"},
        "living_things": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                },
                "required": ["name", "confidence"],
            },
        },
    },
    "required": ["title", "description", "terrain", "living_things"],
}

_CONFIDENCE = {"low", "medium", "high"}


@dataclass
class Observation:
    title: str
    description: str
    terrain: str = ""
    living_things: list[dict] = field(default_factory=list)


class BackendError(RuntimeError):
    """The model could not be reached or refused the request."""


class Backend(Protocol):
    name: str

    def preflight(self) -> None: ...

    def observe(self, jpeg: bytes) -> Observation: ...


def _clip(value, limit: int) -> str:
    return str(value).strip()[:limit] if value is not None else ""


def parse_observation(text: str) -> Observation:
    """Parse model output. Raises ValueError if it is not usable JSON, so the
    caller records a failure instead of publishing garbage as a journal entry."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in model output")
    data = json.loads(cleaned[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("model output is not a JSON object")
    title = _clip(data.get("title"), 120)
    description = _clip(data.get("description"), 1200)
    if not title and not description:
        raise ValueError("model output has neither title nor description")
    things = []
    raw_things = data.get("living_things")
    for item in raw_things if isinstance(raw_things, list) else []:
        if not isinstance(item, dict) or not _clip(item.get("name"), 80):
            continue
        conf = _clip(item.get("confidence"), 10).lower()
        things.append(
            {"name": _clip(item.get("name"), 80), "confidence": conf if conf in _CONFIDENCE else "low"}
        )
    return Observation(
        title=title or "Untitled",
        description=description,
        terrain=_clip(data.get("terrain"), 120),
        living_things=things[:12],
    )


class OllamaBackend:
    def __init__(self, model: str, host: str = "http://localhost:11434", timeout: int = 300):
        self.model = model
        self.host = host.rstrip("/")
        self.timeout = timeout
        self.name = f"ollama:{model}"

    def preflight(self) -> None:
        try:
            r = requests.get(f"{self.host}/api/tags", timeout=10)
            r.raise_for_status()
        except requests.RequestException as exc:
            raise BackendError(
                f"Cannot reach Ollama at {self.host} ({exc.__class__.__name__}). "
                "Start it with `ollama serve`."
            ) from exc
        installed = {m.get("name", "") for m in r.json().get("models", [])}
        wanted = self.model if ":" in self.model else f"{self.model}:latest"
        if wanted not in installed:
            raise BackendError(
                f"Model '{self.model}' is not installed. Run `ollama pull {self.model}`. "
                f"Installed: {', '.join(sorted(installed)) or 'none'}"
            )

    def observe(self, jpeg: bytes) -> Observation:
        body = {
            "model": self.model,
            "stream": False,
            "format": SCHEMA,
            "options": {"temperature": 0.2},
            "messages": [
                {"role": "user", "content": PROMPT, "images": [base64.b64encode(jpeg).decode()]}
            ],
        }
        try:
            r = requests.post(f"{self.host}/api/chat", json=body, timeout=self.timeout)
            r.raise_for_status()
            content = r.json()["message"]["content"]
        except (requests.RequestException, KeyError, ValueError) as exc:
            raise BackendError(f"{exc.__class__.__name__}: {exc}") from exc
        return parse_observation(content)


class MockBackend:
    """Deterministic stand-in. Output is labelled so a mock journal is never mistaken for a real one."""

    name = "mock"

    def preflight(self) -> None:
        return None

    def observe(self, jpeg: bytes) -> Observation:
        return Observation(
            title="Mock entry",
            description=f"Mock backend: no model looked at this {len(jpeg)}-byte image.",
            terrain="unknown",
            living_things=[],
        )
