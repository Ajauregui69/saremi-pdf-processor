"""
Rutas de administración de SarEmi
Requieren Bearer token del BaaS (SigenPlus)
Prefijo: /admin
"""

import hashlib
import json
import logging
import os
import secrets
import time
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr

from db_helpers import get_conn

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])
bearer = HTTPBearer()

BAAS_API_URL = os.getenv("BAAS_API_URL", "")


# ── Auth ───────────────────────────────────────────────────────────────────────

async def get_admin_user(credentials: HTTPAuthorizationCredentials = Depends(bearer)) -> dict:
    token = credentials.credentials

    if not BAAS_API_URL:
        logger.warning("BAAS_API_URL no configurado — modo desarrollo sin validación")
        return {"id": "dev", "email": "dev@saremi.local", "role": "admin"}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{BAAS_API_URL}/api/v1/auth/me",
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code == 401:
                raise HTTPException(status_code=401, detail="Token inválido o expirado")
            resp.raise_for_status()
            data = resp.json()
            # baas-qro returns {"user": {...}} — unwrap if needed
            user = data.get("user", data)
            if user.get("role") not in ("admin", "notary"):
                raise HTTPException(status_code=403, detail="Acceso solo para administradores")
            return user
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error validando token BaaS: {e}")
        raise HTTPException(status_code=401, detail="No se pudo validar el token")


# ── Modelos ────────────────────────────────────────────────────────────────────

class InstitutionCreate(BaseModel):
    name: str
    email: EmailStr
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    plan: str = "basic"
    baas_entity_id: Optional[str] = None


class InstitutionUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    plan: Optional[str] = None
    active: Optional[bool] = None
    baas_entity_id: Optional[str] = None


class ApiKeyCreate(BaseModel):
    label: Optional[str] = None
    expires_at: Optional[datetime] = None


class InstitutionConfigUpdate(BaseModel):
    """Entitlements del token. Solo los campos enviados se actualizan (merge)."""
    allowed_protocols: Optional[list[str]] = None       # ["rest", "soap"]
    blockchain_enabled: Optional[bool] = None
    allowed_document_types: Optional[list[str]] = None  # ["*"] o tipos específicos


class ReviewDecision(BaseModel):
    decision: str
    notes: Optional[str] = None


# ── Institutions ───────────────────────────────────────────────────────────────

@router.get("/institutions")
async def list_institutions(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    active: Optional[bool] = None,
    user: dict = Depends(get_admin_user),
):
    offset = (page - 1) * limit
    async with get_conn() as conn:
        if active is not None:
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM institutions WHERE active = %s", active
            )
            rows = await conn.fetch(
                """
                SELECT i.*, COUNT(ak.id) AS api_keys_count
                FROM institutions i
                LEFT JOIN api_keys ak ON ak.institution_id = i.id AND ak.active = true
                WHERE i.active = %s
                GROUP BY i.id ORDER BY i.created_at DESC
                LIMIT %s OFFSET %s
                """,
                active, limit, offset,
            )
        else:
            total = await conn.fetchval("SELECT COUNT(*) FROM institutions")
            rows = await conn.fetch(
                """
                SELECT i.*, COUNT(ak.id) AS api_keys_count
                FROM institutions i
                LEFT JOIN api_keys ak ON ak.institution_id = i.id AND ak.active = true
                GROUP BY i.id ORDER BY i.created_at DESC
                LIMIT %s OFFSET %s
                """,
                limit, offset,
            )
        return {"data": [dict(r) for r in rows], "total": total, "page": page, "limit": limit}


@router.post("/institutions", status_code=201)
async def create_institution(
    body: InstitutionCreate,
    user: dict = Depends(get_admin_user),
):
    async with get_conn() as conn:
        existing = await conn.fetchrow(
            "SELECT id FROM institutions WHERE email = %s", body.email
        )
        if existing:
            raise HTTPException(status_code=409, detail="Ya existe una institución con ese email")

        row = await conn.fetchrow(
            """
            INSERT INTO institutions (name, email, contact_name, phone, plan, baas_entity_id)
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING *
            """,
            body.name, body.email, body.contact_name, body.phone, body.plan, body.baas_entity_id,
        )
        return dict(row)


