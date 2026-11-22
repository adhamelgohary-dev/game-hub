"""Read and persist boolean preferences in the local JSON settings table."""

import json
import logging
import sqlite3

from gamehub.core.storage.db import Database

LOGGER = logging.getLogger(__name__)


def read_boolean(connection: sqlite3.Connection, key: str, *, default: bool) -> bool:
    row = connection.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is not None:
        try:
            value = json.loads(row["value"])
        except ValueError:
            value = None
        if isinstance(value, bool):
            return value
        LOGGER.warning("invalid_setting key=%s", key)
    return default


def write_boolean(database: Database, key: str, enabled: bool) -> None:
    if not isinstance(enabled, bool):
        raise TypeError("The setting must be a boolean.")
    with database.write() as connection:
        connection.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(enabled)),
        )
