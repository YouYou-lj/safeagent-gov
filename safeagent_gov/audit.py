"""Public TraceAudit-Gov API."""

from importlib import import_module

_audit = import_module("skills.traceaudit-gov.src.audit")
create_trace = _audit.create_trace
export_audit_report = _audit.export_audit_report
get_audit_trace = _audit.get_audit_trace
get_trace_identity = _audit.get_trace_identity
list_pending_approvals = _audit.list_pending_approvals
list_expired_traces = _audit.list_expired_traces
log_event = _audit.log_event
record_approval = _audit.record_approval
verify_trace = _audit.verify_trace
_replay = import_module("skills.traceaudit-gov.src.replay")
create_replay_bundle = _replay.create_replay_bundle
replay_trace = _replay.replay_trace
verify_replay_bundle = _replay.verify_replay_bundle

__all__ = [
    "create_trace",
    "log_event",
    "get_audit_trace",
    "get_trace_identity",
    "export_audit_report",
    "list_pending_approvals",
    "list_expired_traces",
    "record_approval",
    "verify_trace",
    "create_replay_bundle",
    "verify_replay_bundle",
    "replay_trace",
]
