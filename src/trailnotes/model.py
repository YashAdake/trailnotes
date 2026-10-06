"""Vision backends. Ollama is the real one; Mock exists so the pipeline is testable without a GPU."""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from typing import Protocol

import requests

PROMPT = """You are helping write a field journal entry for one photo taken on a walk.
Describe only what is visible in the frame. Do not guess where it was taken.
- title: 2 to 6 words.
- description: 1 to 3 sentences about what is in the frame.
- terrain: 2 to 4 words describing the ground or setting you can actually see (for
  example "wetland edge", "red carpet", "indoor"), never a sentence. Do not default to "paved path".
- living_things: look at the whole frame first and list every plant, tree, flower, fungus
  or animal you can clearly see, including ones in the background. Non-living things are
  never listed: no water, mist, sky, light, rocks, buildings, food, people or signs. If
  none are visible, return an empty list. Use "high" only when distinctive features are
  clearly visible; if you are unsure, use "low". List each thing once.
  Do not put confidence notes or "no living things" remarks in the description.
Reply with JSON only."""

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "maxLength": 80},
        # Listed before the prose on purpose: a small model that writes the description
        # first tends to leave this list empty even when its own text mentions plants.
        "living_things": {
            "type": "array",
            "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "maxLength": 40},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                },
                "required": ["name", "confidence"],
            },
        },
        "terrain": {"type": "string", "maxLength": 60},
        "description": {"type": "string", "maxLength": 600},
    },
    "required": ["title", "living_things", "terrain", "description"],
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
    text = str(value).strip() if value is not None else ""
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


_LEAKED_CONFIDENCE = re.compile(r"\s*\((?:confidence|certainty)[^)]*\)", re.I)


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
    description = _LEAKED_CONFIDENCE.sub("", _clip(data.get("description"), 1200))
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
        # num_predict is a backstop: the schema bounds the output, but a runaway
        # response must still end. 8 items + prose fits well inside 700 tokens.
        body = {
            "model": self.model,
            "stream": False,
            "format": SCHEMA,
            "options": {"temperature": 0.2, "num_predict": 700, "repeat_penalty": 1.1},
            "messages": [
                {"role": "user", "content": PROMPT, "images": [base64.b64encode(jpeg).decode()]}
            ],
        }
        last: ValueError | None = None
        for attempt in range(2):
            if attempt:
                body["options"]["temperature"] = 0.5  # a different sample, not a repeat of the loop
            try:
                r = requests.post(f"{self.host}/api/chat", json=body, timeout=self.timeout)
                r.raise_for_status()
                content = r.json()["message"]["content"]
            except (requests.RequestException, KeyError, ValueError) as exc:
                raise BackendError(f"{exc.__class__.__name__}: {exc}") from exc
            try:
                return parse_observation(content)
            except ValueError as exc:  # unusable output: retry once, then report it
                last = exc
        raise ValueError(f"model output unusable after 2 attempts: {last}")


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
