"""Configuration loader.

Resolution order (highest priority wins):
  1. Environment variables
  2. User YAML at project root: claude-log-doctor.yaml or .claude-log-doctor.yaml
  3. Package defaults: default_config.yaml
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = PACKAGE_DIR / "default_config.yaml"
DEFAULT_RULES_PATH = PACKAGE_DIR / "default_rules.json"


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top-level YAML must be a mapping")
    return data


def _find_user_config(project_root: Path) -> Path | None:
    for name in ("claude-log-doctor.yaml", ".claude-log-doctor.yaml", "claude-log-doctor.yml"):
        candidate = project_root / name
        if candidate.exists():
            return candidate
    return None


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass
class Pricing:
    input_per_token: float = 15.0 / 1_000_000
    output_per_token: float = 75.0 / 1_000_000


@dataclass
class Config:
    """Runtime configuration. Build via `Config.load(project_root)`."""

    project_root: Path
    state_dir: Path

    # Logs
    log_glob: str = "logs/*.log"
    log_tail_lines: int = 5000

    # Safety
    protected_files: list[str] = field(default_factory=list)
    protected_tokens: list[str] = field(default_factory=list)
    allowed_extensions: list[str] = field(default_factory=lambda: [".py", ".json", ".yaml", ".yml", ".toml"])
    shrink_max_pct: float = 0.40
    grow_max_factor: int = 5
    manual_only_patterns: list[str] = field(default_factory=list)

    # Behavior
    enabled: bool = True
    interval_min: int = 15
    daily_budget_usd: float = 0.50
    auto_apply_safe: bool = True
    max_fix_attempts_per_error: int = 2
    max_tokens_per_call: int = 4000
    thinking_budget_tokens: int = 5000
    context_span_lines: int = 30

    # Anthropic
    anthropic_key: str = ""
    model: str = "claude-opus-4-7"
    pricing: Pricing = field(default_factory=Pricing)

    # Rules file (resolved path)
    rules_file: Path = DEFAULT_RULES_PATH

    # Notifier creds (optional)
    telegram_token: str = ""
    telegram_chat: str = ""
    slack_webhook_url: str = ""

    # ------------------------------------------------------------------
    # Loaders / paths
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, project_root: Path | None = None) -> Config:
        root = (project_root or Path.cwd()).resolve()
        defaults = _load_yaml(DEFAULT_CONFIG_PATH)
        user_path = _find_user_config(root)
        user = _load_yaml(user_path) if user_path else {}
        merged: dict[str, Any] = {**defaults, **user}

        state_dir = root / ".log-doctor" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)

        rules_value = merged.get("rules_file")
        rules_file = (root / rules_value).resolve() if rules_value else DEFAULT_RULES_PATH

        pricing_data = merged.get("pricing", {}) or {}
        pricing = Pricing(
            input_per_token=float(pricing_data.get("input_per_token", Pricing.input_per_token)),
            output_per_token=float(pricing_data.get("output_per_token", Pricing.output_per_token)),
        )

        return cls(
            project_root=root,
            state_dir=state_dir,
            log_glob=str(merged.get("log_glob", "logs/*.log")),
            log_tail_lines=int(merged.get("log_tail_lines", 5000)),
            protected_files=list(merged.get("protected_files", []) or []),
            protected_tokens=list(merged.get("protected_tokens", []) or []),
            allowed_extensions=list(merged.get("allowed_extensions", [".py", ".json", ".yaml", ".yml", ".toml"])),
            shrink_max_pct=float(merged.get("shrink_max_pct", 0.40)),
            grow_max_factor=int(merged.get("grow_max_factor", 5)),
            manual_only_patterns=list(merged.get("manual_only_patterns", []) or []),
            enabled=_env_bool("LOG_DOCTOR_ENABLED", True),
            interval_min=_env_int("LOG_DOCTOR_INTERVAL_MIN", 15),
            daily_budget_usd=_env_float("LOG_DOCTOR_DAILY_BUDGET_USD", 0.50),
            auto_apply_safe=_env_bool("LOG_DOCTOR_AUTO_APPLY_SAFE", True),
            max_fix_attempts_per_error=int(merged.get("max_fix_attempts_per_error", 2)),
            max_tokens_per_call=int(merged.get("max_tokens_per_call", 4000)),
            thinking_budget_tokens=int(merged.get("thinking_budget_tokens", 5000)),
            context_span_lines=int(merged.get("context_span_lines", 30)),
            anthropic_key=os.getenv("ANTHROPIC_API_KEY", ""),
            model=os.getenv("LOG_DOCTOR_MODEL", "claude-opus-4-7"),
            pricing=pricing,
            rules_file=rules_file,
            telegram_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            telegram_chat=os.getenv("TELEGRAM_CHAT_ID", ""),
            slack_webhook_url=os.getenv("SLACK_WEBHOOK_URL", ""),
        )

    # ------------------------------------------------------------------
    # Convenience paths under state_dir
    # ------------------------------------------------------------------

    @property
    def scan_state_file(self) -> Path:
        return self.state_dir / "scan_state.json"

    @property
    def budget_file(self) -> Path:
        return self.state_dir / "daily_budget.json"

    @property
    def audit_log_file(self) -> Path:
        return self.state_dir / "audit.log"

    @property
    def applied_fixes_file(self) -> Path:
        return self.state_dir / "applied_fixes.json"

    @property
    def pending_approvals_file(self) -> Path:
        return self.state_dir / "pending_approvals.json"

    @property
    def backups_dir(self) -> Path:
        d = self.state_dir / "backups"
        d.mkdir(exist_ok=True)
        return d

    @property
    def heartbeat_file(self) -> Path:
        return self.state_dir / "heartbeat.txt"
