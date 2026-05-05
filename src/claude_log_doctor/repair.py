"""Auto-repair: ask Claude to propose a minimal fix, validate it, apply or queue.

The Claude prompt asks for a strict JSON response with exact-match search/replace.
If the `search` text is missing or appears multiple times in the target file,
the doctor refuses to apply and queues for manual review.
"""
from __future__ import annotations

import json
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from . import audit, budget, safety
from .config import Config

_TRACEBACK_FILE_RE = re.compile(r'File "([^"]+)", line (\d+)')

_RISK_ORDER = {"SAFE": 0, "NEEDS_APPROVAL": 1, "MANUAL_ONLY": 2}


def extract_file_hint(cfg: Config, event: dict[str, Any]) -> tuple[str, int] | None:
    """From a traceback event, find the deepest in-project file:line."""
    repo = cfg.project_root.resolve()
    last_match: tuple[str, int] | None = None
    for line in event.get("lines", []):
        m = _TRACEBACK_FILE_RE.search(line)
        if not m:
            continue
        path_str, lineno = m.group(1), int(m.group(2))
        try:
            p = Path(path_str).resolve()
            rel = p.relative_to(repo)
            last_match = (str(rel).replace("\\", "/"), lineno)
        except (ValueError, OSError):
            continue
    return last_match


def read_context(cfg: Config, rel_path: str, lineno: int) -> str:
    full = cfg.project_root / rel_path
    try:
        text = full.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return ""
    span = cfg.context_span_lines
    lo = max(0, lineno - span)
    hi = min(len(text), lineno + span)
    return "\n".join(f"{i + 1:>5}: {text[i]}" for i in range(lo, hi))


def _build_prompt(
    cfg: Config,
    event: dict[str, Any],
    file_hint: tuple[str, int] | None,
    context_snippet: str,
) -> str:
    error_block = "\n".join(event.get("lines", []))[:3000]
    file_part = ""
    if file_hint:
        file_part = (
            f"\nLikely file: {file_hint[0]} (around line {file_hint[1]})\n"
            f"--- code context ---\n{context_snippet}\n--- end ---\n"
        )
    protected_files_str = ", ".join(cfg.protected_files) or "(none)"
    protected_tokens_str = ", ".join(cfg.protected_tokens) or "(none)"
    manual_patterns_str = ", ".join(cfg.manual_only_patterns) or "(none)"
    return f"""You are an autonomous code-repair assistant for a Python application.
Your task: analyze a runtime error and propose a MINIMAL, SAFE fix.

ERROR / LOG EVENT (severity={event.get('severity')}, tag={event.get('tag')}):
{error_block}
{file_part}

CONSTRAINTS — set needs_fix=false if any apply:
  * The fix would touch files matching: {manual_patterns_str}
  * The fix would touch protected files: {protected_files_str}
  * The fix would remove protected tokens: {protected_tokens_str}
  * The cause is environmental (network down, rate limit, external service).
  * The cause is data-driven (bad input from upstream system).
  * You are unsure of the root cause.

If a SAFE fix exists (typo, missing import, null check, broad except,
log-message correction, JSON serialization fix, type coercion), respond
with EXACT search/replace text. The 'search' string MUST appear verbatim
in the target file (including indentation), and MUST be unambiguous
(it must appear exactly once).

Respond with ONE valid JSON object only — no prose, no markdown fences:
{{
  "needs_fix": true|false,
  "file": "<project-relative path or null>",
  "search": "<verbatim text from file or null>",
  "replace": "<replacement text or null>",
  "explanation": "<one short sentence>",
  "risk": "SAFE" | "NEEDS_APPROVAL" | "MANUAL_ONLY"
}}
"""


