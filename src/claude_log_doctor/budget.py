"""Daily-budget tracker for Anthropic API spend.

Tracks input/output tokens per call, enforces a daily USD cap, and keeps a
rolling 14-day history under the configured state directory.
"""
from __future__ import annotations

import json
from datetime import date

from .config import Config


def _today_key() -> str:
    return date.today().isoformat()


def _load(cfg: Config) -> dict[str, float]:
    if cfg.budget_file.exists():
        try:
            return json.loads(cfg.budget_file.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save(cfg: Config, data: dict[str, float]) -> None:
    cfg.budget_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.budget_file.write_text(json.dumps(data, indent=2), encoding="utf-8")


def spent_today(cfg: Config) -> float:
    return float(_load(cfg).get(_today_key(), 0.0))


def remaining(cfg: Config) -> float:
    return max(0.0, cfg.daily_budget_usd - spent_today(cfg))


def can_spend(cfg: Config, estimated_cost: float = 0.20) -> bool:
    return remaining(cfg) >= estimated_cost


def record_usage(cfg: Config, input_tokens: int, output_tokens: int) -> float:
    """Record token usage. Returns the dollar cost added."""
    cost = (
        input_tokens * cfg.pricing.input_per_token
        + output_tokens * cfg.pricing.output_per_token
    )
    data = _load(cfg)
    key = _today_key()
    data[key] = round(float(data.get(key, 0.0)) + cost, 6)
    keys = sorted(data.keys())
    while len(keys) > 14:
        data.pop(keys.pop(0))
    _save(cfg, data)
    return cost
