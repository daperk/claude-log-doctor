"""Main run loop. One pass = scan + classify + repair + notify."""
from __future__ import annotations

import contextlib
import time
import traceback
from datetime import datetime
from typing import Any

from . import audit, log_scanner, repair
from .classifier import Classifier
from .config import Config
from .notifier import Notifier, make_default_notifier


def _heartbeat(cfg: Config) -> None:
    with contextlib.suppress(Exception):
        cfg.heartbeat_file.write_text(datetime.now().isoformat(), encoding="utf-8")


def run_once(cfg: Config, notifier: Notifier | None = None, max_repairs: int = 10) -> dict[str, Any]:
    """Single pass. Returns summary dict."""
    notifier = notifier or make_default_notifier(cfg)
    summary: dict[str, Any] = {
        "scanned": 0,
        "actionable": 0,
        "applied": 0,
        "pending": 0,
        "errors": 0,
    }

    new_lines = log_scanner.scan_new_lines(cfg)
    summary["scanned"] = len(new_lines)
    if not new_lines:
        _heartbeat(cfg)
        return summary

    classifier = Classifier(cfg)
    events = classifier.classify_block(new_lines)
    actionable = classifier.filter_actionable(events)
    summary["actionable"] = len(actionable)

    applied: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []

    for ev in actionable[:max_repairs]:
        try:
            res = repair.repair_event(cfg, ev)
            status = res.get("status")
            if status == "applied":
                summary["applied"] += 1
                applied.append({"file": res.get("file"), "reason": res.get("summary", "")})
            elif status == "pending":
                summary["pending"] += 1
                pending.append({
                    "id": res["id"],
                    "file": res["file"],
                    "summary": res.get("summary", ""),
                })
                try:
                    notifier.send_approval_request(
                        res["id"], ev["severity"], res["file"],
                        res.get("summary", ""), res.get("diff_preview", ""),
                    )
                except Exception as e:
                    audit.write(cfg.audit_log_file, "notifier_error", err=str(e)[:200])
        except Exception as e:
            summary["errors"] += 1
            audit.write(
                cfg.audit_log_file,
                "repair_exception",
                err=str(e)[:300],
                tb=traceback.format_exc()[-1500:],
            )

    try:
        notifier.send_digest(events, applied, pending)
    except Exception as e:
        audit.write(cfg.audit_log_file, "notifier_digest_error", err=str(e)[:200])

    audit.write(cfg.audit_log_file, "pass_complete", **summary)
    _heartbeat(cfg)
    return summary


def run_forever(cfg: Config, notifier: Notifier | None = None) -> int:
    """Loop forever, one pass every `cfg.interval_min` minutes."""
    if not cfg.enabled:
        print("[claude-log-doctor] disabled via LOG_DOCTOR_ENABLED=false")
        return 0

    notifier = notifier or make_default_notifier(cfg)
    audit.write(
        cfg.audit_log_file,
        "doctor_start",
        interval_min=cfg.interval_min,
        budget=cfg.daily_budget_usd,
        auto_apply=cfg.auto_apply_safe,
        model=cfg.model,
    )

    while True:
        try:
            s = run_once(cfg, notifier=notifier)
            print(f"[claude-log-doctor] pass: {s}")
        except KeyboardInterrupt:
            audit.write(cfg.audit_log_file, "doctor_stop", reason="keyboard_interrupt")
            return 0
        except Exception as e:
            audit.write(
                cfg.audit_log_file,
                "loop_exception",
                err=str(e)[:300],
                tb=traceback.format_exc()[-1500:],
            )

        total = cfg.interval_min * 60
        slept = 0
        while slept < total:
            time.sleep(min(30, total - slept))
            slept += 30
            _heartbeat(cfg)
