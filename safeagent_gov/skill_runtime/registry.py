"""Atomic, fail-closed loader for repository Skill manifests."""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

import yaml
from pydantic import ValidationError

from safeagent_gov.errors import SkillNotFoundError, SkillRegistryError

from .contracts import (
    RegisteredSkill,
    SkillDefinition,
    SkillExecutionMode,
    SkillRegistrySnapshot,
    SkillTriggerStage,
)


class SkillRegistry:
    """Load fixed local manifests without importing their declared functions."""

    def __init__(self, skills_root: Path):
        self.skills_root = skills_root.resolve()
        self._lock = threading.RLock()
        self._skills: dict[str, RegisteredSkill] = {}
        self._source_digest = hashlib.sha256(b"").hexdigest()

    @staticmethod
    def _read_yaml(path: Path) -> tuple[dict[str, object], str]:
        try:
            text = path.read_text(encoding="utf-8")
            loaded = yaml.safe_load(text)
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise SkillRegistryError(f"无法安全读取 Skill manifest: {path}") from exc
        if not isinstance(loaded, dict):
            raise SkillRegistryError(f"Skill manifest 根节点必须是对象: {path}")
        return loaded, text

    @staticmethod
    def _entrypoint_file(package: Path, entrypoint: str) -> Path:
        module_path, _ = entrypoint.split(":", 1)
        relative = Path(module_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise SkillRegistryError(f"Skill entrypoint 越出包目录: {entrypoint}")
        candidate = package / relative
        resolved = candidate.resolve()
        if candidate.is_symlink() or (resolved != package and package not in resolved.parents):
            raise SkillRegistryError(f"Skill entrypoint 使用符号链接或越出包目录: {entrypoint}")
        if not resolved.is_file():
            raise SkillRegistryError(f"Skill entrypoint 文件不存在: {entrypoint}")
        return resolved

    def load(self) -> SkillRegistrySnapshot:
        if not self.skills_root.is_dir() or self.skills_root.is_symlink():
            raise SkillRegistryError(f"Skill 根目录无效: {self.skills_root}")
        records: dict[str, RegisteredSkill] = {}
        digest_inputs: dict[str, str] = {}
        manifest_paths = sorted(self.skills_root.glob("*/manifest.yaml"))
        if not manifest_paths:
            raise SkillRegistryError("Skill Registry 未找到任何 manifest")
        for manifest_path in manifest_paths:
            package = manifest_path.parent.resolve()
            if manifest_path.is_symlink() or package.parent != self.skills_root or manifest_path.parent.is_symlink():
                raise SkillRegistryError(f"Skill 包使用符号链接或不在固定根目录: {manifest_path}")
            loaded, text = self._read_yaml(manifest_path)
            try:
                definition = SkillDefinition.model_validate(loaded)
            except ValidationError as exc:
                raise SkillRegistryError(f"Skill manifest 不符合执行契约: {manifest_path}: {exc}") from exc
            if definition.name != package.name:
                raise SkillRegistryError(f"Skill name 与目录不一致: {definition.name} != {package.name}")
            if definition.name in records:
                raise SkillRegistryError(f"重复 Skill name: {definition.name}")
            self._entrypoint_file(package, definition.entrypoint)
            if definition.baseline_entrypoint:
                self._entrypoint_file(package, definition.baseline_entrypoint)
            for policy_path in definition.policies.values():
                self._entrypoint_file(package, f"{policy_path}:policy")
            relative = str(manifest_path.relative_to(self.skills_root.parent))
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            records[definition.name] = RegisteredSkill(
                definition=definition,
                manifest_path=relative,
                content_hash=digest,
            )
            digest_inputs[relative] = digest
        source_digest = hashlib.sha256(
            json.dumps(digest_inputs, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        with self._lock:
            self._skills = records
            self._source_digest = source_digest
            return self.snapshot()

    def get(self, name: str) -> RegisteredSkill:
        with self._lock:
            try:
                return self._skills[name]
            except KeyError as exc:
                raise SkillNotFoundError(f"未注册 Skill: {name}") from exc

    def required_for_stage(self, stage: SkillTriggerStage) -> list[RegisteredSkill]:
        with self._lock:
            return [
                record
                for record in self._skills.values()
                if record.definition.enabled
                and record.definition.execution_mode == SkillExecutionMode.MANDATORY
                and stage in record.definition.trigger_stages
            ]

    def snapshot(self) -> SkillRegistrySnapshot:
        with self._lock:
            skills = sorted(self._skills.values(), key=lambda item: item.definition.name)
            return SkillRegistrySnapshot(
                source_digest=self._source_digest,
                skill_count=len(skills),
                enabled_count=sum(record.definition.enabled for record in skills),
                mandatory_count=sum(
                    record.definition.execution_mode == SkillExecutionMode.MANDATORY for record in skills
                ),
                skills=skills,
            )
