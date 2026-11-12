"""Deterministic, data-driven tool failures (see faults.json).

A rule matches when every `match` field re-searches (case-insensitive) the stringified request value;
list values are joined with ",". Delays add up; the first `empty`/`error` wins. `times` budgets are per
(rule, conversation) and only consumed by matching calls.
"""
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass
class Effect:
    kind: Literal["empty", "error"] | None = None
    delay_ms: int = 0
    status: int = 0
    code: str = ""
    retryable: bool = False


def _as_text(value) -> str:
    return ",".join(map(str, value)) if isinstance(value, list) else str(value)


class Faults:
    def __init__(self, rules: list[dict]):
        self.rules = rules
        self._used: dict[tuple[int, str], int] = {}

    @classmethod
    def load(cls, path: Path | None) -> "Faults":
        if path is None or not Path(path).is_file():
            return cls([])
        return cls(json.loads(Path(path).read_text()).get("rules", []))

    def _matches(self, rule: dict, tool: str, fields: dict) -> bool:
        if rule.get("tool") != tool:
            return False
        for field, pattern in (rule.get("match") or {}).items():
            if field not in fields or not re.search(pattern, _as_text(fields[field]), re.IGNORECASE):
                return False
        return True

    def check(self, tool: str, fields: dict, conversation_id: str) -> Effect:
        out = Effect()
        for i, rule in enumerate(self.rules):
            if not self._matches(rule, tool, fields):
                continue
            key = (i, conversation_id)
            if "times" in rule and self._used.get(key, 0) >= rule["times"]:
                continue
            self._used[key] = self._used.get(key, 0) + 1
            effect = rule["effect"]
            if effect == "empty":
                out.kind = out.kind or "empty"
            elif "delay_ms" in effect:
                out.delay_ms += int(effect["delay_ms"])
            elif "error" in effect and out.kind is None:
                err = effect["error"]
                out.kind, out.status, out.code = "error", int(err["status"]), err["code"]
                out.retryable = bool(err.get("retryable", False))
        return out

    def reset(self) -> None:
        self._used.clear()