@router.get("/institutions/{institution_id}")
async def get_institution(
    institution_id: UUID,
    user: dict = Depends(get_admin_user),
):
    async with get_conn() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM institutions WHERE id = %s", str(institution_id)
        )
        if not row:
            raise HTTPException(status_code=404, detail="Institución no encontrada")
        return dict(row)


@router.patch("/institutions/{institution_id}")
async def update_institution(
    institution_id: UUID,
    body: InstitutionUpdate,
    user: dict = Depends(get_admin_user),
):
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No hay campos para actualizar")

    updates["updated_at"] = datetime.now(timezone.utc)
    set_clause = ", ".join(f"{k} = %s" for k in updates.keys())
    values = list(updates.values())

    async with get_conn() as conn:
        row = await conn.fetchrow(
            f"UPDATE institutions SET {set_clause} WHERE id = %s RETURNING *",
            *values, str(institution_id),
        )
        if not row:
            raise HTTPException(status_code=404, detail="Institución no encontrada")
        return dict(row)


def _valid_config_doc_types() -> set[str]:
    from routers.soap import _allowed_types
    return (_allowed_types() - {"auto"}) | {"employment_letter", "tax_return", "*"}


@router.get("/institutions/{institution_id}/config")
async def get_institution_config(
    institution_id: UUID,
    user: dict = Depends(get_admin_user),
):
    from auth.entitlements import normalize_config
    async with get_conn() as conn:
        row = await conn.fetchrow(
            "SELECT config FROM institutions WHERE id = %s", str(institution_id)
        )
        if not row:
            raise HTTPException(status_code=404, detail="Institución no encontrada")
        raw = row["config"]
        if isinstance(raw, str):
            raw = json.loads(raw)
        return normalize_config(raw)


@router.put("/institutions/{institution_id}/config")
async def update_institution_config(
    institution_id: UUID,
    body: InstitutionConfigUpdate,
    user: dict = Depends(get_admin_user),
):
    from auth.entitlements import VALID_PROTOCOLS, normalize_config

    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No hay campos para actualizar")

    if "allowed_protocols" in updates:
        protocols = {str(p).lower() for p in updates["allowed_protocols"]}
        invalid = protocols - VALID_PROTOCOLS
        if invalid:
            raise HTTPException(status_code=400, detail=f"Protocolos inválidos: {', '.join(invalid)}. Válidos: rest, soap")
        if not protocols:
            raise HTTPException(status_code=400, detail="allowed_protocols no puede quedar vacío")
        updates["allowed_protocols"] = sorted(protocols)

    if "allowed_document_types" in updates:
        types = [str(t).lower() for t in updates["allowed_document_types"]]
        invalid = set(types) - _valid_config_doc_types()
        if invalid:
            raise HTTPException(status_code=400, detail=f"Tipos de documento inválidos: {', '.join(sorted(invalid))}")
        if not types:
            raise HTTPException(status_code=400, detail="allowed_document_types no puede quedar vacío (use [\"*\"] para todos)")
        updates["allowed_document_types"] = types

    async with get_conn() as conn:
        row = await conn.fetchrow(
            "SELECT config FROM institutions WHERE id = %s", str(institution_id)
        )
        if not row:
            raise HTTPException(status_code=404, detail="Institución no encontrada")

        current = row["config"]
        if isinstance(current, str):
            current = json.loads(current)
        merged = normalize_config(current)
        merged.update(updates)

        await conn.execute(
            "UPDATE institutions SET config = %s::jsonb, updated_at = NOW() WHERE id = %s",
            json.dumps(merged), str(institution_id),
        )
        logger.info(f"Config de institución {institution_id} actualizada por {user.get('email')}: {merged}")
        return merged


@router.delete("/institutions/{institution_id}", status_code=204)
async def delete_institution(
    institution_id: UUID,
    user: dict = Depends(get_admin_user),
):
    async with get_conn() as conn:
        result = await conn.execute(
            "DELETE FROM institutions WHERE id = %s", str(institution_id)
        )
        if "0" in result:
            raise HTTPException(status_code=404, detail="Institución no encontrada")


# ── API Keys ───────────────────────────────────────────────────────────────────

