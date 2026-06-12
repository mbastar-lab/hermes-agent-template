"""Postgres-backed thread -> session map.

This is NOT a transcript store. The Agent SDK persists the actual conversation
to $HOME/.claude/projects/<encoded-cwd>/*.jsonl on the volume; all we keep in
Postgres is the mapping from a Slack thread to the SDK session_id so a later
mention in the same thread resumes the right session.
"""
from __future__ import annotations

import asyncpg


class SessionStore:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=5)
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_sessions (
                    thread_ts   TEXT PRIMARY KEY,
                    session_id  TEXT NOT NULL,
                    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()

    async def get(self, thread_ts: str) -> str | None:
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT session_id FROM agent_sessions WHERE thread_ts = $1",
                thread_ts,
            )
            return row["session_id"] if row else None

    async def put(self, thread_ts: str, session_id: str) -> None:
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO agent_sessions (thread_ts, session_id, updated_at)
                VALUES ($1, $2, now())
                ON CONFLICT (thread_ts)
                DO UPDATE SET session_id = EXCLUDED.session_id, updated_at = now()
                """,
                thread_ts,
                session_id,
            )
