"""Consistent, integrity-checked SQLite backup and non-overwriting restore."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = ROOT / "backend" / "data" / "safeagent.db"


class BackupError(RuntimeError):
    pass


def _absolute(path: Path) -> Path:
    return path.expanduser().resolve()


def _integrity(path: Path) -> str:
    if not path.is_file():
        raise BackupError(f"数据库文件不存在: {path}")
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
        try:
            result = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise BackupError(f"数据库完整性检查失败: {path}") from exc
    if result != "ok":
        raise BackupError(f"数据库完整性异常: {result}")
    return result


def _copy_database(source: Path, destination: Path) -> dict[str, str | int]:
    source = _absolute(source)
    destination = _absolute(destination)
    _integrity(source)
    if source == destination:
        raise BackupError("源数据库和目标数据库不能相同")
    if destination.exists():
        raise BackupError(f"目标已存在，拒绝覆盖: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(f".{destination.name}.partial")
    if partial.exists():
        raise BackupError(f"发现未处理的临时备份，拒绝覆盖: {partial}")

    created_partial = False
    try:
        source_connection = sqlite3.connect(f"file:{source}?mode=ro", uri=True, timeout=10)
        destination_connection = sqlite3.connect(partial, timeout=10)
        created_partial = True
        try:
            source_connection.backup(destination_connection)
        finally:
            destination_connection.close()
            source_connection.close()
        _integrity(partial)
        os.replace(partial, destination)
    except (OSError, sqlite3.Error) as exc:
        if created_partial and partial.exists():
            partial.unlink()
        raise BackupError(f"SQLite 一致性复制失败: {exc}") from exc

    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    return {
        "source": str(source),
        "destination": str(destination),
        "integrity_check": _integrity(destination),
        "sha256": digest,
        "size_bytes": destination.stat().st_size,
    }


def backup(source: Path, destination: Path) -> dict[str, str | int]:
    result = _copy_database(source, destination)
    result["operation"] = "backup"
    return result


def restore(backup_path: Path, destination: Path) -> dict[str, str | int]:
    result = _copy_database(backup_path, destination)
    result["operation"] = "restore_to_new_path"
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    backup_parser.add_argument("--output", type=Path, required=True)
    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("--backup", type=Path, required=True)
    restore_parser.add_argument("--output", type=Path, required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--database", type=Path, required=True)
    args = parser.parse_args()

    if args.operation == "backup":
        result = backup(args.database, args.output)
    elif args.operation == "restore":
        result = restore(args.backup, args.output)
    else:
        database = _absolute(args.database)
        result = {"operation": "verify", "database": str(database), "integrity_check": _integrity(database)}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
