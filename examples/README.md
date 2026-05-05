# Examples

A minimal demo: `buggy_app.py` is a tiny script with an intentional
`AttributeError`. `sample.log` is what its traceback looks like in your
log file.

## Try the doctor against the sample log

```bash
# from the repo root
pip install -e ".[dev]"
export ANTHROPIC_API_KEY=sk-ant-...

cd examples
mkdir -p logs
cp sample.log logs/app.log

claude-log-doctor init       # writes a starter claude-log-doctor.yaml
claude-log-doctor status     # confirms config + budget + pending count
claude-log-doctor scan       # one pass: scans logs/, classifies, repairs
```

`scan` will:
1. Find the traceback in `logs/app.log`.
2. Classify it as `ERROR` / `attrerror`.
3. Extract `examples/buggy_app.py:8` from the traceback.
4. Read ±30 lines of context from that file.
5. Ask Claude for a minimal search/replace fix.
6. Validate the fix against the safety rails.
7. Apply if SAFE (default), or queue if NEEDS_APPROVAL.

If applied, look at `buggy_app.py` — the bug is gone. To restore:
```bash
claude-log-doctor rollback
```
