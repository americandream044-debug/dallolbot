"""Small asynchronous SQLite connection layer."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import aiosqlite


class Database:
    """Open short-lived SQLite connections with WAL and row dictionaries."""

    def __init__(self, path: str) -> None:
        self.path = str(Path(path).expanduser())

    async def initialize(self) -> None:
        """Create schema and enable durable SQLite settings."""
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("PRAGMA synchronous=NORMAL")
            await conn.execute("PRAGMA foreign_keys=ON")
            await conn.executescript(schema)
            # Additive migrations keep an existing database compatible with newer releases.
            migrations = {
                "users": {"is_blocked": "INTEGER NOT NULL DEFAULT 0", "note": "TEXT NOT NULL DEFAULT ''"},
                "posts": {"media_type": "TEXT", "media_file_id": "TEXT", "recurrence": "TEXT", "views_manual": "INTEGER", "buttons_json": "TEXT NOT NULL DEFAULT '[]'", "poll_question": "TEXT", "poll_options_json": "TEXT", "poll_message_id": "INTEGER"},
                "broadcasts": {"media_type": "TEXT", "file_id": "TEXT", "cancelled": "INTEGER NOT NULL DEFAULT 0"},
            }
            for table, columns in migrations.items():
                cursor = await conn.execute(f"PRAGMA table_info({table})")
                present = {row[1] for row in await cursor.fetchall()}
                for column, definition in columns.items():
                    if column not in present:
                        await conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            await conn.commit()

    async def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        """Execute a write query and return its last inserted row id."""
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA foreign_keys=ON")
            cursor = await conn.execute(sql, tuple(params))
            await conn.commit()
            return int(cursor.lastrowid or cursor.rowcount or 0)

    async def executemany(self, sql: str, rows: Iterable[Iterable[Any]]) -> None:
        """Execute a batch of write queries."""
        async with aiosqlite.connect(self.path) as conn:
            await conn.executemany(sql, [tuple(row) for row in rows])
            await conn.commit()

    async def fetchone(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        """Return one row as a plain dictionary."""
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(sql, tuple(params))
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def fetchall(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        """Return all result rows as plain dictionaries."""
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(sql, tuple(params))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def integrity_check(self) -> str:
        """Return SQLite integrity check result."""
        row = await self.fetchone("PRAGMA integrity_check")
        return str(next(iter(row.values()))) if row else "unknown"
