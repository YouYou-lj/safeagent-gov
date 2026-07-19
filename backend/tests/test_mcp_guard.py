from mcp.gateway import check_tool_call


def test_secret_path_is_blocked():
    result = check_tool_call("file_read", {"path": "/data/secret/person.xlsx"}, {})
    assert result["decision"] == "block"


def test_external_mail_requires_approval():
    result = check_tool_call("send_email", {"to": "external@example.com"}, {})
    assert result["decision"] == "require_approval"


def test_shell_is_blocked():
    assert check_tool_call("shell_exec", {"command": "echo test"}, {})["decision"] == "block"


def test_public_file_is_logged_and_allowed():
    assert check_tool_call("file_read", {"path": "/data/public/政策问答示例.txt"}, {})["decision"] == "allow_with_log"
