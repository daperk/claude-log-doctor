"""Incremental log scanner.

Reads only the new bytes from the most-recent log matching `log_glob`
(tracked in `state/scan_state.json`). Detects rotation and truncation.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import audit
from .config import Config


def find_latest_log(cfg: Config) -> Path | None:
    """Resolve `log_glob` (relative to project_root) and return the newest match."""
    glob = cfg.log_glob
    if Path(glob).is_absolute():
        candidates = list(Path("/").glob(glob.lstrip("/")))
    else:
        candidates = list(cfg.project_root.glob(glob))
    candidates = [p for p in candidates if p.is_file()]
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def _load_state(cfg: Config) -> dict[str, Any]:
    if cfg.scan_state_file.exists():
        try:
            return json.loads(cfg.scan_state_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"file": None, "offset": 0}


def _save_state(cfg: Config, state: dict[str, Any]) -> None:
    cfg.scan_state_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.scan_state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")


def scan_new_lines(cfg: Config) -> list[str]:
    """Return new lines since last scan. Updates state. Caps to log_tail_lines."""
    log_path = find_latest_log(cfg)
    if log_path is None:
        audit.write(cfg.audit_log_file, "scan_no_log_file", glob=cfg.log_glob)
        return []

    state = _load_state(cfg)
    last_file = state.get("file")
    last_offset = int(state.get("offset", 0) or 0)

    if last_file != str(log_path):
        last_offset = 0  # rotation: start fresh on the new file

    try:
        size = log_path.stat().st_size
    except OSError:
        return []

    if last_offset > size:
        last_offset = 0  # truncated under the same name
    if last_offset >= size:
        _save_state(cfg, {"file": str(log_path), "offset": size})
        return []

    new_lines: list[str] = []
    try:
        with log_path.open("r", encoding="utf-8", errors="replace") as fh:
            fh.seek(last_offset)
            chunk = fh.read()
            new_offset = fh.tell()
        new_lines = [ln for ln in chunk.splitlines() if ln.strip()]
        if len(new_lines) > cfg.log_tail_lines:
            new_lines = new_lines[-cfg.log_tail_lines :]
    except Exception as e:
        audit.write(cfg.audit_log_file, "scan_read_error", error=str(e), file=str(log_path))
        return []

    _save_state(cfg, {"file": str(log_path), "offset": new_offset})
    audit.write(
        cfg.audit_log_file,
        "scan_complete",
        file=log_path.name,
        new_lines=len(new_lines),
        offset=new_offset,
    )
    return new_lines