def _call_claude(cfg: Config, prompt: str) -> dict[str, Any] | None:
    if not cfg.anthropic_key:
        audit.write(cfg.audit_log_file, "repair_no_api_key")
        return None
    if not budget.can_spend(cfg, 0.20):
        audit.write(
            cfg.audit_log_file,
            "repair_budget_exhausted",
            spent=budget.spent_today(cfg),
            budget=cfg.daily_budget_usd,
        )
        return None
    try:
        import anthropic
    except ImportError:
        audit.write(cfg.audit_log_file, "repair_no_anthropic_sdk")
        return None
    try:
        client = anthropic.Anthropic(api_key=cfg.anthropic_key)
        kwargs: dict[str, Any] = {
            "model": cfg.model,
            "max_tokens": cfg.max_tokens_per_call + max(0, cfg.thinking_budget_tokens),
            "messages": [{"role": "user", "content": prompt}],
        }
        if cfg.thinking_budget_tokens > 0:
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": cfg.thinking_budget_tokens}
        resp = client.messages.create(**kwargs)
        text = "".join(
            b.text for b in resp.content
            if hasattr(b, "text") and getattr(b, "type", "") == "text"
        )
        usage = getattr(resp, "usage", None)
        in_tok = getattr(usage, "input_tokens", 0) if usage else 0
        out_tok = getattr(usage, "output_tokens", 0) if usage else 0
        cost = budget.record_usage(cfg, in_tok, out_tok)
        audit.write(
            cfg.audit_log_file,
            "repair_claude_call",
            model=cfg.model,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=round(cost, 4),
        )
        return _extract_json(text)
    except Exception as e:
        audit.write(cfg.audit_log_file, "repair_claude_error", error=str(e)[:300])
        return None


def _extract_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    a, b = text.find("{"), text.rfind("}")
    if a == -1 or b == -1 or b <= a:
        return None
    try:
        return json.loads(text[a : b + 1])
    except Exception:
        return None


def _backup_file(cfg: Config, rel_path: str) -> Path:
    src = cfg.project_root / rel_path
    bp = cfg.backups_dir / f"{Path(rel_path).name}.{uuid.uuid4().hex[:8]}.bak"
    shutil.copy2(src, bp)
    return bp


def _apply_search_replace(
    cfg: Config, rel_path: str, search: str, replace: str
) -> tuple[bool, str, str | None, str | None]:
    full = cfg.project_root / rel_path
    if not full.exists():
        return False, f"file not found: {rel_path}", None, None
    try:
        old = full.read_text(encoding="utf-8")
    except Exception as e:
        return False, f"read failed: {e}", None, None

    n = old.count(search)
    if n == 0:
        return False, "search text not found verbatim", old, None
    if n > 1:
        return False, f"search text matched {n} times (ambiguous)", old, None

    new = old.replace(search, replace, 1)
    ok, reason = safety.validate_fix(cfg, rel_path, old, new)
    if not ok:
        return False, f"safety_rail: {reason}", old, new

    try:
        full.write_text(new, encoding="utf-8")
    except Exception as e:
        return False, f"write failed: {e}", old, new
    return True, "applied", old, new