@router.get("/institutions/{institution_id}/api-keys")
async def list_api_keys(
    institution_id: UUID,
    user: dict = Depends(get_admin_user),
):
    async with get_conn() as conn:
        rows = await conn.fetch(
            """
            SELECT ak.id, ak.institution_id, ak.key_prefix, ak.label, ak.active,
                   ak.last_used_at, ak.expires_at, ak.created_at, ak.usage_count,
                   COUNT(vl.id) AS total_verifications,
                   COUNT(vl.id) FILTER (WHERE vl.created_at >= NOW() - INTERVAL '30 days') AS verifications_month,
                   COUNT(vl.id) FILTER (WHERE vl.created_at >= NOW() - INTERVAL '24 hours') AS verifications_today
            FROM api_keys ak
            LEFT JOIN verification_logs vl ON vl.institution_id = ak.institution_id
            WHERE ak.institution_id = %s
            GROUP BY ak.id
            ORDER BY ak.created_at DESC
            """,
            str(institution_id),
        )
        return [dict(r) for r in rows]


@router.post("/institutions/{institution_id}/api-keys", status_code=201)
async def create_api_key(
    institution_id: UUID,
    body: ApiKeyCreate,
    user: dict = Depends(get_admin_user),
):
    async with get_conn() as conn:
        inst = await conn.fetchrow(
            "SELECT id FROM institutions WHERE id = %s AND active = true", str(institution_id)
        )
        if not inst:
            raise HTTPException(status_code=404, detail="Institución no encontrada o inactiva")

        raw_key = f"saremi_{secrets.token_hex(24)}"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        key_prefix = raw_key[:10]

        row = await conn.fetchrow(
            """
            INSERT INTO api_keys (institution_id, key_hash, key_prefix, label, expires_at)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, institution_id, key_prefix, label, active, expires_at, created_at
            """,
            str(institution_id), key_hash, key_prefix, body.label, body.expires_at,
        )
        result = dict(row)
        result["api_key"] = raw_key  # Solo se muestra una vez
        return result


@router.delete("/institutions/{institution_id}/api-keys/{key_id}", status_code=204)
async def revoke_api_key(
    institution_id: UUID,
    key_id: UUID,
    user: dict = Depends(get_admin_user),
):
    async with get_conn() as conn:
        result = await conn.execute(
            "UPDATE api_keys SET active = false WHERE id = %s AND institution_id = %s",
            str(key_id), str(institution_id),
        )
        if "0" in result:
            raise HTTPException(status_code=404, detail="API Key no encontrada")


# ── Verification Logs ──────────────────────────────────────────────────────────

@router.get("/verifications")
async def list_verifications(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    institution_id: Optional[UUID] = None,
    document_type: Optional[str] = None,
    status: Optional[str] = None,
    user: dict = Depends(get_admin_user),
):
    offset = (page - 1) * limit
    conditions = []
    params: list = []

    if institution_id:
        conditions.append("vl.institution_id = %s")
        params.append(str(institution_id))
    if document_type:
        conditions.append("vl.document_type = %s")
        params.append(document_type)
    if status:
        conditions.append("vl.status = %s")
        params.append(status)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    async with get_conn() as conn:
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM verification_logs vl {where}", *params
        )
        rows = await conn.fetch(
            f"""
            SELECT vl.*, i.name AS institution_name
            FROM verification_logs vl
            LEFT JOIN institutions i ON i.id = vl.institution_id
            {where}
            ORDER BY vl.created_at DESC
            LIMIT %s OFFSET %s
            """,
            *params, limit, offset,
        )
        return {"data": [dict(r) for r in rows], "total": total, "page": page, "limit": limit}


@router.get("/verifications/{verification_id}")
async def get_verification(
    verification_id: UUID,
    user: dict = Depends(get_admin_user),
):
    async with get_conn() as conn:
        row = await conn.fetchrow(
            """
            SELECT vl.*, i.name AS institution_name
            FROM verification_logs vl
            LEFT JOIN institutions i ON i.id = vl.institution_id
            WHERE vl.id = %s
            """,
            str(verification_id),
        )
        if not row:
            raise HTTPException(status_code=404, detail="Verificación no encontrada")
        return dict(row)


