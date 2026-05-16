"""Deep Research 可调参数的统一读取层。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

DEFAULT_MAX_REFLECT_ROUNDS = 5
MIN_MAX_REFLECT_ROUNDS = 1
MAX_MAX_REFLECT_ROUNDS = 5

_PHASES = ("plan", "decide", "search", "read", "reflect", "write")

_DEFAULT_PHASE_CONFIG: dict[str, dict[str, object]] = {
    "plan": {
        "temperature": 0.2,
        "max_tokens": 4096,
        "enable_thinking": False,
        "history_limit": 2,
    },
    "decide": {
        "temperature": 0.1,
        "max_tokens": 4096,
        "enable_thinking": False,
        "history_limit": 2,
    },
    "search": {
        "temperature": 0.1,
        "max_tokens": 6144,
        "enable_thinking": False,
        "history_limit": 2,
    },
    "read": {
        "temperature": 0.2,
        "max_tokens": 6144,
        "enable_thinking": False,
        "history_limit": 2,
    },
    "reflect": {
        "temperature": 0.1,
        "max_tokens": 6144,
        "enable_thinking": False,
        "history_limit": 2,
    },
    "write": {
        "temperature": 0.2,
        "max_tokens": 6144,
        "enable_thinking": False,
        "history_limit": 2,
    },
}


@dataclass(frozen=True)
class DRPhaseLLMConfig:
    temperature: float
    max_tokens: int
    enable_thinking: bool
    history_limit: int


def _as_dict(raw: object) -> dict[str, object]:
    if isinstance(raw, Mapping):
        return dict(raw)
    return {}


def _coerce_float(raw: object, default: float) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _coerce_int(raw: object, default: int) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _coerce_bool(raw: object, default: bool) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        token = raw.strip().lower()
        if token in {"true", "1", "yes", "on"}:
            return True
        if token in {"false", "0", "no", "off"}:
            return False
    return default


def _phase_override(runtime_config: Mapping[str, Any], phase: str) -> dict[str, object]:
    dr_cfg = _as_dict(runtime_config.get("dr_config"))
    llm_cfg = _as_dict(dr_cfg.get("llm"))
    phase_cfg = _as_dict(llm_cfg.get(phase))
    return phase_cfg


def resolve_dr_phase_llm_config(
    runtime_config: Mapping[str, Any] | None,
    *,
    phase: str,
) -> DRPhaseLLMConfig:
    cfg = dict(runtime_config or {})
    phase_key = phase if phase in _PHASES else "write"
    default = dict(_DEFAULT_PHASE_CONFIG[phase_key])
    override = _phase_override(cfg, phase_key)

    temperature = _coerce_float(override.get("temperature"), float(default["temperature"]))
    max_tokens = _coerce_int(override.get("max_tokens"), int(default["max_tokens"]))
    history_limit = _coerce_int(override.get("history_limit"), int(default["history_limit"]))
    enable_thinking = _coerce_bool(
        override.get("enable_thinking"),
        bool(default["enable_thinking"]),
    )

    return DRPhaseLLMConfig(
        temperature=temperature,
        max_tokens=max(1, max_tokens),
        enable_thinking=enable_thinking,
        history_limit=max(1, history_limit),
    )


def resolve_dr_max_reflect_rounds(runtime_config: Mapping[str, Any] | None) -> int:
    cfg = dict(runtime_config or {})
    raw = cfg.get("max_reflect_rounds", DEFAULT_MAX_REFLECT_ROUNDS)
    if "max_reflect_rounds" not in cfg:
        dr_cfg = _as_dict(cfg.get("dr_config"))
        raw = dr_cfg.get("max_reflect_rounds", raw)
    rounds = _coerce_int(raw, DEFAULT_MAX_REFLECT_ROUNDS)
    return max(MIN_MAX_REFLECT_ROUNDS, min(MAX_MAX_REFLECT_ROUNDS, rounds))
