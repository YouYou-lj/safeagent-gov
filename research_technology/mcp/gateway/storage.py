"""Private SQLite helpers for replay-safe MCP gateway state."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from safeagent_gov.paths import resource_root


def gateway_state_path() -> Path:
    """Return the configured durable state path shared with the audit database."""
    configured = os.getenv("SAFEAGENT_GATEWAY_DB_PATH") or os.getenv("SAFEAGENT_DB_PATH")
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            path = resource_root() / path
    else:
        path = resource_root() / "backend" / "data" / "safeagent.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def gateway_connection(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(path or gateway_state_path(), timeout=10, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
    finally:
        connection.close()
