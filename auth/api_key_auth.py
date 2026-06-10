"""
Autenticación por API Key para instituciones cliente
Valida X-API-Key contra la tabla api_keys en PostgreSQL
"""

import hashlib
import logging
import os
from fastapi import Security, HTTPException, Request
from fastapi.security import APIKeyHeader

logger = logging.getLogger(__name__)

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


async def get_api_key(request: Request, api_key: str = Security(API_KEY_HEADER)) -> str:
    """
    Valida X-API-Key contra PostgreSQL.
    Retorna el institution_id si es válida, HTTP 403 si no.
    """
    if not api_key:
        raise HTTPException(status_code=403, detail="Se requiere X-API-Key")

    key_hash = _hash_key(api_key)

    try:
        from db_helpers import get_conn
        async with get_conn() as conn:
            row = await conn.fetchrow(
                """
                SELECT ak.institution_id, i.name AS institution_name
                FROM api_keys ak
                JOIN institutions i ON i.id = ak.institution_id
                WHERE ak.key_hash = %s
                  AND ak.active = true
                  AND i.active = true
                  AND (ak.expires_at IS NULL OR ak.expires_at > NOW())
                """,
                key_hash,
            )
            if not row:
                return _check_env_fallback(api_key, request)

            institution_id = str(row["institution_id"])
            await conn.execute(
                "UPDATE api_keys SET last_used_at = NOW(), usage_count = usage_count + 1 WHERE key_hash = %s",
                key_hash,
            )
            request.state.institution_id = institution_id
            request.state.institution_name = row["institution_name"]
            logger.info(f"Acceso autorizado: {row['institution_name']} ({institution_id})")
            return institution_id

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error validando API key en DB: {e}")
        # Fallback a env vars si la DB no está disponible
        return _check_env_fallback(api_key, request)


def _check_env_fallback(api_key: str, request: Request) -> str:
    """Fallback: valida contra API_KEYS del .env (solo desarrollo)."""
    raw = os.getenv("API_KEYS", "")
    for entry in raw.split(","):
        entry = entry.strip()
        if ":" not in entry:
            continue
        institution_id, env_key = entry.split(":", 1)
        if env_key.strip() == api_key:
            request.state.institution_id = institution_id.strip()
            request.state.institution_name = institution_id.strip()
            logger.warning(f"API Key validada por fallback ENV: {institution_id}")
            return institution_id.strip()
    raise HTTPException(status_code=403, detail="API Key inválida")
