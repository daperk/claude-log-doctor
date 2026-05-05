"""Shared pytest fixtures."""
from __future__ import annotations

from pathlib import Path

import pytest

from claude_log_doctor.config import Config


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """A fresh project root with a logs/ directory."""
    (tmp_path / "logs").mkdir()
    return tmp_path


@pytest.fixture
def cfg(tmp_project: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    """A Config rooted at tmp_project with no env-var leakage."""
    for key in (
        "ANTHROPIC_API_KEY",
        "LOG_DOCTOR_ENABLED",
        "LOG_DOCTOR_INTERVAL_MIN",
        "LOG_DOCTOR_DAILY_BUDGET_USD",
        "LOG_DOCTOR_AUTO_APPLY_SAFE",
        "LOG_DOCTOR_MODEL",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "SLACK_WEBHOOK_URL",
    ):
        monkeypatch.delenv(key, raising=False)
    return Config.load(tmp_project)
