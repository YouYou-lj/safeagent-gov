"""Email simulator; it never connects to an SMTP or email API service."""

from __future__ import annotations


def send_email(
    to: str,
    subject: str = "",
    content: str = "",
    attachments: list[str] | None = None,
    **_: object,
) -> dict[str, object]:
    return {
        "status": "simulated",
        "message": "邮件已进入模拟发送记录，未连接真实邮件系统",
        "to": to,
        "subject": subject,
        "content_preview": content[:160],
        "attachments": attachments or [],
    }
