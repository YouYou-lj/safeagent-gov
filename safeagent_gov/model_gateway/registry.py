"""Atomic, fail-closed loader for the secret-free Model Gateway registry."""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path

import yaml
from pydantic import ValidationError

from safeagent_gov.errors import ModelGatewayConfigurationError

from .contracts import ModelGatewayConfig, ModelRegistrySnapshot, ProviderDefinition, ProviderRegistryRecord


def _snapshot(config: ModelGatewayConfig, digest: str) -> ModelRegistrySnapshot:
    records = tuple(
        ProviderRegistryRecord(
            provider_id=provider.provider_id,
            display_name=provider.display_name,
            protocol=provider.protocol,
            model=provider.model,
            enabled=provider.enabled,
            private_deployment=provider.private_deployment,
            capabilities=provider.capabilities,
            task_types=provider.task_types,
            max_context_tokens=provider.max_context_tokens,
            max_output_tokens=provider.max_output_tokens,
        )
        for provider in sorted(config.providers.values(), key=lambda item: item.provider_id)
    )
    return ModelRegistrySnapshot(
        version=config.version,
        source_digest=digest,
        default_provider=config.default_provider,
        provider_count=len(records),
        enabled_count=sum(record.enabled for record in records),
        providers=records,
    )


class ModelRegistry:
    def __init__(self, path: Path) -> None:
        # Keep the configured path un-resolved so a symlink cannot disappear
        # before the explicit trust-boundary check in ``load``.
        self.path = path.absolute()
        self._lock = threading.RLock()
        self._config: ModelGatewayConfig | None = None
        self._digest = ""

    def load(self) -> ModelRegistrySnapshot:
        if self.path.is_symlink():
            raise ModelGatewayConfigurationError("Model Gateway 配置不得为符号链接")
        try:
            raw_text = self.path.read_text(encoding="utf-8")
            raw = yaml.safe_load(raw_text)
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise ModelGatewayConfigurationError(f"无法读取 Model Gateway 配置: {self.path}") from exc
        if not isinstance(raw, dict):
            raise ModelGatewayConfigurationError("Model Gateway YAML 根节点必须是对象")
        providers = raw.get("providers")
        if isinstance(providers, dict):
            raw["providers"] = {
                str(key): {"provider_id": str(key), **value} if isinstance(value, dict) else value
                for key, value in providers.items()
            }
        try:
            candidate = ModelGatewayConfig.model_validate(raw)
        except ValidationError as exc:
            raise ModelGatewayConfigurationError(f"Model Gateway 配置不符合 Schema: {exc}") from exc
        digest = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        with self._lock:
            self._config = candidate
            self._digest = digest
            return self._snapshot_locked()

    def config(self) -> ModelGatewayConfig:
        with self._lock:
            if self._config is None:
                raise ModelGatewayConfigurationError("Model Gateway Registry 尚未加载")
            return self._config

    def get(self, provider_id: str) -> ProviderDefinition:
        config = self.config()
        try:
            return config.providers[provider_id]
        except KeyError as exc:
            raise ModelGatewayConfigurationError(f"未知 Model Provider: {provider_id}") from exc

    def snapshot(self) -> ModelRegistrySnapshot:
        with self._lock:
            if self._config is None:
                raise ModelGatewayConfigurationError("Model Gateway Registry 尚未加载")
            return self._snapshot_locked()

    def _snapshot_locked(self) -> ModelRegistrySnapshot:
        assert self._config is not None
        return _snapshot(self._config, self._digest)


class MemoryModelRegistry:
    """Immutable request-scoped registry for secret-free temporary Provider definitions."""

    def __init__(self, config: ModelGatewayConfig) -> None:
        self._config = config
        public_payload = config.model_dump_json(exclude_none=False)
        self._digest = hashlib.sha256(public_payload.encode("utf-8")).hexdigest()

    def config(self) -> ModelGatewayConfig:
        return self._config

    def get(self, provider_id: str) -> ProviderDefinition:
        try:
            return self._config.providers[provider_id]
        except KeyError as exc:
            raise ModelGatewayConfigurationError(f"未知 Model Provider: {provider_id}") from exc

    def snapshot(self) -> ModelRegistrySnapshot:
        return _snapshot(self._config, self._digest)
