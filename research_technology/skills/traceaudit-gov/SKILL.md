# TraceAudit-Gov

## Purpose

Create versioned trace events, verify per-trace hash chains and HMAC signatures,
apply storage/query redaction, export integrity evidence, and replay frozen Agent
security decisions without executing tools.

## Public API

```python
from safeagent_gov.audit import (
    create_trace,
    log_event,
    verify_trace,
    get_audit_trace,
    export_audit_report,
    create_replay_bundle,
    verify_replay_bundle,
    replay_trace,
)
```

## Safety boundary

- An append verifies the existing chain and fails closed on storage or integrity errors.
- Credentials and raw content are redacted or replaced by length + SHA-256 before storage.
- Replay consumes signed snapshots and recorded simulator responses; it never invokes a tool handler.
- Local HMAC signing proves integrity within the deployment trust domain; it is not an external timestamp or HSM root of trust.

## Verification

```bash
python -m pytest research_technology/skills/traceaudit-gov/tests -q
python research_technology/benchmarks/runners/eval_traceaudit.py
```
