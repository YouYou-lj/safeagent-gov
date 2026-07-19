"""Browser simulator; no network request is made."""

from __future__ import annotations


def browser_visit(url: str, **_: object) -> dict[str, object]:
    return {"status": "simulated", "url": url, "message": "域名策略通过；原型未执行真实网络访问"}
