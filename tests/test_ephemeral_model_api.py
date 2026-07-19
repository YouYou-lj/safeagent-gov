from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from backend.api import model_api
from backend.main import app
from safeagent_gov.auth import issue_token


class CapturingTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def send(self, endpoint, headers, payload, timeout_seconds):  # noqa: ANN001, ANN201
        self.calls.append(
            {
                "endpoint": endpoint,
                "headers": dict(headers),
                "payload": dict(payload),
                "timeout_seconds": timeout_seconds,
            }
        )
        return {
            "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 1},
        }


def _headers(role: str = "staff") -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_token('model-user', 'tenant-a', role)}"}


def test_ephemeral_connection_uses_request_scoped_key_and_does_not_persist_it() -> None:
    transport = CapturingTransport()
    app.dependency_overrides[model_api.get_ephemeral_transport] = lambda: transport
    secret = "temporary-secret-value"
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/model/test-connection",
                headers=_headers(),
                json={"provider": "openai", "model": "gpt-test", "api_key": secret},
            )
            assert response.status_code == 200, response.text
            result = response.json()
            assert result["credential_persisted"] is False
            assert result["output_trusted"] is False
            assert result["response"]["content"] == "OK"
            assert secret not in response.text
            assert transport.calls[0]["headers"]["Authorization"] == f"Bearer {secret}"
            audit = client.get(f"/api/audit/{result['trace_id']}", headers=_headers())
            assert audit.status_code == 200
            assert secret not in audit.text
    finally:
        app.dependency_overrides.pop(model_api.get_ephemeral_transport, None)


def test_ephemeral_chat_marks_external_output_untrusted() -> None:
    transport = CapturingTransport()
    app.dependency_overrides[model_api.get_ephemeral_transport] = lambda: transport
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/model/session/chat",
                headers=_headers(),
                json={
                    "provider": "openai",
                    "model": "gpt-test",
                    "api_key": "one-shot",
                    "messages": [{"role": "user", "content": "普通公开测试"}],
                    "data_classification": "public",
                },
            )
            assert response.status_code == 200, response.text
            assert response.json()["response"]["output_trusted"] is False
            assert response.json()["output_risk"]["action"] == "allow"
    finally:
        app.dependency_overrides.pop(model_api.get_ephemeral_transport, None)


def test_ephemeral_endpoint_and_data_classification_fail_closed() -> None:
    transport = CapturingTransport()
    app.dependency_overrides[model_api.get_ephemeral_transport] = lambda: transport
    try:
        with TestClient(app) as client:
            ssrf = client.post(
                "/api/model/test-connection",
                headers=_headers(),
                json={
                    "provider": "openai",
                    "model": "gpt-test",
                    "endpoint": "https://169.254.169.254/v1/chat/completions",
                    "api_key": "one-shot",
                },
            )
            assert ssrf.status_code == 400
            confidential = client.post(
                "/api/model/session/chat",
                headers=_headers(),
                json={
                    "provider": "openai",
                    "model": "gpt-test",
                    "api_key": "one-shot",
                    "messages": [{"role": "user", "content": "机密材料"}],
                    "data_classification": "confidential",
                },
            )
            assert confidential.status_code == 400
            assert transport.calls == []
    finally:
        app.dependency_overrides.pop(model_api.get_ephemeral_transport, None)


def test_ephemeral_model_endpoints_require_authentication() -> None:
    with TestClient(app) as client:
        assert client.post("/api/model/test-connection", json={}).status_code == 401
        assert client.post("/api/model/session/chat", json={}).status_code == 401
