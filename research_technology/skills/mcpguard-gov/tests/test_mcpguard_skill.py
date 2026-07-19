from importlib import import_module


def _load_entrypoint():
    module = import_module("skills.mcpguard-gov.src.guard")
    return module.check_tool_call


def test_skill_entrypoint_blocks_shell():
    check_tool_call = _load_entrypoint()
    result = check_tool_call("shell_exec", {"command": "echo unsafe"}, {})
    assert result["decision"] == "block"
    assert result["policy_version"] == "2.0.0"
