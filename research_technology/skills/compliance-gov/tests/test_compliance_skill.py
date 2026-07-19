from importlib import import_module

evaluate_compliance = import_module("skills.compliance-gov.src.checker").evaluate_compliance


def test_compliance_requires_approval_and_blocks_forbidden_or_unprivileged_actions():
    pending = evaluate_compliance(
        "send_email",
        "government_office",
        destination="external@example.com",
        data_labels=["internal"],
    )
    assert pending["decision"] == "require_approval"
    assert "human_approval" in pending["obligations"]

    approved = evaluate_compliance(
        "send_email",
        "government_office",
        destination="external@example.com",
        data_labels=["internal"],
        approval_state="approved",
    )
    assert approved["decision"] == "allow_with_log"

    assert evaluate_compliance("shell_exec", "operations_collaboration")["decision"] == "block"
    assert evaluate_compliance("file_write", "government_office", actor_role="visitor")["decision"] == "block"
    public_browse = evaluate_compliance(
        "browser_visit",
        "knowledge_service",
        destination="https://www.gov.cn/",
        actor_role="visitor",
    )
    assert public_browse["decision"] == "allow_with_log"