def _load_pending(cfg: Config) -> list[dict[str, Any]]:
    if cfg.pending_approvals_file.exists():
        try:
            return json.loads(cfg.pending_approvals_file.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _save_pending(cfg: Config, items: list[dict[str, Any]]) -> None:
    cfg.pending_approvals_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.pending_approvals_file.write_text(json.dumps(items, indent=2, default=str), encoding="utf-8")


def _record_applied(cfg: Config, rec: dict[str, Any]) -> None:
    items: list[dict[str, Any]] = []
    if cfg.applied_fixes_file.exists():
        try:
            items = json.loads(cfg.applied_fixes_file.read_text(encoding="utf-8"))
        except Exception:
            items = []
    items.append(rec)
    items = items[-200:]
    cfg.applied_fixes_file.write_text(json.dumps(items, indent=2, default=str), encoding="utf-8")


def repair_event(cfg: Config, event: dict[str, Any]) -> dict[str, Any]:
    """Top-level: classify, propose, validate, apply or queue. Never raises."""
    file_hint = extract_file_hint(cfg, event)
    context = read_context(cfg, file_hint[0], file_hint[1]) if file_hint else ""
    prompt = _build_prompt(cfg, event, file_hint, context)

    proposal = _call_claude(cfg, prompt)
    if not proposal:
        return {"status": "no_proposal", "event_summary": event["summary"]}

    if not proposal.get("needs_fix"):
        audit.write(cfg.audit_log_file, "repair_no_fix_needed", reason=proposal.get("explanation", "")[:120])
        return {
            "status": "skipped",
            "reason": proposal.get("explanation", ""),
            "event_summary": event["summary"],
        }

    rel_path = (proposal.get("file") or "").replace("\\", "/").lstrip("./")
    search = proposal.get("search") or ""
    replace = proposal.get("replace") or ""
    risk = (proposal.get("risk") or "NEEDS_APPROVAL").upper()
    explanation = proposal.get("explanation", "")[:300]

    if not rel_path or not search:
        return {"status": "invalid_proposal", "event_summary": event["summary"]}
    if not (cfg.project_root / rel_path).exists():
        return {"status": "invalid_path", "file": rel_path}

    diff_preview = f"--- {rel_path}\n- {search[:600]}\n+ {replace[:600]}"
    rails_risk = safety.categorize_fix_risk(cfg, diff_preview, rel_path)
    final_risk = max([risk, rails_risk], key=lambda r: _RISK_ORDER.get(r, 1))

    if final_risk == "MANUAL_ONLY":
        audit.write(cfg.audit_log_file, "repair_manual_only", file=rel_path, reason=explanation)
        return {
            "status": "manual_only",
            "file": rel_path,
            "summary": explanation,
            "diff_preview": diff_preview,
        }

    if final_risk == "SAFE" and cfg.auto_apply_safe:
        backup = _backup_file(cfg, rel_path)
        ok, reason, _, _ = _apply_search_replace(cfg, rel_path, search, replace)
        rec = {
            "ts_event": event["summary"],
            "file": rel_path,
            "explanation": explanation,
            "ok": ok,
            "reason": reason,
            "backup": str(backup),
        }
        _record_applied(cfg, rec)
        audit.write(cfg.audit_log_file, "repair_apply_safe", **rec)
        if not ok:
            return {"status": "apply_failed", "reason": reason, "file": rel_path, "summary": explanation}
        return {
            "status": "applied",
            "file": rel_path,
            "summary": explanation,
            "backup": str(backup),
            "diff_preview": diff_preview,
        }

    approval_id = uuid.uuid4().hex[:8]
    pending = _load_pending(cfg)
    pending.append({
        "id": approval_id,
        "file": rel_path,
        "search": search,
        "replace": replace,
        "summary": explanation,
        "risk": final_risk,
        "event_summary": event["summary"],
    })
    _save_pending(cfg, pending)
    audit.write(cfg.audit_log_file, "repair_pending", id=approval_id, file=rel_path, risk=final_risk)
    return {
        "status": "pending",
        "id": approval_id,
        "file": rel_path,
        "summary": explanation,
        "diff_preview": diff_preview,
        "risk": final_risk,
    }


def apply_pending(cfg: Config, approval_id: str) -> dict[str, Any]:
    """Manually apply a previously queued fix by id."""
    pending = _load_pending(cfg)
    target = next((p for p in pending if p["id"] == approval_id), None)
    if not target:
        return {"status": "not_found"}
    backup = _backup_file(cfg, target["file"])
    ok, reason, _, _ = _apply_search_replace(cfg, target["file"], target["search"], target["replace"])
    pending = [p for p in pending if p["id"] != approval_id]
    _save_pending(cfg, pending)
    rec = {
        "file": target["file"],
        "ok": ok,
        "reason": reason,
        "explanation": target.get("summary"),
        "backup": str(backup),
        "manual_apply_id": approval_id,
    }
    _record_applied(cfg, rec)
    audit.write(cfg.audit_log_file, "repair_apply_manual", **rec)
    return {"status": "applied" if ok else "failed", **rec}


def rollback_last(cfg: Config) -> dict[str, Any]:
    """Restore the most recent applied fix from its backup."""
    if not cfg.applied_fixes_file.exists():
        return {"status": "nothing_to_rollback"}
    items = json.loads(cfg.applied_fixes_file.read_text(encoding="utf-8"))
    if not items:
        return {"status": "nothing_to_rollback"}
    last = items[-1]
    backup = Path(last.get("backup", ""))
    target = cfg.project_root / last.get("file", "")
    if not backup.exists() or not target.exists():
        return {"status": "backup_missing", "fix": last}
    try:
        shutil.copy2(backup, target)
    except Exception as e:
        return {"status": "rollback_failed", "error": str(e)}
    items[-1]["rolled_back"] = True
    cfg.applied_fixes_file.write_text(json.dumps(items, indent=2), encoding="utf-8")
    audit.write(cfg.audit_log_file, "repair_rollback", file=str(target), backup=str(backup))
    return {"status": "rolled_back", "file": str(target)}
