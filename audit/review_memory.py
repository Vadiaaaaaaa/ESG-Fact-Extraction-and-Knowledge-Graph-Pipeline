from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_HERE = _Path(__file__).resolve().parent
_ROOT = _HERE.parent
for _p in [str(_ROOT / 'pipeline'), str(_ROOT / 'registry'), str(_HERE)]:
    if _p not in _sys.path:
        _sys.path.insert(0, _p)


import json
import re
from pathlib import Path
from typing import Any


DEFAULT_REVIEW_MEMORY_PATH = _Path(__file__).resolve().parent / "review_memory.json"
REVIEW_MEMORY_VERSION = "review_memory_v1"
GENERIC_SINGLE_WORD_METRIC_CORES = {
    "countries",
    "stores",
    "employees",
    "locations",
    "share",
    "rate",
    "count",
    "facilities",
    "markets",
    "sites",
    "units",
    "growth",
}


def normalize_review_key(value: Any) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())
    return " ".join(text.split())


def _is_generic_memory_key(value: Any) -> bool:
    key = normalize_review_key(value)
    return key in GENERIC_SINGLE_WORD_METRIC_CORES


def decision_keys(raw_name: str = "", metric_core: str = "", canonical_id: str = "") -> list[str]:
    keys: list[str] = []
    raw_key = normalize_review_key(raw_name)
    core_key = normalize_review_key(metric_core)
    qualified_key = normalize_review_key(canonical_id)
    if qualified_key and raw_key and not _is_generic_memory_key(raw_key):
        keys.append(f"qualified:{qualified_key}:raw_name:{raw_key}")
    if qualified_key and core_key and not _is_generic_memory_key(core_key):
        keys.append(f"qualified:{qualified_key}:metric_core:{core_key}")
    if raw_key and not _is_generic_memory_key(raw_key):
        keys.append(f"raw_name:{raw_key}")
    if core_key and not _is_generic_memory_key(core_key):
        keys.append(f"metric_core:{core_key}")
    return keys


def load_review_memory(path: str | Path | None = None) -> dict[str, Any]:
    memory_path = Path(path) if path else DEFAULT_REVIEW_MEMORY_PATH
    if not memory_path.exists():
        return {"version": REVIEW_MEMORY_VERSION, "decisions": {}}
    with memory_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        return {"version": REVIEW_MEMORY_VERSION, "decisions": {}}
    payload.setdefault("version", REVIEW_MEMORY_VERSION)
    payload.setdefault("decisions", {})
    return payload


def lookup_review_decision(
    memory: dict[str, Any],
    *,
    raw_name: str = "",
    metric_core: str = "",
) -> dict[str, Any] | None:
    decisions = memory.get("decisions") or {}
    for key in decision_keys(raw_name=raw_name, metric_core=metric_core):
        decision = decisions.get(key)
        if isinstance(decision, dict):
            return decision
    return None