@router.get("/verifications/{verification_id}/file")
async def get_verification_file(
    verification_id: UUID,
    token: str = "",           # query param para iframes (Bearer no funciona en <iframe>)
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer(auto_error=False)),
):
    """
    Sirve el archivo original. Acepta auth via:
    - Header: Authorization: Bearer <token>
    - Query:  ?token=<token>  (para iframes)
    """
    from fastapi.responses import FileResponse as FR
    raw_token = (credentials.credentials if credentials else None) or token
    if not raw_token:
        raise HTTPException(status_code=401, detail="Token requerido")
    # Reutilizar validación de admin
    try:
        await get_admin_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=raw_token))
    except HTTPException:
        raise HTTPException(status_code=403, detail="Acceso denegado")

    async with get_conn() as conn:
        row = await conn.fetchrow(
            "SELECT file_path FROM verification_logs WHERE id = %s",
            str(verification_id),
        )
    if not row or not row["file_path"]:
        raise HTTPException(status_code=404, detail="Archivo no disponible")
    path = row["file_path"]
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Archivo no encontrado en disco")

    # Detectar tipo real por magic bytes, no por extensión
    import imghdr
    with open(path, "rb") as f:
        header = f.read(12)
    if header[:4] == b'\xff\xd8\xff':
        media_type = "image/jpeg"
    elif header[:8] == b'\x89PNG\r\n\x1a\n':
        media_type = "image/png"
    elif header[:4] == b'%PDF':
        media_type = "application/pdf"
    else:
        # Fallback a extensión
        ext = os.path.splitext(path)[1].lower()
        media_type = "application/pdf" if ext == ".pdf" else f"image/{ext.lstrip('.')}"

    return FR(path, media_type=media_type)


@router.post("/verifications/{verification_id}/cancel")
async def cancel_processing(
    verification_id: UUID,
    user: dict = Depends(get_admin_user),
):
    """Cancela una verificación atascada en 'processing', marcándola como manual_review."""
    async with get_conn() as conn:
        row = await conn.fetchrow(
            "SELECT status FROM verification_logs WHERE id = %s", str(verification_id)
        )
        if not row:
            raise HTTPException(status_code=404, detail="Verificación no encontrada")
        if row["status"] != "processing":
            raise HTTPException(status_code=400, detail="Solo se puede cancelar una verificación en estado 'processing'")
        await conn.execute(
            """UPDATE verification_logs
               SET status = 'manual_review', conclusion = 'Análisis cancelado manualmente — requiere re-verificación.'
               WHERE id = %s""",
            str(verification_id),
        )
        await conn.execute(
            "INSERT INTO manual_reviews (verification_id) VALUES (%s) ON CONFLICT DO NOTHING",
            str(verification_id),
        )
    return {"id": str(verification_id), "status": "manual_review"}


@router.delete("/verifications/{verification_id}", status_code=204)
async def delete_verification(
    verification_id: UUID,
    user: dict = Depends(get_admin_user),
):
    """Elimina una verificación y su archivo del disco."""
    async with get_conn() as conn:
        row = await conn.fetchrow(
            "SELECT file_path FROM verification_logs WHERE id = %s", str(verification_id)
        )
        if not row:
            raise HTTPException(status_code=404, detail="Verificación no encontrada")

        # Borrar archivo del disco (silencioso si no existe)
        file_path = row["file_path"]
        if file_path and os.path.exists(file_path):
            try:
                os.unlink(file_path)
            except Exception as e:
                logger.warning(f"No se pudo borrar archivo {file_path}: {e}")

        await conn.execute(
            "DELETE FROM verification_logs WHERE id = %s", str(verification_id)
        )


# ── Person Groups ──────────────────────────────────────────────────────────────

class PersonGroupCreate(BaseModel):
    name: str
    notes: Optional[str] = None
    institution_id: Optional[str] = None
    verification_ids: list[str] = []


@router.get("/person-groups")
async def list_person_groups(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_admin_user),
):
    offset = (page - 1) * limit
    async with get_conn() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM person_groups")
        rows = await conn.fetch(
            """
            SELECT pg.*, i.name AS institution_name,
                   COUNT(pgm.verification_id) AS doc_count
            FROM person_groups pg
            LEFT JOIN institutions i ON i.id = pg.institution_id
            LEFT JOIN person_group_members pgm ON pgm.group_id = pg.id
            GROUP BY pg.id, i.name
            ORDER BY pg.created_at DESC
            LIMIT %s OFFSET %s
            """,
            limit, offset,
        )
        return {"data": [dict(r) for r in rows], "total": total, "page": page, "limit": limit}


