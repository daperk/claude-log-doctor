# claude-log-doctor

**A self-healing log watchdog for Python services.** It scans your application logs, classifies errors, asks Claude for a minimal fix, validates the proposal against hard guardrails, and either auto-applies SAFE fixes or queues risky ones for a one-tap approval.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![ci](https://github.com/daperk/claude-log-doctor/actions/workflows/ci.yml/badge.svg)](https://github.com/daperk/claude-log-doctor/actions/workflows/ci.yml)

> **Heads up:** this is an autonomous code-modification tool. Read the *Safety guarantees* section before pointing it at production. The defaults are conservative; the override knobs are not.

---

## Real-world example, in 30 seconds

Your service crashes. In `logs/app.log`:

```
Traceback (most recent call last):
  File "main.py", line 42, in handler
    user.name.upper()
AttributeError: 'NoneType' object has no attribute 'upper'
```

You run `claude-log-doctor scan` (or have it running in the background via `watch`). It:

1. Reads only the **new** log lines since its last scan.
2. Classifies the traceback as `ERROR / attrerror`.
3. Pulls 30 lines of context around `main.py:42`.
4. Asks Claude for a minimal exact-match search/replace fix.
5. Claude returns:
   ```json
   {"needs_fix": true, "file": "main.py",
    "search": "user.name.upper()",
    "replace": "(user.name or 'anonymous').upper()",
    "risk": "SAFE", "explanation": "guard against None"}
   ```
6. The doctor validates: search appears exactly once ✓, file isn't protected ✓, no protected tokens removed ✓, file size sane ✓.
7. Backs up `main.py` and applies the patch.
8. Logs to `state/audit.log`, prints a digest, notifies Telegram/Slack if configured.

Total time: **~10 seconds, ~$0.05**. The bug is gone before you've even looked. If anything looks off, `claude-log-doctor rollback` undoes it.

For anything riskier than a typo or null guard — function logic changes, conditional rewrites, anything in paths you marked sensitive — it doesn't touch a thing. It queues the proposal with an id and pings you for approval.

---

## Why this exists

Production Python services fail in boring, repetitive ways: a missing import after a refactor, a `None` slipping past a type hint, a typo in a log message that crashed the formatter. The fix is usually one line. The cost is finding the line.

`claude-log-doctor` closes the loop:

- **Tail your logs**, incrementally. State is durable; rotation and truncation are handled.
- **Classify** every error using a YAML rule table (extend with your own patterns).
- **Locate the bug** by walking the traceback for the deepest in-project file:line.
- **Ask Claude** for an exact-match search/replace — no fuzzy edits, no whole-file rewrites.
- **Validate** the proposal against safety rails (protected files, protected tokens, file-size limits).
- **Apply or queue** based on a SAFE / NEEDS_APPROVAL / MANUAL_ONLY taxonomy.
- **Cap your daily spend** in USD. Hard stop at the configured cap.

It is a small, focused tool. ~1,000 LOC of source. No magic — every action it takes is in the audit log.

---

## Install

```bash
pip install git+https://github.com/daperk/claude-log-doctor.git

# optional notification channels
pip install "claude-log-doctor[telegram] @ git+https://github.com/daperk/claude-log-doctor.git"
pip install "claude-log-doctor[slack] @ git+https://github.com/daperk/claude-log-doctor.git"
```

Set your Anthropic key:
```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

---

## 60-second tour

```bash
cd /path/to/your/python/project

# write a starter config you can edit
claude-log-doctor init

# show effective config + today's spend + pending count
claude-log-doctor status

# run one classify+repair pass and exit (for cron, CI, manual)
claude-log-doctor scan

# run forever — one pass every interval_min minutes (default 15)
claude-log-doctor watch

# apply a queued NEEDS_APPROVAL fix by id
claude-log-doctor approve abc12345

# undo the most recent applied fix
claude-log-doctor rollback
```

The doctor expects logs at `logs/*.log` (configurable). State (incremental scan offsets, daily spend, audit log, applied fixes, backups) lives at `.log-doctor/state/` under your project root.

---

## How it picks fixes

For every `ERROR` or `CRITICAL` event found in new log lines:

1. Walk the traceback to find the deepest in-project `File ".../foo.py", line N`.
2. Read 30 lines of context around that line.
3. Send the error block + context to Claude with a strict JSON tool prompt.
4. Claude responds with `{file, search, replace, risk, explanation}` or `{needs_fix: false}`.
5. The proposal is validated:
   - `search` must appear **verbatim and exactly once** in the file (no fuzzy matching).
   - The path must be inside the project, not a protected file, and have an allowed extension.
   - The replacement must not delete the file, shrink it >40%, grow >5x, or remove protected tokens.
6. The fix is categorized — SAFE, NEEDS_APPROVAL, or MANUAL_ONLY — taking the more cautious of Claude's self-assessment and the local rule check.
7. SAFE → auto-applied (if `auto_apply_safe: true`); NEEDS_APPROVAL → queued + notified; MANUAL_ONLY → refused, logged.

Every applied fix gets a backup in `.log-doctor/state/backups/` first. `rollback` restores the most recent one.

---

## Safety guarantees

These are enforced in code, not in the prompt — if Claude returns a proposal that violates any of these, it is refused before any write:

- **Never edits** files matching `protected_files` or `manual_only_patterns` (configurable per project).
- **Never edits** any `.env*` file. Always.
- **Only edits** files with extensions in `allowed_extensions` (default: `.py .json .yaml .yml .toml`).
- **Never removes** any substring listed in `protected_tokens` (use this for kill switches, feature flags, audit hooks).
- **Refuses** replacements that delete the file, shrink it >40%, or grow it >5x (anti–LLM-runaway).
- **Refuses** if the `search` text isn't present verbatim, or appears more than once (anti-ambiguity).
- **Caps daily spend** at `daily_budget_usd` USD. Refuses new Claude calls past the cap.
- **Audits everything** — every scan, classification, Claude call, fix attempt, apply, and rollback is appended to `state/audit.log` as JSONL.

The doctor cannot — by design — modify a file outside your project root, can't `rm`, can't run shell commands, can't open network connections beyond the Anthropic and (optional) Telegram/Slack endpoints.

---

## Configuration

```yaml
# claude-log-doctor.yaml at your project root

log_glob: "logs/app-*.log"           # which files to scan
log_tail_lines: 5000                 # cap per pass

protected_files:
  - "config/secrets.py"
  - "migrations/"                    # trailing slash = whole tree
protected_tokens:
  - "DEBUG"
  - "FEATURE_BILLING_V2"
manual_only_patterns:
  - "core/auth/"
  - "billing/"

allowed_extensions: [.py, .json, .yaml]
shrink_max_pct: 0.40
grow_max_factor: 5

max_tokens_per_call: 4000
thinking_budget_tokens: 5000         # set to 0 to disable extended thinking
context_span_lines: 30

pricing:                             # override per-model if needed
  input_per_token: 0.000015          # $15 / 1M
  output_per_token: 0.000075         # $75 / 1M
```

Environment overrides (see `.env.example`):

| Var                              | Default          | Purpose                          |
|----------------------------------|------------------|----------------------------------|
| `ANTHROPIC_API_KEY`              | (unset)          | required for repair calls        |
| `LOG_DOCTOR_DAILY_BUDGET_USD`    | `0.50`           | hard cap on Anthropic spend/day  |
| `LOG_DOCTOR_AUTO_APPLY_SAFE`     | `true`           | auto-apply SAFE-classified fixes |
| `LOG_DOCTOR_INTERVAL_MIN`        | `15`             | `watch` pass cadence             |
| `LOG_DOCTOR_ENABLED`             | `true`           | master kill switch               |
| `LOG_DOCTOR_MODEL`               | `claude-opus-4-7`| any Anthropic model id           |
| `TELEGRAM_BOT_TOKEN` / `_CHAT_ID`| (unset)          | enable Telegram notifier         |
| `SLACK_WEBHOOK_URL`              | (unset)          | enable Slack notifier            |

---

## Daily cost — what to expect

| Service health        | Errors/day | Calls/day | Cost/day      |
|-----------------------|-----------:|----------:|---------------|
| Healthy               |        0–1 |       0–1 | $0.00 – $0.10 |
| Typical (some bugs)   |        2–4 |       2–4 | $0.10 – $0.30 |
| Stormy (post-deploy)  |       5–10 |  up to cap| up to cap     |

Numbers above assume Opus 4.x list pricing. Use Sonnet or Haiku for ~10x cheaper at slightly lower fix quality:

```yaml
# claude-log-doctor.yaml
# (model can also be set via LOG_DOCTOR_MODEL env var)
```

---

## Notifications

By default, digests and approval requests print to stdout. Add Telegram or Slack by setting the relevant env vars and installing the optional extra:

```bash
pip install "claude-log-doctor[slack]"
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/T.../B.../..."
claude-log-doctor watch
```

To plug in a custom channel, subclass `claude_log_doctor.Notifier`:

```python
from claude_log_doctor import Notifier, Config, run_forever

class PagerDutyNotifier(Notifier):
    def send_digest(self, events, applied, pending): ...
    def send_approval_request(self, approval_id, severity, file, summary, diff_preview): ...

run_forever(Config.load(), notifier=PagerDutyNotifier())
```

---

## Library API

For programmatic use:

```python
from claude_log_doctor import Config, run_once, Classifier, repair_event

cfg = Config.load(project_root="/srv/myapp")

# ad-hoc single pass
summary = run_once(cfg)
print(summary)
# {"scanned": 412, "actionable": 2, "applied": 1, "pending": 1, "errors": 0}

# pure classification, no Claude calls
clf = Classifier(cfg)
events = clf.classify_block(open("logs/app.log").read().splitlines())

# repair a single event manually
result = repair_event(cfg, events[0])
```

---

## What this tool will NOT do

- It will not modify strategy, business-logic, billing, or auth code unless you explicitly take it out of `manual_only_patterns`.
- It will not touch `.env*` ever.
- It will not restart your service. It targets *code* bugs, not process crashes — pair it with a process supervisor.
- It will not fix non-Python issues (network, OS, hardware, third-party services).
- It will not silently retry on the same error pattern after `max_fix_attempts_per_error` (default 2).

---

## Development

```bash
git clone https://github.com/daperk/claude-log-doctor.git
cd claude-log-doctor
pip install -e ".[dev]"

pytest -v
ruff check .
```

---

## License

MIT — see [LICENSE](LICENSE).
