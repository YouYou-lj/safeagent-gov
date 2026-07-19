"""Shell simulator; commands are never executed."""

from __future__ import annotations


def shell_exec(command: str, **_: object) -> dict[str, object]:
    return {"status": "blocked_simulation", "command": command, "message": "Shell 命令未执行"}