@router.post("/person-groups", status_code=201)
async def create_person_group(
    body: PersonGroupCreate,
    user: dict = Depends(get_admin_user),
):
    async with get_conn() as conn:
        group = await conn.fetchrow(
            """
            INSERT INTO person_groups (name, notes, institution_id)
            VALUES (%s, %s, %s) RETURNING *
            """,
            body.name, body.notes, body.institution_id or None,
        )
        group_id = str(group["id"])
        for vid in body.verification_ids:
            await conn.execute(
                "INSERT INTO person_group_members (group_id, verification_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                group_id, vid,
            )
        result = dict(group)
        result["doc_count"] = len(body.verification_ids)
        return result


@router.get("/person-groups/{group_id}")
async def get_person_group(
    group_id: UUID,
    user: dict = Depends(get_admin_user),
):
    async with get_conn() as conn:
        group = await conn.fetchrow(
            "SELECT pg.*, i.name AS institution_name FROM person_groups pg LEFT JOIN institutions i ON i.id = pg.institution_id WHERE pg.id = %s",
            str(group_id),
        )
        if not group:
            raise HTTPException(status_code=404, detail="Grupo no encontrado")
        members = await conn.fetch(
            """
            SELECT vl.*, i.name AS institution_name
            FROM person_group_members pgm
            JOIN verification_logs vl ON vl.id = pgm.verification_id
            LEFT JOIN institutions i ON i.id = vl.institution_id
            WHERE pgm.group_id = %s
            ORDER BY vl.created_at DESC
            """,
            str(group_id),
        )
        result = dict(group)
        result["verifications"] = [dict(m) for m in members]
        return result


@router.patch("/person-groups/{group_id}/members")
async def update_group_members(
    group_id: UUID,
    body: dict,
    user: dict = Depends(get_admin_user),
):
    """Añade o quita verifications del grupo. body: {add: [id,...], remove: [id,...]}"""
    async with get_conn() as conn:
        grp = await conn.fetchrow("SELECT id FROM person_groups WHERE id = %s", str(group_id))
        if not grp:
            raise HTTPException(status_code=404, detail="Grupo no encontrado")
        for vid in body.get("add", []):
            await conn.execute(
                "INSERT INTO person_group_members (group_id, verification_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                str(group_id), vid,
            )
        for vid in body.get("remove", []):
            await conn.execute(
                "DELETE FROM person_group_members WHERE group_id = %s AND verification_id = %s",
                str(group_id), vid,
            )
    return {"ok": True}


@router.delete("/person-groups/{group_id}", status_code=204)
async def delete_person_group(
    group_id: UUID,
    user: dict = Depends(get_admin_user),
):
    async with get_conn() as conn:
        result = await conn.execute("DELETE FROM person_groups WHERE id = %s", str(group_id))
        if "0" in result:
            raise HTTPException(status_code=404, detail="Grupo no encontrado")


# ── Stats / Dashboard ──────────────────────────────────────────────────────────

@router.get("/stats")
async def get_stats(user: dict = Depends(get_admin_user)):
    async with get_conn() as conn:
        summary = await conn.fetchrow(
            """
            SELECT
                (SELECT COUNT(*) FROM institutions WHERE active = true) AS active_institutions,
                (SELECT COUNT(*) FROM verification_logs
                 WHERE created_at >= NOW() - INTERVAL '24 hours') AS verifications_today,
                (SELECT COUNT(*) FROM verification_logs
                 WHERE created_at >= NOW() - INTERVAL '30 days') AS verifications_month,
                (SELECT ROUND(AVG(confidence_score)::numeric, 3)
                 FROM verification_logs
                 WHERE created_at >= NOW() - INTERVAL '30 days') AS avg_confidence_month,
                (SELECT COUNT(*) FROM verification_logs WHERE status = 'verified'
                 AND created_at >= NOW() - INTERVAL '30 days') AS verified_month,
                (SELECT COUNT(*) FROM verification_logs WHERE status = 'invalid'
                 AND created_at >= NOW() - INTERVAL '30 days') AS invalid_month,
                (SELECT COUNT(*) FROM manual_reviews WHERE resolved_at IS NULL) AS pending_manual_reviews
            """
        )
        by_type = await conn.fetch(
            """
            SELECT document_type, status, COUNT(*) AS total
            FROM verification_logs
            WHERE created_at >= NOW() - INTERVAL '30 days'
            GROUP BY document_type, status ORDER BY document_type, status
            """
        )
        daily = await conn.fetch(
            """
            SELECT DATE(created_at) AS day, COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE status = 'verified') AS verified,
                   COUNT(*) FILTER (WHERE status = 'invalid') AS invalid
            FROM verification_logs
            WHERE created_at >= NOW() - INTERVAL '30 days'
            GROUP BY DATE(created_at) ORDER BY day DESC
            """
        )
        return {
            "summary": dict(summary),
            "by_document_type": [dict(r) for r in by_type],
            "daily_trend": [dict(r) for r in daily],
        }


