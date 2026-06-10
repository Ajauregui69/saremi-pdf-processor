"""
Conexión a PostgreSQL para SarEmi usando aiopg (wrapper async de psycopg2)
"""

import os
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import aiopg

logger = logging.getLogger(__name__)

_pool: aiopg.Pool | None = None


def _dsn() -> str:
    return (
        f"host={os.getenv('DB_HOST', '172.19.48.1')} "
        f"port={os.getenv('DB_PORT', '5432')} "
        f"user={os.getenv('DB_USER', 'postgres')} "
        f"password={os.getenv('DB_PASSWORD', '')} "
        f"dbname={os.getenv('DB_NAME', 'saremi')}"
    )


async def init_db() -> None:
    global _pool
    _pool = await aiopg.create_pool(_dsn(), minsize=2, maxsize=10)
    logger.info("PostgreSQL pool inicializado (aiopg)")


async def close_db() -> None:
    global _pool
    if _pool:
        _pool.close()
        await _pool.wait_closed()
        logger.info("PostgreSQL pool cerrado")


def get_pool() -> aiopg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool no inicializado — llama init_db() primero")
    return _pool


@asynccontextmanager
async def get_conn() -> AsyncGenerator[aiopg.Connection, None]:
    async with get_pool().acquire() as conn:
        yield conn
