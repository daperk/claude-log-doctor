"""Audit logger — every action the doctor takes is appended here as JSONL."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def _stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def write(audit_log_file: Path, action: str, **kwargs) -> None:
    """Append one structured record to the audit log. Never raises."""
    record = {"ts": _stamp(), "action": action, **kwargs}
    line = json.dumps(record, default=str, ensure_ascii=False)
    try:
        audit_log_file.parent.mkdir(parents=True, exist_ok=True)
        with audit_log_file.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception as e:
        print(f"[claude-log-doctor:audit] write failed: {e}")
    print(f"[claude-log-doctor {record['ts']}] {action} {kwargs}")
