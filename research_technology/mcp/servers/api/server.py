"""External API simulator; it records intent and performs no HTTP request."""

from __future__ import annotations

from typing import Any


def api_call(
    url: str,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    **_: object,
) -> dict[str, object]:
    return {
        "status": "simulated",
        "url": url,
        "method": method.upper(),
        "body_fields": sorted((body or {}).keys()),
        "message": "API 策略通过；未执行真实网络请求",
    }
