"""Archive and package input hardening for the static scanner."""

from __future__ import annotations

import shutil
import stat
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from safeagent_gov.errors import UnsafePackageError


@dataclass
class PreparedPackage:
    source: Path
    root: Path
    files: list[Path]
    temporary: Path | None
    archive_stats: dict[str, Any]

    def cleanup(self) -> None:
        if self.temporary:
            shutil.rmtree(self.temporary, ignore_errors=True)


def _validate_member(info: zipfile.ZipInfo, limits: dict[str, Any], seen: set[str]) -> None:
    member = PurePosixPath(info.filename)
    normalized = str(member).casefold()
    if member.is_absolute() or ".." in member.parts or not member.parts:
        raise UnsafePackageError("压缩包包含目录穿越或绝对路径")
    if len(str(member)) > int(limits.get("max_path_length", 240)):
        raise UnsafePackageError("压缩包成员路径过长")
    if normalized in seen:
        raise UnsafePackageError("压缩包包含规范化后重复路径")
    seen.add(normalized)
    mode = info.external_attr >> 16
    file_type = stat.S_IFMT(mode)
    if file_type == stat.S_IFLNK:
        raise UnsafePackageError("压缩包包含符号链接")
    if file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
        raise UnsafePackageError("压缩包包含设备或特殊文件")
    if info.flag_bits & 0x1:
        raise UnsafePackageError("压缩包包含加密成员，无法静态验证")
    max_single = int(limits.get("max_single_file_kb", 1024)) * 1024
    if info.file_size > max_single:
        raise UnsafePackageError("压缩包单文件超过安全上限")
    if info.compress_size == 0 and info.file_size > 0:
        raise UnsafePackageError("压缩包成员压缩比异常")
    ratio = info.file_size / max(1, info.compress_size)
    if ratio > float(limits.get("max_compression_ratio", 100)):
        raise UnsafePackageError("压缩包压缩比异常，疑似 ZIP 炸弹")
    if member.suffix.casefold() in {".zip", ".tar", ".gz", ".7z", ".rar"}:
        raise UnsafePackageError("不接受嵌套压缩包")


def _extract_zip(source: Path, target: Path, limits: dict[str, Any]) -> dict[str, Any]:
    if source.stat().st_size > int(limits.get("max_archive_mb", 10)) * 1024 * 1024:
        raise UnsafePackageError("压缩包本体超过安全大小限制")
    total = 0
    seen: set[str] = set()
    with zipfile.ZipFile(source) as bundle:
        infos = bundle.infolist()
        if len(infos) > int(limits.get("max_files", 500)):
            raise UnsafePackageError("压缩包成员数量超过扫描上限")
        for info in infos:
            _validate_member(info, limits, seen)
            total += info.file_size
            if total > int(limits.get("max_uncompressed_mb", 20)) * 1024 * 1024:
                raise UnsafePackageError("压缩包解压后超过安全大小限制")
        for info in infos:
            relative = Path(*PurePosixPath(info.filename).parts)
            destination = target / relative
            if info.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info) as source_handle, destination.open("xb") as target_handle:
                shutil.copyfileobj(source_handle, target_handle, length=64 * 1024)
    return {"member_count": len(infos), "uncompressed_bytes": total, "archive_bytes": source.stat().st_size}


def prepare_package(package_path: str, limits: dict[str, Any]) -> PreparedPackage:
    original = Path(package_path).expanduser().absolute()
    if original.is_symlink():
        raise UnsafePackageError("扫描入口不能是符号链接")
    source = original.resolve()
    if not source.exists():
        raise FileNotFoundError(f"扫描对象不存在: {source}")
    temporary: Path | None = None
    root = source
    archive_stats: dict[str, Any] = {"member_count": 0, "uncompressed_bytes": 0, "archive_bytes": 0}
    if source.is_file() and source.suffix.casefold() == ".zip":
        temporary = Path(tempfile.mkdtemp(prefix="safeagent-scan-"))
        try:
            archive_stats = _extract_zip(source, temporary, limits)
            root = temporary
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
    candidates = [root] if root.is_file() else list(root.rglob("*"))
    files: list[Path] = []
    total_bytes = 0
    max_single = int(limits.get("max_single_file_kb", 1024)) * 1024
    max_total = int(limits.get("max_uncompressed_mb", 20)) * 1024 * 1024
    for path in candidates:
        if path.is_symlink():
            if temporary:
                shutil.rmtree(temporary, ignore_errors=True)
            raise UnsafePackageError("目录包包含符号链接")
        if path.is_file():
            size = path.stat().st_size
            total_bytes += size
            if size > max_single and path.suffix.casefold() in {
                ".py", ".js", ".ts", ".mjs", ".cjs", ".jsx", ".tsx", ".sh", ".bash", ".ps1",
                ".json", ".yaml", ".yml", ".toml", ".txt",
            }:
                if temporary:
                    shutil.rmtree(temporary, ignore_errors=True)
                raise UnsafePackageError("待分析文本文件超过单文件安全上限")
            files.append(path)
    if len(files) > int(limits.get("max_files", 500)):
        if temporary:
            shutil.rmtree(temporary, ignore_errors=True)
        raise UnsafePackageError("文件数量超过扫描上限")
    if total_bytes > max_total:
        if temporary:
            shutil.rmtree(temporary, ignore_errors=True)
        raise UnsafePackageError("目录包总大小超过扫描上限")
    return PreparedPackage(source=source, root=root, files=files, temporary=temporary, archive_stats=archive_stats)


def check_deadline(started_at: float, timeout_seconds: float) -> None:
    if time.monotonic() - started_at > timeout_seconds:
        raise UnsafePackageError("扫描超过总时间限制")