# ── Manual Review ──────────────────────────────────────────────────────────────

@router.get("/manual-reviews")
async def list_manual_reviews(
    resolved: bool = False,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_admin_user),
):
    offset = (page - 1) * limit
    where = "WHERE mr.resolved_at IS NULL" if not resolved else "WHERE mr.resolved_at IS NOT NULL"

    async with get_conn() as conn:
        total = await conn.fetchval(f"SELECT COUNT(*) FROM manual_reviews mr {where}")
        rows = await conn.fetch(
            f"""
            SELECT mr.*, vl.document_type, vl.status, vl.confidence_score,
                   vl.conclusion, i.name AS institution_name
            FROM manual_reviews mr
            JOIN verification_logs vl ON vl.id = mr.verification_id
            LEFT JOIN institutions i ON i.id = vl.institution_id
            {where}
            ORDER BY mr.created_at DESC LIMIT %s OFFSET %s
            """,
            limit, offset,
        )
        return {"data": [dict(r) for r in rows], "total": total, "page": page, "limit": limit}


@router.post("/verifications/{verification_id}/reverify")
async def reverify_document(
    verification_id: UUID,
    request: Request,
    user: dict = Depends(get_admin_user),
):
    """Re-corre el pipeline de verificación sobre el archivo ya almacenado."""
    async with get_conn() as conn:
        row = await conn.fetchrow(
            "SELECT id, file_path, document_type, institution_id FROM verification_logs WHERE id = %s",
            str(verification_id),
        )
    if not row:
        raise HTTPException(status_code=404, detail="Verificación no encontrada")

    file_path = row["file_path"]
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=400, detail="Archivo no disponible para re-verificación")

    from routers.verify import run_verification_pipeline
    start = time.time() * 1000
    result = await run_verification_pipeline(file_path, row["document_type"], start)

    checks_json = json.dumps([c.model_dump() for c in result.checks])
    warnings_json = json.dumps(result.warnings)
    extracted_json = json.dumps(result.extracted_data, default=str)

    async with get_conn() as conn:
        await conn.execute(
            """
            UPDATE verification_logs SET
              status = %s, confidence_score = %s,
              extracted_data = %s::jsonb, checks = %s::jsonb, conclusion = %s,
              warnings = %s::jsonb, processing_time_ms = %s
            WHERE id = %s
            """,
            result.status.value, float(result.confidence_score),
            extracted_json, checks_json, result.conclusion,
            warnings_json, result.processing_time_ms,
            str(verification_id),
        )
        if result.status.value == "manual_review":
            await conn.execute(
                "INSERT INTO manual_reviews (verification_id) VALUES (%s) ON CONFLICT DO NOTHING",
                str(verification_id),
            )

    return result


@router.patch("/manual-reviews/{review_id}")
async def resolve_manual_review(
    review_id: UUID,
    body: ReviewDecision,
    user: dict = Depends(get_admin_user),
):
    if body.decision not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="decision debe ser 'approved' o 'rejected'")

    async with get_conn() as conn:
        row = await conn.fetchrow(
            """
            UPDATE manual_reviews
            SET decision = %s, notes = %s, assigned_to = %s, resolved_at = NOW()
            WHERE id = %s RETURNING *
            """,
            body.decision, body.notes, user.get("email"), str(review_id),
        )
        if not row:
            raise HTTPException(status_code=404, detail="Revisión no encontrada")
        return dict(row)
