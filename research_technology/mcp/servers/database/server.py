"""Database simulator; it never opens a database connection."""

from __future__ import annotations


def db_query(sql: str, **_: object) -> dict[str, object]:
    return {
        "status": "simulated",
        "sql_preview": sql[:160],
        "rows": [],
        "message": "只读查询策略通过；未连接真实数据库",
    }


def db_write(sql: str, **_: object) -> dict[str, object]:
    return {
        "status": "blocked_simulation",
        "sql_preview": sql[:160],
        "affected_rows": 0,
        "message": "数据库写入未执行",
    }
