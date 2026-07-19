"""Small authenticated API probe used by the distributed recovery benchmark."""

from __future__ import annotations

import argparse
import json
import urllib.request
from typing import Any

from safeagent_gov.auth import issue_token

BASE_URL = "http://127.0.0.1:8000"


def _request(path: str, *, role: str = "staff", body: dict[str, Any] | None = None) -> Any:
    token = issue_token("distributed-recovery-probe", "recovery-tenant", role)
    headers = {"Authorization": f"Bearer {token}"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(f"{BASE_URL}{path}", headers=headers, data=data)
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    submit = subparsers.add_parser("submit")
    submit.add_argument("--idempotency-key", required=True)
    get_task = subparsers.add_parser("get")
    get_task.add_argument("task_id")
    get_audit = subparsers.add_parser("audit")
    get_audit.add_argument("trace_id")
    subparsers.add_parser("metrics")
    args = parser.parse_args()

    if args.action == "submit":
        output = _request(
            "/api/tasks/submit",
            body={
                "kind": "security_check",
                "priority": "critical",
                "payload": {"text": "分布式恢复演练：普通公开政策内容"},
                "idempotency_key": args.idempotency_key,
                "timeout_seconds": 10,
                "max_attempts": 2,
            },
        )
    elif args.action == "get":
        output = _request(f"/api/tasks/{args.task_id}")
    elif args.action == "audit":
        report = _request(f"/api/audit/{args.trace_id}")
        output = {
            "trace_id": args.trace_id,
            "audit_status": report.get("audit_status"),
            "integrity": report.get("integrity"),
            "stages": [event.get("stage") for event in report.get("events", [])],
        }
    else:
        output = _request("/api/tasks/metrics", role="admin")
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
