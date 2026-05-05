"""Safety rails — what the doctor must NEVER do.

Every fix proposed by Claude is run through `validate_fix()` before any
write. Risk categorization lives here too.

Risk levels:
  SAFE             — typo, missing import, null check, exception handler.
                     Auto-applied if `auto_apply_safe` is on.
  NEEDS_APPROVAL   — function logic change, new conditional. Queued.
  MANUAL_ONLY      — touches a path matching `manual_only_patterns`. Refused.
"""
from __future__ import annotations

from pathlib import Path

from .config import Config


def _norm(rel_path: str) -> str:
    s = rel_path.replace("\\", "/")
    if s.startswith("./"):
        s = s[2:]
    return s.lower()


def is_protected_file(cfg: Config, rel_path: str) -> bool:
    n = _norm(rel_path)
    for protected in cfg.protected_files:
        p = _norm(protected)
        if p.endswith("/"):
            if n.startswith(p):
                return True
        elif n == p:
            return True
    base = Path(n).name
    return bool(base.startswith(".env"))


def is_outside_repo(cfg: Config, rel_path: str) -> bool:
    if ".." in Path(rel_path).parts:
        return True
    try:
        full = (cfg.project_root / rel_path).resolve()
        full.relative_to(cfg.project_root.resolve())
        return False
    except Exception:
        return True


def removes_protected_token(cfg: Config, old_content: str, new_content: str) -> str | None:
    for token in cfg.protected_tokens:
        if token in old_content and token not in new_content:
            return token
    return None


def is_allowed_extension(cfg: Config, rel_path: str) -> bool:
    suffix = Path(rel_path).suffix.lower()
    return suffix in {ext.lower() for ext in cfg.allowed_extensions}


def categorize_fix_risk(cfg: Config, diff_summary: str, rel_path: str) -> str:
    """Return SAFE | NEEDS_APPROVAL | MANUAL_ONLY."""
    n = _norm(rel_path)
    for pattern in cfg.manual_only_patterns:
        p = _norm(pattern)
        if p in n:
            return "MANUAL_ONLY"

    safe_signals = (
        "import ", "is None", "if not ", "try:", "except ",
        "raise ValueError", "return None", " = 0", " = []", " = {}",
    )
    if any(sig in diff_summary for sig in safe_signals) and len(diff_summary) < 1500:
        return "SAFE"
    return "NEEDS_APPROVAL"


def validate_fix(cfg: Config, rel_path: str, old_content: str, new_content: str) -> tuple[bool, str]:
    """Refuse the fix if any guardrail trips. Returns (ok, reason)."""
    if is_outside_repo(cfg, rel_path):
        return False, f"path outside project: {rel_path}"
    if is_protected_file(cfg, rel_path):
        return False, f"protected file: {rel_path}"
    if not is_allowed_extension(cfg, rel_path):
        return False, f"extension not allowed: {rel_path}"
    removed = removes_protected_token(cfg, old_content, new_content)
    if removed:
        return False, f"removes protected token: {removed}"
    if len(new_content) == 0:
        return False, "empty replacement (would delete file)"
    if len(old_content) > 0 and len(new_content) < len(old_content) * (1.0 - cfg.shrink_max_pct):
        return False, f"replacement shrinks file by more than {int(cfg.shrink_max_pct * 100)}%"
    if len(new_content) > max(2000, len(old_content) * cfg.grow_max_factor):
        return False, f"replacement grew >{cfg.grow_max_factor}x (suspicious)"
    return True, "ok"
