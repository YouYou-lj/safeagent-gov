"""Controlled file simulator mapped only to the repository demo data root."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

from safeagent_gov.errors import UnsafeToolArgumentError
from safeagent_gov.paths import resource_root

DATA_ROOT = Path(os.getenv("SAFEAGENT_FILE_DATA_ROOT", str(resource_root() / "agent_demo" / "data"))).resolve()


def _resolve_virtual(virtual_path: str) -> Path:
    pure = PurePosixPath(virtual_path)
    if not virtual_path.startswith("/data/") or ".." in pure.parts:
        raise UnsafeToolArgumentError("仅支持 /data 下的规范化虚拟路径")
    relative = Path(*pure.parts[2:])
    resolved = (DATA_ROOT / relative).resolve()
    if DATA_ROOT.resolve() not in resolved.parents and resolved != DATA_ROOT.resolve():
        raise UnsafeToolArgumentError("路径超出受控数据目录")
    return resolved


def file_read(path: str, **_: object) -> dict[str, object]:
    target = _resolve_virtual(path)
    if not target.exists() or not target.is_file():
        return {"status": "not_found", "path": path, "content": "演示文件不存在"}
    content = target.read_text(encoding="utf-8", errors="replace")[:8192]
    return {"status": "success", "path": path, "content": content, "truncated": target.stat().st_size > 8192}


def file_write(path: str, content: str = "", **_: object) -> dict[str, object]:
    target = _resolve_virtual(path)
    if "output" not in target.relative_to(DATA_ROOT).parts:
        raise UnsafeToolArgumentError("写入仅限 /data/output")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content[:100_000], encoding="utf-8")
    return {"status": "success", "path": path, "bytes": len(content[:100_000].encode("utf-8"))}


def file_delete(path: str, **_: object) -> dict[str, object]:
    return {"status": "blocked_simulation", "path": path, "message": "删除操作未执行"}
