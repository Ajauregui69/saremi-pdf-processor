"""
Entitlements por institución — configuración del token/API key.

Cada institución tiene un JSONB `config` en la tabla `institutions` que controla:
  - allowed_protocols:       ["rest", "soap"] — por cuáles interfaces puede llamar
  - blockchain_enabled:      true/false — registrar (o no) sus verificaciones en blockchain
  - allowed_document_types:  ["*"] o lista de tipos ("ine", "curp", ...)

El default es totalmente permisivo (compatibilidad con instituciones existentes).
La configuración se carga en get_api_key() y viaja en request.state.institution_config.
"""

import logging
from fastapi import Request

logger = logging.getLogger(__name__)

DEFAULT_CONFIG: dict = {
    "allowed_protocols": ["rest", "soap"],
    "blockchain_enabled": True,
    "allowed_document_types": ["*"],
}

VALID_PROTOCOLS = {"rest", "soap"}


def normalize_config(raw) -> dict:
    """Mezcla la config almacenada con los defaults (campos faltantes → permisivo)."""
    cfg = dict(DEFAULT_CONFIG)
    if isinstance(raw, dict):
        for key in DEFAULT_CONFIG:
            if key in raw and raw[key] is not None:
                cfg[key] = raw[key]
    return cfg


def get_request_config(request: Request) -> dict:
    """Config de la institución autenticada en este request (default si no hay)."""
    return getattr(request.state, "institution_config", None) or dict(DEFAULT_CONFIG)


def protocol_for_path(path: str) -> str:
    return "soap" if path.startswith("/soap") else "rest"


def protocol_allowed(config: dict, protocol: str) -> bool:
    allowed = config.get("allowed_protocols") or DEFAULT_CONFIG["allowed_protocols"]
    return protocol in [str(p).lower() for p in allowed]


def doc_type_allowed(config: dict, doc_type: str) -> bool:
    """'*' permite todo. 'auto' siempre se permite al solicitar (se valida el tipo detectado)."""
    if doc_type in ("auto", "document", "unknown", ""):
        return True
    allowed = config.get("allowed_document_types") or ["*"]
    allowed = [str(t).lower() for t in allowed]
    return "*" in allowed or doc_type.lower() in allowed


# Tipos de documento del path REST que se validan contra allowed_document_types.
# /v1/verify/document (auto) y /v1/verify/pending se validan después, con el tipo real.
_PATH_SKIP = {"document", "pending"}


def doc_type_from_path(path: str) -> str | None:
    """Extrae el tipo de documento de un path REST /v1/verify/{tipo}."""
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 3 and parts[0] == "v1" and parts[1] == "verify":
        segment = parts[2].replace("-", "_").lower()
        if segment not in _PATH_SKIP:
            return segment
    return None
