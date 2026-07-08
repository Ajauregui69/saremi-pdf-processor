"""
Autenticación por API Key para instituciones cliente
Valida X-API-Key contra la tabla api_keys en PostgreSQL
"""

import hashlib
import json
import logging
import os
from fastapi import Security, HTTPException, Request
from fastapi.security import APIKeyHeader

from auth.entitlements import (
    DEFAULT_CONFIG,
    doc_type_allowed,
    doc_type_from_path,
    normalize_config,
    protocol_allowed,
    protocol_for_path,
)

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
                SELECT ak.institution_id, i.name AS institution_name, i.config AS institution_config
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
            raw_config = row.get("institution_config")
            if isinstance(raw_config, str):
                try:
                    raw_config = json.loads(raw_config)
                except ValueError:
                    raw_config = None
            config = normalize_config(raw_config)
            _enforce_entitlements(request, config, row["institution_name"])

            await conn.execute(
                "UPDATE api_keys SET last_used_at = NOW(), usage_count = usage_count + 1 WHERE key_hash = %s",
                key_hash,
            )
            request.state.institution_id = institution_id
            request.state.institution_name = row["institution_name"]
            request.state.institution_config = config
            logger.info(f"Acceso autorizado: {row['institution_name']} ({institution_id})")
            return institution_id

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error validando API key en DB: {e}")
        # Fallback a env vars si la DB no está disponible
        return _check_env_fallback(api_key, request)


def _enforce_entitlements(request: Request, config: dict, institution_name: str) -> None:
    """
    Aplica la configuración del token al request actual:
    protocolo (REST vs SOAP) y tipo de documento cuando viene en el path REST.
    Los tipos resueltos por auto-detección se validan después en el endpoint.
    """
    path = request.url.path
    protocol = protocol_for_path(path)
    if not protocol_allowed(config, protocol):
        logger.warning(f"[{institution_name}] Protocolo '{protocol}' no habilitado para su plan")
        raise HTTPException(
            status_code=403,
            detail=f"El protocolo {protocol.upper()} no está habilitado para su institución. "
                   f"Protocolos permitidos: {', '.join(config.get('allowed_protocols', []))}",
        )

    path_doc_type = doc_type_from_path(path)
    if path_doc_type and not doc_type_allowed(config, path_doc_type):
        logger.warning(f"[{institution_name}] Tipo de documento '{path_doc_type}' no habilitado")
        raise HTTPException(
            status_code=403,
            detail=f"El tipo de documento '{path_doc_type}' no está habilitado para su institución.",
        )


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
            request.state.institution_config = dict(DEFAULT_CONFIG)
            logger.warning(f"API Key validada por fallback ENV: {institution_id}")
            return institution_id.strip()
    raise HTTPException(status_code=403, detail="API Key inválida")
