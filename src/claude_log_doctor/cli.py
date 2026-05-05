"""Command-line interface for claude-log-doctor.

Commands:
    init                 — write a starter claude-log-doctor.yaml in cwd
    scan                 — single classify+repair pass and exit
    watch                — run forever, scanning every `interval_min`
    approve <id>         — apply a queued NEEDS_APPROVAL fix
    rollback             — restore the most recent applied fix
    status               — show config, today's spend, pending approvals
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from . import budget, repair
from .config import Config
from .loop import run_forever, run_once

_STARTER_YAML = """\
# claude-log-doctor configuration. See default_config.yaml in the package
# for every available key + comments.

log_glob: "logs/*.log"

protected_files:
  # add files the doctor must NEVER edit
  # - "config/secrets.py"

protected_tokens:
  # add substrings that must NEVER be removed
  # - "DEBUG"

manual_only_patterns:
  # add path substrings that should never be auto-fixed
  # - "core/billing/"
"""


def _cfg() -> Config:
    return Config.load()


@click.group()
@click.version_option(package_name="claude-log-doctor")
def main() -> None:
    """Self-healing log watchdog for Python services."""


@main.command()
def init() -> None:
    """Write a starter claude-log-doctor.yaml in the current directory."""
    target = Path.cwd() / "claude-log-doctor.yaml"
    if target.exists():
        click.echo(f"refusing to overwrite existing {target}", err=True)
        sys.exit(1)
    target.write_text(_STARTER_YAML, encoding="utf-8")
    click.echo(f"wrote {target}")


@main.command()
@click.option(
    "--max-repairs",
    default=10,
    show_default=True,
    help="Cap how many ERROR/CRITICAL events get a repair attempt this pass.",
)
def scan(max_repairs: int) -> None:
    """Run a single classify + repair pass and exit."""
    cfg = _cfg()
    summary = run_once(cfg, max_repairs=max_repairs)
    click.echo(json.dumps(summary, indent=2))


@main.command()
def watch() -> None:
    """Run forever — one pass every `interval_min` minutes."""
    cfg = _cfg()
    sys.exit(run_forever(cfg))


@main.command()
@click.argument("approval_id")
def approve(approval_id: str) -> None:
    """Apply a queued NEEDS_APPROVAL fix by id."""
    cfg = _cfg()
    result = repair.apply_pending(cfg, approval_id)
    click.echo(json.dumps(result, indent=2, default=str))
    if result.get("status") not in ("applied",):
        sys.exit(1)


@main.command()
def rollback() -> None:
    """Restore the most recent applied fix from its backup."""
    cfg = _cfg()
    result = repair.rollback_last(cfg)
    click.echo(json.dumps(result, indent=2, default=str))
    if result.get("status") not in ("rolled_back",):
        sys.exit(1)


@main.command()
def status() -> None:
    """Show effective config + today's spend + pending approvals count."""
    cfg = _cfg()
    pending_count = 0
    if cfg.pending_approvals_file.exists():
        try:
            pending_count = len(json.loads(cfg.pending_approvals_file.read_text(encoding="utf-8")))
        except Exception:
            pending_count = -1
    info = {
        "project_root": str(cfg.project_root),
        "state_dir": str(cfg.state_dir),
        "log_glob": cfg.log_glob,
        "model": cfg.model,
        "enabled": cfg.enabled,
        "auto_apply_safe": cfg.auto_apply_safe,
        "interval_min": cfg.interval_min,
        "daily_budget_usd": cfg.daily_budget_usd,
        "spent_today_usd": round(budget.spent_today(cfg), 4),
        "remaining_today_usd": round(budget.remaining(cfg), 4),
        "rules_file": str(cfg.rules_file),
        "protected_files": cfg.protected_files,
        "protected_tokens": cfg.protected_tokens,
        "manual_only_patterns": cfg.manual_only_patterns,
        "pending_approvals": pending_count,
        "anthropic_key_set": bool(cfg.anthropic_key),
    }
    click.echo(json.dumps(info, indent=2, default=str))


if __name__ == "__main__":
    main()
