"""Notification channels for digest summaries and approval requests.

Default notifier writes to stdout. Telegram and Slack ship as optional
extras (`pip install claude-log-doctor[telegram]` / `[slack]`). To add
your own channel, subclass `Notifier` and pass an instance into the loop.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .config import Config


class Notifier(ABC):
    @abstractmethod
    def send_digest(
        self,
        events: list[dict[str, Any]],
        applied: list[dict[str, Any]],
        pending: list[dict[str, Any]],
    ) -> None: ...

    @abstractmethod
    def send_approval_request(
        self, approval_id: str, severity: str, file: str, summary: str, diff_preview: str
    ) -> None: ...


class ConsoleNotifier(Notifier):
    """Default — prints structured digests to stdout."""

    def send_digest(self, events, applied, pending):
        if not events and not applied and not pending:
            return
        print("\n" + "=" * 60)
        print("[claude-log-doctor] DIGEST")
        print("=" * 60)
        if events:
            print(f"  Events classified: {len(events)}")
            for ev in events[:10]:
                print(f"    [{ev['severity']:>8}] {ev['summary']}")
        if applied:
            print(f"\n  Applied fixes: {len(applied)}")
            for fix in applied:
                print(f"    + {fix.get('file')}: {fix.get('reason', '')}")
        if pending:
            print(f"\n  Pending approvals: {len(pending)}")
            for p in pending:
                print(f"    ? [{p['id']}] {p.get('file')}: {p.get('summary', '')}")
        print("=" * 60)

    def send_approval_request(self, approval_id, severity, file, summary, diff_preview):
        print("\n" + "-" * 60)
        print(f"[claude-log-doctor] APPROVAL REQUEST id={approval_id} severity={severity}")
        print(f"file: {file}")
        print(f"summary: {summary}")
        print(diff_preview[:1500])
        print(f"To apply: claude-log-doctor approve {approval_id}")
        print("-" * 60)


class TelegramNotifier(Notifier):
    """Sends digests + approval requests via the Telegram Bot API."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.token = cfg.telegram_token
        self.chat_id = cfg.telegram_chat
        self._console = ConsoleNotifier()
        if not (self.token and self.chat_id):
            raise ValueError("TelegramNotifier requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")

    def _post(self, text: str) -> None:
        try:
            import requests
        except ImportError as e:
            raise RuntimeError("Install with `pip install claude-log-doctor[telegram]`") from e
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            requests.post(
                url,
                json={"chat_id": self.chat_id, "text": text[:4000], "parse_mode": "Markdown"},
                timeout=10,
            )
        except Exception as e:
            print(f"[telegram] post failed: {e}")

    def send_digest(self, events, applied, pending):
        self._console.send_digest(events, applied, pending)
        if not events and not applied and not pending:
            return
        lines = ["*claude-log-doctor digest*"]
        if events:
            lines.append(f"events: {len(events)}")
        if applied:
            lines.append(f"applied: {len(applied)}")
            for fix in applied[:5]:
                lines.append(f"  + `{fix.get('file')}`")
        if pending:
            lines.append(f"pending: {len(pending)}")
            for p in pending[:5]:
                lines.append(f"  ? `{p['id']}` `{p.get('file')}`")
        self._post("\n".join(lines))

    def send_approval_request(self, approval_id, severity, file, summary, diff_preview):
        self._console.send_approval_request(approval_id, severity, file, summary, diff_preview)
        msg = (
            f"*Needs approval* `{approval_id}` ({severity})\n"
            f"`{file}`\n{summary}\n\n```\n{diff_preview[:1200]}\n```\n"
            f"Run: `claude-log-doctor approve {approval_id}`"
        )
        self._post(msg)


class SlackNotifier(Notifier):
    """Sends digests + approval requests via a Slack incoming webhook."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.webhook_url = cfg.slack_webhook_url
        self._console = ConsoleNotifier()
        if not self.webhook_url:
            raise ValueError("SlackNotifier requires SLACK_WEBHOOK_URL")

    def _post(self, text: str) -> None:
        try:
            import requests
        except ImportError as e:
            raise RuntimeError("Install with `pip install claude-log-doctor[slack]`") from e
        try:
            requests.post(self.webhook_url, json={"text": text[:3500]}, timeout=10)
        except Exception as e:
            print(f"[slack] post failed: {e}")

    def send_digest(self, events, applied, pending):
        self._console.send_digest(events, applied, pending)
        if not events and not applied and not pending:
            return
        lines = ["*claude-log-doctor digest*"]
        if events:
            lines.append(f"events: {len(events)}")
        if applied:
            lines.append(f"applied: {len(applied)}")
        if pending:
            lines.append(f"pending: {len(pending)}")
        self._post("\n".join(lines))

    def send_approval_request(self, approval_id, severity, file, summary, diff_preview):
        self._console.send_approval_request(approval_id, severity, file, summary, diff_preview)
        msg = (
            f"*Needs approval* `{approval_id}` ({severity})\n"
            f"`{file}` — {summary}\n```\n{diff_preview[:1200]}\n```"
        )
        self._post(msg)


def make_default_notifier(cfg: Config) -> Notifier:
    """Pick the best notifier based on what creds are configured."""
    if cfg.slack_webhook_url:
        try:
            return SlackNotifier(cfg)
        except Exception:
            pass
    if cfg.telegram_token and cfg.telegram_chat:
        try:
            return TelegramNotifier(cfg)
        except Exception:
            pass
    return ConsoleNotifier()
