"""Pattern-based severity classifier.

Loads rules from JSON, returns the highest-severity classification per line,
and groups multi-line tracebacks into a single event so they survive intact.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .config import Config

SEVERITY_ORDER: dict[str, int] = {"INFO": 0, "WARNING": 1, "ERROR": 2, "CRITICAL": 3}
DEFAULT_SEVERITY = "INFO"


def _load_rules(rules_file: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(rules_file.read_text(encoding="utf-8"))
        rules = data.get("rules", [])
        return [r for r in rules if "pattern" in r and "severity" in r]
    except Exception:
        return []


class Classifier:
    """Holds compiled rules and classifies lines / blocks."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._raw_rules = _load_rules(cfg.rules_file)
        self._compiled: list[tuple[re.Pattern, dict[str, Any]]] = []
        for rule in self._raw_rules:
            try:
                self._compiled.append((re.compile(rule["pattern"]), rule))
            except re.error:
                continue

    def classify_line(self, line: str) -> dict[str, Any]:
        """Return {'severity', 'tag', 'pattern'} for a single line."""
        best_severity = DEFAULT_SEVERITY
        best_rank = SEVERITY_ORDER[DEFAULT_SEVERITY]
        best_tag = "info"
        best_pattern: str | None = None
        for compiled, rule in self._compiled:
            if compiled.search(line):
                rank = SEVERITY_ORDER.get(rule["severity"], 0)
                if rank > best_rank:
                    best_rank = rank
                    best_severity = rule["severity"]
                    best_tag = rule.get("tag", "")
                    best_pattern = rule["pattern"]
        return {"severity": best_severity, "tag": best_tag, "pattern": best_pattern}

    def classify_block(self, lines: list[str]) -> list[dict[str, Any]]:
        """Group multi-line tracebacks. Each event is {severity, tag, lines, summary}."""
        out: list[dict[str, Any]] = []
        i = 0
        n = len(lines)
        while i < n:
            line = lines[i]
            cls = self.classify_line(line)
            if cls["tag"] == "traceback":
                block = [line]
                j = i + 1
                while j < n and (
                    lines[j].startswith(" ")
                    or lines[j].startswith("\t")
                    or lines[j].startswith("File ")
                    or "Error" in lines[j]
                    or "Exception" in lines[j]
                ):
                    block.append(lines[j])
                    j += 1
                    if j - i > 60:
                        break
                tail = block[-1] if block else line
                tail_cls = self.classify_line(tail)
                severity = max(
                    cls["severity"], tail_cls["severity"], key=lambda s: SEVERITY_ORDER[s]
                )
                out.append({
                    "severity": severity,
                    "tag": tail_cls["tag"] if tail_cls["severity"] != "INFO" else "traceback",
                    "lines": block,
                    "summary": tail.strip()[:200],
                })
                i = j
                continue

            if cls["severity"] != "INFO":
                out.append({
                    "severity": cls["severity"],
                    "tag": cls["tag"],
                    "lines": [line],
                    "summary": line.strip()[:200],
                })
            i += 1
        return out

    @staticmethod
    def filter_actionable(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Only ERROR and CRITICAL events get sent to the repair pipeline."""
        return [e for e in events if e["severity"] in ("ERROR", "CRITICAL")]
