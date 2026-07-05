"""Configuration loading.

A thin, dependency-light wrapper over the YAML file. We deliberately keep this
as nested dicts with dotted-path access rather than a rigid schema so new
tunables can be added in one place (config.yaml) without touching code.
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml


class Config:
    """Dotted-path access over a nested config dict.

    >>> cfg = Config({"a": {"b": 1}})
    >>> cfg.get("a.b")
    1
    >>> cfg.get("a.missing", 42)
    42
    """

    def __init__(self, data: dict[str, Any]):
        self._data = data

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        with open(path, "r", encoding="utf-8") as f:
            return cls(yaml.safe_load(f) or {})

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def section(self, dotted: str) -> "Config":
        return Config(copy.deepcopy(self.get(dotted, {}) or {}))

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def as_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self._data)
