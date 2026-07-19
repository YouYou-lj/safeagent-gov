import pytest

from safeagent_gov.task_runtime import runtime_config


def test_runtime_config_reads_valid_environment(monkeypatch):
    monkeypatch.setenv("SAFEAGENT_REDIS_URL", "rediss://cache.example:6380/2")
    monkeypatch.setenv("SAFEAGENT_TASK_REDIS_NAMESPACE", "tenant:tasks")
    monkeypatch.setenv("SAFEAGENT_TASK_LEASE_SECONDS", "12.5")
    monkeypatch.setenv("SAFEAGENT_TASK_STAGING_TIMEOUT_SECONDS", "45")

    assert runtime_config.redis_url() == "rediss://cache.example:6380/2"
    assert runtime_config.redis_namespace() == "tenant:tasks"
    assert runtime_config.lease_seconds() == 12.5
    assert runtime_config.staging_timeout_seconds() == 45.0


def test_runtime_config_rejects_invalid_environment(monkeypatch):
    monkeypatch.setenv("SAFEAGENT_REDIS_URL", "https://cache.example")
    with pytest.raises(RuntimeError, match="仅支持"):
        runtime_config.redis_url()

    monkeypatch.setenv("SAFEAGENT_TASK_LEASE_SECONDS", "not-a-number")
    with pytest.raises(RuntimeError, match="必须是数字"):
        runtime_config.lease_seconds()

    monkeypatch.setenv("SAFEAGENT_TASK_LEASE_SECONDS", "0.5")
    with pytest.raises(RuntimeError, match="必须介于"):
        runtime_config.lease_seconds()


def test_redis_task_store_is_built_once_from_validated_config(monkeypatch):
    captured = {}
    sentinel = object()

    def fake_from_url(url, settings, *, namespace, lease_seconds, staging_timeout_seconds):
        captured.update(
            url=url,
            settings=settings,
            namespace=namespace,
            lease_seconds=lease_seconds,
            staging_timeout_seconds=staging_timeout_seconds,
        )
        return sentinel

    monkeypatch.setattr(runtime_config.RedisTaskStore, "from_url", staticmethod(fake_from_url))
    monkeypatch.setenv("SAFEAGENT_REDIS_URL", "unix:///tmp/safeagent-redis.sock")
    monkeypatch.setenv("SAFEAGENT_TASK_REDIS_NAMESPACE", "test:tasks")
    runtime_config.get_redis_task_store.cache_clear()
    try:
        assert runtime_config.get_redis_task_store() is sentinel
        assert runtime_config.get_redis_task_store() is sentinel
    finally:
        runtime_config.get_redis_task_store.cache_clear()

    assert captured["url"] == "unix:///tmp/safeagent-redis.sock"
    assert captured["namespace"] == "test:tasks"
    assert captured["lease_seconds"] == 15.0
    assert captured["staging_timeout_seconds"] == 30.0
