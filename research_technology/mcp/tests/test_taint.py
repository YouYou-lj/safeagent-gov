from mcp.gateway import check_tool_call
from mcp.gateway.taint import infer_result_labels, join_labels


def test_confidential_summary_stays_tainted_and_requires_external_approval():
    derived = join_labels(["confidential"], ["public"])
    result = check_tool_call(
        "send_email",
        {"to": "partner@example.com", "content": "已重新摘要和编码"},
        {"data_labels": [label.value for label in derived]},
    )
    assert result["decision"] == "require_approval"
    assert result["policy_hit"] == "data_flow.external_sink.require_approval"


def test_restricted_data_is_blocked_from_external_api_even_when_encoded():
    result = check_tool_call(
        "api_call",
        {"url": "https://www.gov.cn/api", "body": {"payload": "base64-summary"}},
        {"data_labels": ["restricted"]},
    )
    assert result["decision"] == "block"
    assert result["policy_hit"] == "data_flow.external_sink.block"


def test_file_read_result_gets_path_label_without_downgrade():
    labels = infer_result_labels("file_read", {"path": "/data/approved/case.txt"}, ["internal"])
    assert [label.value for label in labels] == ["internal", "confidential"]
