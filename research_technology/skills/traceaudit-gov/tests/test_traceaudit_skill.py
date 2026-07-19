from importlib import import_module


def _load_entrypoint():
    return import_module("skills.traceaudit-gov.src.audit")


def test_skill_entrypoint_records_trace():
    audit = _load_entrypoint()
    trace_id = audit.create_trace("skill contract test")
    audit.log_event(trace_id, "final_output", {"status": "complete"})
    trace = audit.get_audit_trace(trace_id)
    assert trace["audit_status"] == "complete"
