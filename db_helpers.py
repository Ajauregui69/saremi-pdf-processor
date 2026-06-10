"""
Helpers para usar aiopg con una interfaz similar a asyncpg (fetchrow, fetch, fetchval)
"""

from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Optional
import psycopg2.extras

from database import get_pool


class DBResult(dict):
    """Dict que permite acceso por atributo además de por clave."""
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)


class DBConn:
    """Wrapper sobre aiopg.Connection con API similar a asyncpg."""

    def __init__(self, conn):
        self._conn = conn

    async def fetchrow(self, query: str, *args) -> Optional[DBResult]:
        async with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            await cur.execute(query, args or None)
            row = await cur.fetchone()
            return DBResult(row) if row else None

    async def fetch(self, query: str, *args) -> list[DBResult]:
        async with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            await cur.execute(query, args or None)
            rows = await cur.fetchall()
            return [DBResult(r) for r in rows]

    async def fetchval(self, query: str, *args) -> Any:
        async with self._conn.cursor() as cur:
            await cur.execute(query, args or None)
            row = await cur.fetchone()
            return row[0] if row else None

    async def execute(self, query: str, *args) -> str:
        async with self._conn.cursor() as cur:
            await cur.execute(query, args or None)
            return f"OK {cur.rowcount}"


@asynccontextmanager
async def get_conn() -> AsyncGenerator[DBConn, None]:
    async with get_pool().acquire() as conn:
        yield DBConn(conn)
