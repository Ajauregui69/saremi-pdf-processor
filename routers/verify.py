"""
Router de verificación de documentos
Endpoints: POST /v1/verify/{ine,curp,bank-statement,proof-of-address,document}
Todos requieren X-API-Key válida.
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Optional

UPLOADS_DIR = Path(os.getenv("UPLOADS_DIR", str(Path(__file__).parent.parent / "uploads")))
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Security, UploadFile
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

from auth.api_key_auth import get_api_key
from models.verification_schemas import CheckItem, CheckStatus, VerificationResult, VerificationStatus
from services.conclusion_engine import compute_confidence, determine_status, generate_conclusion, extract_fraud_flags
from services.data_extractor import (
    extract_financial_data, extract_id_document_data, extract_proof_of_address_data,
    extract_payroll_data, extract_employment_letter_data, extract_tax_return_data,
    parse_mrz, decode_voter_id_date,
)
from services.pdf_processor import PDFProcessor
from services.qr_service import QRService
from services.verifiers.ine_verifier import INEVerifier
from services.verifiers.curp_verifier import CURPVerifier
from services.verifiers.bank_statement_verifier import BankStatementVerifier
from services.verifiers.proof_of_address_verifier import ProofOfAddressVerifier
from services.verifiers.csf_verifier import CSFVerifier
from services.verifiers.spei_verifier import SPEIVerifier
from services.verifiers.escritura_verifier import EscrituraVerifier
from services.verifiers.predial_verifier import PredialVerifier
from services.verifiers.passport_verifier import PassportVerifier
from services.verifiers.acta_nacimiento_verifier import ActaNacimientoVerifier
from services.verifiers.acta_matrimonio_verifier import ActaMatrimonioVerifier
from services.verifiers.acta_defuncion_verifier import ActaDefuncionVerifier
from services.verifiers.rfc_verifier import RFCVerifier
from services.verifiers.cfdi_verifier import CFDIVerifier
from services.verifiers.cert_libertad_gravamen_verifier import CertLibertadGravamenVerifier
from services.verifiers.avaluo_verifier import AvaluoVerifier
from services.verifiers.carta_no_adeudo_verifier import CartaNoAdeudoVerifier
from services.verifiers.licencia_verifier import LicenciaVerifier
from services.verifiers.fm_residencia_verifier import FMResidenciaVerifier
from services.verifiers.cedula_profesional_verifier import CedulaProfesionalVerifier

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/verify", tags=["verify"])

pdf_processor = PDFProcessor()
qr_service = QRService()

# Mapeo de tipo de documento → clase verificadora para documentos notariales.
# Usado por run_verification_pipeline y el endpoint /document auto-detect.
_NOTARIAL_VERIFIER_MAP = {
    "csf":                    CSFVerifier,
    "spei":                   SPEIVerifier,
    "escritura":              EscrituraVerifier,
    "predial":                PredialVerifier,
    "passport":               PassportVerifier,
    "passport_mx":            PassportVerifier,
    "passport_ext":           PassportVerifier,
    "acta_nacimiento":        ActaNacimientoVerifier,
    "acta_matrimonio":        ActaMatrimonioVerifier,
    "acta_defuncion":         ActaDefuncionVerifier,
    "rfc":                    RFCVerifier,
    "cfdi":                   CFDIVerifier,
    "cert_libertad_gravamen": CertLibertadGravamenVerifier,
    "avaluo":                 AvaluoVerifier,
    "carta_no_adeudo":        CartaNoAdeudoVerifier,
    "licencia":               LicenciaVerifier,
    "fm_residencia":          FMResidenciaVerifier,
    "cedula_profesional":     CedulaProfesionalVerifier,
}


# ── helpers ───────────────────────────────────────────────────────────────────

def _save_temp(file: UploadFile, suffix: str) -> str:
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        return tmp.name


def _extract_text_from_file(path: str) -> str:
    """Extrae texto de PDF o imagen. Para imágenes: Claude Vision → pytesseract."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".jpg", ".jpeg", ".png", ".webp"):
        # Intentar Claude Vision primero
        from services.vision_extractor import extract_text_with_vision
        vision_text = extract_text_with_vision(path)
        if vision_text and len(vision_text) > 30:
            logger.info(f"✅ Vision OCR: {len(vision_text)} chars")
            return vision_text
        # Fallback pytesseract
        try:
            import pytesseract
            from PIL import Image as PILImage
            img = PILImage.open(path)
            text = pytesseract.image_to_string(img, lang="spa+eng")
            logger.info(f"✅ Tesseract OCR: {len(text)} chars")
            return text.strip()
        except Exception as e:
            logger.warning(f"OCR fallido en imagen: {e}")
            return ""
    try:
        return pdf_processor.extract_text(path)
    except Exception as e:
        logger.warning(f"Error extrayendo texto: {e}")
        return ""

# alias backward compat
_extract_text_from_pdf = _extract_text_from_file


def _file_hash(path: str) -> str:
    """SHA-256 del archivo para audit trail."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _persist_file(tmp_path: str, doc_hash: str, suffix: str) -> str | None:
    """Copia el archivo temporal a uploads/ usando el hash como nombre. Retorna la ruta."""
    try:
        dest = UPLOADS_DIR / f"{doc_hash}{suffix}"
        if not dest.exists():
            shutil.copy2(tmp_path, dest)
        return str(dest)
    except Exception as e:
        logger.warning(f"No se pudo guardar el archivo: {e}")
        return None


# ── registro en blockchain (BaaS / Hyperledger Fabric) ──────────────────────────

# URL del BaaS y API-Key propia de SarEmi para el endpoint /external/records.
# La API-Key debe existir en baas-qro con una blockchain asignada.
_BAAS_API_URL = os.getenv("BAAS_API_URL", "").rstrip("/")
_BAAS_EXTERNAL_API_KEY = os.getenv("BAAS_EXTERNAL_API_KEY", "")
_BLOCKCHAIN_TIMEOUT = int(os.getenv("BLOCKCHAIN_TIMEOUT_SECONDS", "20"))


async def _register_on_blockchain(result: VerificationResult, doc_hash: str) -> None:
    """
    Registra el hash del documento + conclusión en la blockchain vía baas-qro.
    Fire-and-forget: cualquier error se loguea pero NUNCA interrumpe la verificación.
    Aplica a TODOS los tipos de documento (se llama desde _save_log).
    """
    if not _BAAS_API_URL or not _BAAS_EXTERNAL_API_KEY:
        logger.debug("Registro en blockchain omitido: BAAS_API_URL o BAAS_EXTERNAL_API_KEY no configurados")
        return

    payload = {
        "documentHash": doc_hash,
        "documentType": result.document_type,
        "conclusion": result.conclusion,
        "confidence": result.confidence_score,
        "livoStatus": result.status.value,
        "metadata": {
            "fraud_flags": [f.model_dump() for f in result.fraud_flags],
            "processing_time_ms": result.processing_time_ms,
        },
    }

    try:
        import httpx
        async with httpx.AsyncClient(timeout=_BLOCKCHAIN_TIMEOUT) as client:
            resp = await client.post(
                f"{_BAAS_API_URL}/api/v1/external/records",
                json=payload,
                headers={"X-API-Key": _BAAS_EXTERNAL_API_KEY},
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                logger.info(
                    f"✅ Documento registrado en blockchain: txHash={data.get('txHash')} "
                    f"block={data.get('blockNumber')} hash={doc_hash[:12]}…"
                )
            elif resp.status_code == 503:
                logger.warning("Red blockchain no disponible en baas-qro — registro omitido")
            else:
                logger.warning(
                    f"baas-qro rechazó el registro en blockchain (HTTP {resp.status_code}): {resp.text[:200]}"
                )
    except Exception as e:
        logger.warning(f"No se pudo registrar el documento en blockchain: {e}")


async def _save_log(
    result: VerificationResult,
    institution_id: str,
    doc_hash: str,
    request: Request,
    file_path: str | None = None,
    original_filename: str | None = None,
    pending_id: str | None = None,
    client_reference_id: str | None = None,
) -> str | None:
    """Guarda el resultado en verification_logs. Si se pasa pending_id, actualiza ese registro."""
    # Registrar en blockchain (independiente de la persistencia en PostgreSQL):
    # un fallo de DB no impide el registro en cadena, y viceversa. Aplica a TODOS
    # los tipos de documento porque todos los endpoints llaman a _save_log.
    await _register_on_blockchain(result, doc_hash)

    def _strip_nul(s: str) -> str:
        """Elimina bytes NUL que PostgreSQL no acepta en strings."""
        return s.replace("\x00", "") if isinstance(s, str) else s

    try:
        from db_helpers import get_conn
        ip = request.client.host if request.client else None
        checks_json = _strip_nul(json.dumps([c.model_dump() for c in result.checks]))
        warnings_json = _strip_nul(json.dumps(result.warnings))
        extracted_json = _strip_nul(json.dumps(result.extracted_data, default=str))

        async with get_conn() as conn:
            if pending_id:
                await conn.execute(
                    """
                    UPDATE verification_logs SET
                      document_type = %s, status = %s, confidence_score = %s,
                      extracted_data = %s::jsonb, checks = %s::jsonb, conclusion = %s,
                      warnings = %s::jsonb, processing_time_ms = %s, document_hash = %s,
                      file_path = COALESCE(%s, file_path),
                      original_filename = COALESCE(%s, original_filename),
                      client_reference_id = COALESCE(%s, client_reference_id)
                    WHERE id = %s
                    """,
                    result.document_type,
                    result.status.value,
                    float(result.confidence_score),
                    extracted_json,
                    checks_json,
                    _strip_nul(result.conclusion or ""),
                    warnings_json,
                    result.processing_time_ms,
                    doc_hash,
                    file_path,
                    original_filename,
                    client_reference_id,
                    pending_id,
                )
                log_id = pending_id
                logger.info(f"Verificación actualizada en DB (pending→{result.status.value}), id={log_id}")
            else:
                inst_row = await conn.fetchrow(
                    "SELECT id FROM institutions WHERE id = %s", institution_id
                )
                inst_pk = str(inst_row["id"]) if inst_row else None

                log_id = await conn.fetchval(
                    """
                    INSERT INTO verification_logs
                      (institution_id, document_type, status, confidence_score,
                       extracted_data, checks, conclusion, warnings,
                       processing_time_ms, document_hash, ip_address, file_path,
                       original_filename, client_reference_id)
                    VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s::jsonb, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    inst_pk,
                    result.document_type,
                    result.status.value,
                    float(result.confidence_score),
                    extracted_json,
                    checks_json,
                    _strip_nul(result.conclusion or ""),
                    warnings_json,
                    result.processing_time_ms,
                    doc_hash,
                    ip,
                    file_path,
                    original_filename,
                    client_reference_id,
                )
                log_id = str(log_id) if log_id else None
                logger.info(f"Verificación guardada en DB para institución {institution_id}, id={log_id}")

            if log_id and result.status.value == "manual_review":
                await conn.execute(
                    "INSERT INTO manual_reviews (verification_id) VALUES (%s) ON CONFLICT DO NOTHING",
                    str(log_id),
                )
            return str(log_id) if log_id else None
    except Exception as e:
        logger.error(f"Error guardando log de verificación: {e}")
        return None


def _build_result(
    doc_type: str,
    checks,
    extracted_data: dict,
    start_ms: float,
    warnings: list[str] | None = None,
) -> VerificationResult:
    confidence = compute_confidence(checks)
    status = determine_status(confidence, checks)
    conclusion = generate_conclusion(status, checks, doc_type, extracted_data)
    fraud_flags = extract_fraud_flags(checks)
    elapsed = int((time.time() * 1000) - start_ms)
    return VerificationResult(
        document_type=doc_type,
        status=status,
        confidence_score=round(confidence, 3),
        extracted_data=extracted_data,
        checks=checks,
        conclusion=conclusion,
        warnings=warnings or [],
        fraud_flags=fraud_flags,
        processing_time_ms=elapsed,
    )


async def run_verification_pipeline(file_path: str, doc_type: str, start_ms: float) -> VerificationResult:
    """
    Corre el pipeline de extracción + verificación sobre un archivo ya almacenado.
    Usado por el endpoint de re-verificación del admin.
    """
    suffix = os.path.splitext(file_path)[1].lower()
    raw_text = _extract_text_from_file(file_path)

    if doc_type == "ine":
        extracted = extract_id_document_data(raw_text)
        if suffix in (".jpg", ".jpeg", ".png", ".webp", ".pdf") and os.getenv("ANTHROPIC_API_KEY"):
            from services.vision_extractor import extract_ine_data_with_vision
            vision_path = file_path
            if suffix == ".pdf":
                try:
                    from pdf2image import convert_from_path
                    from PIL import Image as _PILImage
                    import tempfile
                    pages = convert_from_path(file_path, dpi=200, first_page=1, last_page=2)
                    if pages:
                        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as vf:
                            vision_path = vf.name
                        if len(pages) >= 2:
                            total_h = pages[0].height + pages[1].height
                            combined = _PILImage.new("RGB", (max(pages[0].width, pages[1].width), total_h))
                            combined.paste(pages[0], (0, 0))
                            combined.paste(pages[1], (0, pages[0].height))
                            combined.save(vision_path, "PNG")
                        else:
                            pages[0].save(vision_path, "PNG")
                except Exception:
                    pass
            vision_data = extract_ine_data_with_vision(vision_path)
            if vision_path != file_path:
                try:
                    os.unlink(vision_path)
                except OSError:
                    pass
            if vision_data:
                extracted.update(vision_data)
                logger.info(f"✅ Vision INE pipeline (override OCR): {list(vision_data.keys())}")
        extracted["_raw_text"] = raw_text
        checks = await INEVerifier().verify(file_path, extracted)
        extracted.pop("_raw_text", None)

    elif doc_type == "curp":
        extracted = extract_id_document_data(raw_text)
        extracted["_raw_text"] = raw_text
        checks = await CURPVerifier().verify(file_path, extracted)
        extracted.pop("_raw_text", None)

    elif doc_type == "bank_statement":
        extracted = extract_financial_data(raw_text, "bank_statement")
        extracted["_raw_text"] = raw_text
        qr_codes = []
        try:
            page_images = pdf_processor.convert_to_images(file_path)
            qr_codes = qr_service.scan_images(page_images)
        except Exception:
            pass
        checks = await BankStatementVerifier(qr_codes=qr_codes).verify(file_path, extracted)
        extracted.pop("_raw_text", None)

    elif doc_type == "proof_of_address":
        extracted = extract_proof_of_address_data(raw_text)
        extracted["_raw_text"] = raw_text
        checks = await ProofOfAddressVerifier().verify(file_path, extracted)
        extracted.pop("_raw_text", None)

    elif doc_type in ("payroll", "income_proof"):
        extracted = extract_payroll_data(raw_text)
        if (not extracted.get("employee_name") or not extracted.get("net_salary")) and suffix in (".jpg", ".jpeg", ".png", ".webp", ".pdf"):
            vision_data = await asyncio.to_thread(_extract_payroll_vision_sync, file_path, suffix)
            if vision_data:
                extracted.update(vision_data)
        payroll_qr: list = []
        try:
            from services.qr_service import QRService as _QRSvc2
            _page_imgs = pdf_processor.convert_to_images(file_path)
            payroll_qr = _QRSvc2().scan_images(_page_imgs)
        except Exception:
            pass
        extracted["_raw_text"] = raw_text
        checks = _build_payroll_checks_inline(extracted, qr_codes=payroll_qr)
        checks.extend(await _fraud_analysis(file_path, doc_type, extracted, preloaded_qr=payroll_qr))
        extracted.pop("_raw_text", None)

    elif doc_type in _NOTARIAL_VERIFIER_MAP:
        verifier_cls = _NOTARIAL_VERIFIER_MAP[doc_type]
        extracted = {"_raw_text": raw_text}
        qr_codes: list = []
        try:
            page_images = pdf_processor.convert_to_images(file_path)
            qr_codes = qr_service.scan_images(page_images)
        except Exception:
            pass
        checks = await verifier_cls().verify(file_path, extracted, preloaded_qr_codes=qr_codes)
        extracted.pop("_raw_text", None)

    else:
        extracted = extract_id_document_data(raw_text) or extract_financial_data(raw_text, "document")
        extracted["_raw_text"] = raw_text
        checks = await ProofOfAddressVerifier().verify(file_path, extracted)
        extracted.pop("_raw_text", None)

    return _build_result(doc_type, checks, extracted, start_ms)


# ── endpoints ─────────────────────────────────────────────────────────────────

@router.post("/pending")
async def register_pending(
    request: Request,
    document_type: str = Form(default="document"),
    original_filename: str = Form(default=""),
    client_reference_id: str = Form(default=""),
    institution_id: str = Security(get_api_key),
):
    """
    Crea un registro 'processing' antes de que el análisis termine.
    Llamar inmediatamente al recibir el documento; retorna { id } para pasarlo al endpoint real.
    client_reference_id: identificador del usuario en el sistema del cliente (e.g. el userId en el sistema del cliente).
    """
    ip = request.client.host if request.client else None
    ref_id = client_reference_id.strip() or None
    try:
        from db_helpers import get_conn
        async with get_conn() as conn:
            inst_row = await conn.fetchrow(
                "SELECT id FROM institutions WHERE id = %s", institution_id
            )
            inst_pk = str(inst_row["id"]) if inst_row else None
            log_id = await conn.fetchval(
                """
                INSERT INTO verification_logs
                  (institution_id, document_type, status, confidence_score,
                   extracted_data, checks, conclusion, warnings,
                   processing_time_ms, document_hash, ip_address, file_path,
                   original_filename, client_reference_id)
                VALUES (%s, %s, 'processing', 0,
                        '{}'::jsonb, '[]'::jsonb, 'Documento en análisis...', '[]'::jsonb,
                        0, '', %s, NULL, %s, %s)
                RETURNING id
                """,
                inst_pk, document_type, ip, original_filename or None, ref_id,
            )
            logger.info(f"Registro pending creado para {institution_id} (ref={ref_id}): {log_id}")
            return {"id": str(log_id)}
    except Exception as e:
        logger.error(f"Error en register_pending: {e}")
        raise HTTPException(status_code=500, detail="Error al registrar documento pendiente")


@router.post("/ine", response_model=VerificationResult)
async def verify_ine(
    request: Request,
    file: UploadFile = File(...),
    institution_id: str = Security(get_api_key),
    original_filename: str = Form(default=""),
    pending_id: str = Form(default=""),
    client_reference_id: str = Form(default=""),
):
    """Verifica una INE / Credencial para Votar."""
    logger.info(f"[{institution_id}] Verificando INE: {file.filename}")
    start = time.time() * 1000
    tmp_path = None
    try:
        suffix = ".pdf" if (file.filename or "").lower().endswith(".pdf") else os.path.splitext(file.filename or "")[1] or ".pdf"
        tmp_path = _save_temp(file, suffix)
        doc_hash = _file_hash(tmp_path)
        stored_path = _persist_file(tmp_path, doc_hash, suffix)
        raw_text = _extract_text_from_pdf(tmp_path)
        extracted = extract_id_document_data(raw_text)

        # Convertir PDF a páginas PIL una sola vez — se reutilizan para Vision y QR
        pages: list = []
        if suffix == ".pdf":
            try:
                from pdf2image import convert_from_path
                pages = convert_from_path(tmp_path, dpi=300, first_page=1, last_page=2)
            except Exception as e:
                logger.warning(f"pdf2image falló: {e}")

        # Siempre correr Claude Vision para INE — los escaneos generan OCR corrupto.
        # Vision tiene prioridad sobre OCR en todos los campos clave.
        if suffix in (".jpg", ".jpeg", ".png", ".webp", ".pdf") and os.getenv("ANTHROPIC_API_KEY"):
            from services.vision_extractor import extract_ine_data_with_vision
            from PIL import Image as _PILImage
            vision_path = tmp_path
            if suffix == ".pdf" and pages:
                try:
                    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as vf:
                        vision_path = vf.name
                    if len(pages) >= 2:
                        # Combinar ambas páginas verticalmente para que Vision vea frente y reverso
                        total_h = pages[0].height + pages[1].height
                        combined = _PILImage.new("RGB", (max(pages[0].width, pages[1].width), total_h))
                        combined.paste(pages[0], (0, 0))
                        combined.paste(pages[1], (0, pages[0].height))
                        combined.save(vision_path, "PNG")
                    else:
                        pages[0].save(vision_path, "PNG")
                except Exception:
                    pass
            vision_data = extract_ine_data_with_vision(vision_path)
            if vision_path != tmp_path:
                try:
                    os.unlink(vision_path)
                except OSError:
                    pass
            if vision_data:
                # Vision siempre gana sobre OCR en campos estructurados de INE
                extracted.update(vision_data)
                logger.info(f"✅ Vision estructurado INE (override OCR): {list(vision_data.keys())}")

        # Post-Vision: parsear MRZ con líneas que Vision extrajo (si OCR no las encontró)
        if not extracted.get("mrz"):
            l1 = extracted.get("mrz_line1", "")
            l2 = extracted.get("mrz_line2", "")
            l3 = extracted.get("mrz_line3", "")
            if l1 and l2 and l3:
                mrz_parsed = parse_mrz(f"{l1}\n{l2}\n{l3}")
                if mrz_parsed:
                    extracted["mrz"] = mrz_parsed
                    if mrz_parsed.get("dob_mrz"):
                        extracted["dob_mrz"] = mrz_parsed["dob_mrz"]
                    if mrz_parsed.get("name_mrz"):
                        extracted["name_mrz"] = mrz_parsed["name_mrz"]
                    if mrz_parsed.get("expiry_year_mrz"):
                        extracted["expiry_year_mrz"] = mrz_parsed["expiry_year_mrz"]
                    logger.info(f"✅ MRZ parseada desde campos Vision: DOB={mrz_parsed.get('dob_mrz')}")

        # Post-Vision: recalcular fecha en clave de elector si Vision mejoró el voter_id
        voter_id_final = extracted.get("voter_id", "")
        if voter_id_final and not extracted.get("dob_clave_elector"):
            clave_date = decode_voter_id_date(voter_id_final)
            if clave_date:
                extracted["dob_clave_elector"] = clave_date
                logger.info(f"✅ Fecha clave elector (post-Vision): {clave_date}")

        # Pre-escanear QR — usa las páginas PIL ya generadas (evita re-renderizar el PDF)
        preloaded_qr: list = []
        try:
            from services.qr_service import QRService as _QRSvc
            if suffix == ".pdf" and pages:
                preloaded_qr = _QRSvc().scan_images(pages)
            elif suffix in (".jpg", ".jpeg", ".png", ".webp"):
                from PIL import Image as _PILImg2
                preloaded_qr = _QRSvc().scan_images([_PILImg2.open(tmp_path)])
            if preloaded_qr:
                logger.info(f"QR pre-escaneado: {len(preloaded_qr)} código(s) encontrado(s)")
        except Exception as e:
            logger.warning(f"QR pre-scan falló: {e}")

        extracted["_raw_text"] = raw_text
        verifier = INEVerifier()
        checks = await verifier.verify(tmp_path, extracted, preloaded_qr_codes=preloaded_qr)
        extracted.pop("_raw_text", None)

        result = _build_result("ine", checks, extracted, start)
        await _save_log(result, institution_id, doc_hash, request, file_path=stored_path, original_filename=original_filename or file.filename, pending_id=pending_id or None, client_reference_id=client_reference_id.strip() or None)
        return result
    except Exception as e:
        logger.error(f"Error verificando INE: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


class CURPRequest(BaseModel):
    curp: str
    full_name: Optional[str] = None


@router.post("/curp", response_model=VerificationResult)
async def verify_curp(
    request: Request,
    institution_id: str = Security(get_api_key),
    file: Optional[UploadFile] = File(default=None),
    curp: Optional[str] = Form(default=None),
    full_name: Optional[str] = Form(default=None),
    original_filename: str = Form(default=""),
    pending_id: str = Form(default=""),
    client_reference_id: str = Form(default=""),
):
    """Verifica un CURP. Acepta archivo PDF o campos {curp, full_name}."""
    logger.info(f"[{institution_id}] Verificando CURP")
    start = time.time() * 1000
    tmp_path = None
    extracted: dict = {}

    try:
        if file and file.filename:
            suffix = os.path.splitext(file.filename)[1] or ".pdf"
            tmp_path = _save_temp(file, suffix)
            raw_text = _extract_text_from_pdf(tmp_path)
            extracted = extract_id_document_data(raw_text)
        elif curp:
            extracted = {"curp": curp.strip().upper()}
            if full_name:
                extracted["full_name"] = full_name.strip()
        else:
            raise HTTPException(status_code=400, detail="Se requiere un archivo o el campo 'curp'")

        doc_hash = _file_hash(tmp_path) if tmp_path else hashlib.sha256(extracted.get("curp", "").encode()).hexdigest()
        stored_path = _persist_file(tmp_path, doc_hash, os.path.splitext(file.filename or "")[1] or ".pdf") if tmp_path else None
        verifier = CURPVerifier()
        checks = await verifier.verify(tmp_path or "", extracted)

        result = _build_result("curp", checks, extracted, start)
        await _save_log(result, institution_id, doc_hash, request, file_path=stored_path, original_filename=original_filename or (file.filename if file else None), pending_id=pending_id or None, client_reference_id=client_reference_id.strip() or None)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error verificando CURP: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


@router.post("/bank-statement", response_model=VerificationResult)
async def verify_bank_statement(
    request: Request,
    file: UploadFile = File(...),
    institution_id: str = Security(get_api_key),
    original_filename: str = Form(default=""),
    pending_id: str = Form(default=""),
    client_reference_id: str = Form(default=""),
):
    """Verifica un estado de cuenta bancario."""
    logger.info(f"[{institution_id}] Verificando estado de cuenta: {file.filename}")
    start = time.time() * 1000
    tmp_path = None

    try:
        tmp_path = _save_temp(file, ".pdf")
        doc_hash = _file_hash(tmp_path)
        stored_path = _persist_file(tmp_path, doc_hash, ".pdf")
        raw_text = _extract_text_from_pdf(tmp_path)
        extracted = extract_financial_data(raw_text, "bank_statement")
        extracted["_raw_text"] = raw_text

        qr_codes = []
        try:
            page_images = pdf_processor.convert_to_images(tmp_path)
            qr_codes = qr_service.scan_images(page_images)
        except Exception as e:
            logger.warning(f"Error escaneando QR: {e}")

        verifier = BankStatementVerifier(qr_codes=qr_codes)
        checks = await verifier.verify(tmp_path, extracted)
        extracted.pop("_raw_text", None)

        result = _build_result("bank_statement", checks, extracted, start)
        await _save_log(result, institution_id, doc_hash, request, file_path=stored_path, original_filename=original_filename or file.filename, pending_id=pending_id or None, client_reference_id=client_reference_id.strip() or None)
        return result
    except Exception as e:
        logger.error(f"Error verificando estado de cuenta: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


@router.post("/proof-of-address", response_model=VerificationResult)
async def verify_proof_of_address(
    request: Request,
    file: UploadFile = File(...),
    institution_id: str = Security(get_api_key),
    original_filename: str = Form(default=""),
    pending_id: str = Form(default=""),
    client_reference_id: str = Form(default=""),
):
    """Verifica un comprobante de domicilio."""
    logger.info(f"[{institution_id}] Verificando comprobante de domicilio: {file.filename}")
    start = time.time() * 1000
    tmp_path = None

    try:
        tmp_path = _save_temp(file, ".pdf")
        doc_hash = _file_hash(tmp_path)
        stored_path = _persist_file(tmp_path, doc_hash, ".pdf")
        raw_text = _extract_text_from_pdf(tmp_path)
        extracted = extract_proof_of_address_data(raw_text)
        extracted["_raw_text"] = raw_text

        verifier = ProofOfAddressVerifier()
        checks = await verifier.verify(tmp_path, extracted)
        extracted.pop("_raw_text", None)

        result = _build_result("proof_of_address", checks, extracted, start)
        await _save_log(result, institution_id, doc_hash, request, file_path=stored_path, original_filename=original_filename or file.filename, pending_id=pending_id or None, client_reference_id=client_reference_id.strip() or None)
        return result
    except Exception as e:
        logger.error(f"Error verificando comprobante: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _generic_file_endpoint(doc_type: str, verifier_cls, extractor_fn=None):
    """
    Genera una función de endpoint genérica para verificadores de archivos.
    Todos los documentos notariales siguen el mismo patrón: file → OCR → verify → log.
    """
    async def _endpoint(
        request: Request,
        file: UploadFile = File(...),
        institution_id: str = Security(get_api_key),
        original_filename: str = Form(default=""),
        pending_id: str = Form(default=""),
        client_reference_id: str = Form(default=""),
    ):
        logger.info(f"[{institution_id}] Verificando {doc_type}: {file.filename}")
        start = time.time() * 1000
        tmp_path = None
        try:
            suffix = os.path.splitext(file.filename or "")[1] or ".pdf"
            tmp_path = _save_temp(file, suffix)
            doc_hash = _file_hash(tmp_path)
            stored_path = _persist_file(tmp_path, doc_hash, suffix)
            raw_text = _extract_text_from_file(tmp_path)

            extracted = extractor_fn(raw_text) if extractor_fn else {}
            extracted["_raw_text"] = raw_text

            # Pre-escanear QR
            qr_codes: list = []
            try:
                page_images = pdf_processor.convert_to_images(tmp_path)
                qr_codes = qr_service.scan_images(page_images)
            except Exception:
                pass

            verifier = verifier_cls()
            checks = await verifier.verify(tmp_path, extracted, preloaded_qr_codes=qr_codes)
            extracted.pop("_raw_text", None)

            result = _build_result(doc_type, checks, extracted, start)
            await _save_log(
                result, institution_id, doc_hash, request,
                file_path=stored_path,
                original_filename=original_filename or file.filename,
                pending_id=pending_id or None,
                client_reference_id=client_reference_id.strip() or None,
            )
            return result
        except Exception as e:
            logger.error(f"Error verificando {doc_type}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    _endpoint.__name__ = f"verify_{doc_type}"
    return _endpoint


def _extract_generic_text(raw_text: str) -> dict:
    return {}


# ── Endpoints notariales ──────────────────────────────────────────────────────

router.post("/csf", response_model=VerificationResult, summary="Verifica Constancia de Situación Fiscal")(
    _generic_file_endpoint("csf", CSFVerifier, lambda t: {"_raw_text": t})
)

router.post("/spei", response_model=VerificationResult, summary="Verifica comprobante SPEI")(
    _generic_file_endpoint("spei", SPEIVerifier, _extract_generic_text)
)

router.post("/escritura", response_model=VerificationResult, summary="Verifica Escritura Pública")(
    _generic_file_endpoint("escritura", EscrituraVerifier, _extract_generic_text)
)

router.post("/predial", response_model=VerificationResult, summary="Verifica Boleta Predial")(
    _generic_file_endpoint("predial", PredialVerifier, _extract_generic_text)
)

router.post("/passport", response_model=VerificationResult, summary="Verifica Pasaporte (MX o extranjero)")(
    _generic_file_endpoint("passport", PassportVerifier, _extract_generic_text)
)

router.post("/acta-nacimiento", response_model=VerificationResult, summary="Verifica Acta de Nacimiento")(
    _generic_file_endpoint("acta_nacimiento", ActaNacimientoVerifier, _extract_generic_text)
)

router.post("/acta-matrimonio", response_model=VerificationResult, summary="Verifica Acta de Matrimonio")(
    _generic_file_endpoint("acta_matrimonio", ActaMatrimonioVerifier, _extract_generic_text)
)

router.post("/acta-defuncion", response_model=VerificationResult, summary="Verifica Acta de Defunción")(
    _generic_file_endpoint("acta_defuncion", ActaDefuncionVerifier, _extract_generic_text)
)

router.post("/rfc", response_model=VerificationResult, summary="Verifica RFC (SAT + listas 69/69-B)")(
    _generic_file_endpoint("rfc", RFCVerifier, _extract_generic_text)
)

router.post("/cfdi", response_model=VerificationResult, summary="Verifica CFDI / Factura Electrónica")(
    _generic_file_endpoint("cfdi", CFDIVerifier, _extract_generic_text)
)

router.post("/cert-libertad-gravamen", response_model=VerificationResult, summary="Verifica Certificado de Libertad de Gravamen")(
    _generic_file_endpoint("cert_libertad_gravamen", CertLibertadGravamenVerifier, _extract_generic_text)
)

router.post("/avaluo", response_model=VerificationResult, summary="Verifica Avalúo Inmobiliario")(
    _generic_file_endpoint("avaluo", AvaluoVerifier, _extract_generic_text)
)

router.post("/carta-no-adeudo", response_model=VerificationResult, summary="Verifica Carta de No Adeudo")(
    _generic_file_endpoint("carta_no_adeudo", CartaNoAdeudoVerifier, _extract_generic_text)
)

router.post("/licencia", response_model=VerificationResult, summary="Verifica Licencia de Conducir")(
    _generic_file_endpoint("licencia", LicenciaVerifier, _extract_generic_text)
)

router.post("/fm-residencia", response_model=VerificationResult, summary="Verifica Tarjeta de Residencia / FM")(
    _generic_file_endpoint("fm_residencia", FMResidenciaVerifier, _extract_generic_text)
)

router.post("/cedula-profesional", response_model=VerificationResult, summary="Verifica Cédula Profesional")(
    _generic_file_endpoint("cedula_profesional", CedulaProfesionalVerifier, _extract_generic_text)
)


@router.post("/document", response_model=VerificationResult)
async def verify_document_auto(
    request: Request,
    file: UploadFile = File(...),
    institution_id: str = Security(get_api_key),
    document_type_hint: str = Form(default=""),
    original_filename: str = Form(default=""),
    pending_id: str = Form(default=""),
    client_reference_id: str = Form(default=""),
):
    """
    Verificación automática. Si auto-detect no reconoce el tipo,
    usa document_type_hint (tipo original del cliente) para etiquetar correctamente.
    """
    logger.info(f"[{institution_id}] Verificación auto-detect: {file.filename} hint={document_type_hint or 'none'}")
    start = time.time() * 1000
    tmp_path = None

    try:
        suffix = os.path.splitext(file.filename or "")[1] or ".pdf"
        tmp_path = _save_temp(file, suffix)
        doc_hash = _file_hash(tmp_path)
        stored_path = _persist_file(tmp_path, doc_hash, suffix)
        raw_text = _extract_text_from_pdf(tmp_path)
        raw_lower = raw_text.lower()

        # El hint del cliente tiene prioridad sobre el auto-detect de keywords
        hint = document_type_hint.strip()
        _KNOWN_TYPES = {
            "ine", "curp", "bank_statement", "proof_of_address", "payroll", "income_proof",
            "employment_letter", "tax_return", "csf", "spei", "escritura", "predial",
            "acta_nacimiento", "acta_matrimonio", "acta_defuncion", "rfc", "cfdi",
            "cert_libertad_gravamen", "avaluo", "carta_no_adeudo", "passport",
            "licencia", "fm_residencia", "cedula_profesional",
        }
        if hint in _KNOWN_TYPES:
            doc_type = hint
            logger.info(f"Usando hint del cliente: {doc_type}")
        else:
            doc_type = _detect_document_type(raw_lower)
            # Si el texto no fue suficiente, intentar clasificar con Claude Vision
            if doc_type == "unknown" and suffix in (".jpg", ".jpeg", ".png", ".webp", ".pdf"):
                doc_type = _classify_with_vision(tmp_path) or "unknown"
            logger.info(f"Tipo detectado (keywords+vision): {doc_type}")

        if doc_type == "ine":
            from services.data_extractor import extract_id_document_data as _eid
            extracted = _eid(raw_lower)
            verifier = INEVerifier()
            checks = await verifier.verify(tmp_path, extracted)
            result = _build_result(doc_type, checks, extracted, start)

        elif doc_type == "bank_statement":
            extracted = extract_financial_data(raw_lower, "bank_statement")
            extracted["_raw_text"] = raw_lower
            qr_codes = []
            try:
                page_images = pdf_processor.convert_to_images(tmp_path)
                qr_codes = qr_service.scan_images(page_images)
            except Exception:
                pass
            verifier = BankStatementVerifier(qr_codes=qr_codes)
            checks = await verifier.verify(tmp_path, extracted)
            extracted.pop("_raw_text", None)
            result = _build_result(doc_type, checks, extracted, start)

        elif doc_type == "proof_of_address":
            extracted = extract_proof_of_address_data(raw_lower)
            extracted["_raw_text"] = raw_lower
            verifier = ProofOfAddressVerifier()
            checks = await verifier.verify(tmp_path, extracted)
            extracted.pop("_raw_text", None)
            result = _build_result(doc_type, checks, extracted, start)

        elif doc_type in ("payroll", "income_proof"):
            extracted = extract_payroll_data(raw_text)
            if (not extracted.get("employee_name") or not extracted.get("net_salary")) and suffix in (".jpg", ".jpeg", ".png", ".webp", ".pdf"):
                vision_data = await asyncio.to_thread(_extract_payroll_vision_sync, tmp_path, suffix)
                if vision_data:
                    extracted.update(vision_data)
                    logger.info(f"Vision nómina campos: {list(vision_data.keys())}")
            payroll_qr2: list = []
            try:
                from services.qr_service import QRService as _QRSvc3
                _pi2 = pdf_processor.convert_to_images(tmp_path)
                payroll_qr2 = _QRSvc3().scan_images(_pi2)
            except Exception:
                pass
            extracted["_raw_text"] = raw_text
            checks = _build_payroll_checks_inline(extracted, qr_codes=payroll_qr2)
            checks.extend(await _fraud_analysis(tmp_path, doc_type, extracted, preloaded_qr=payroll_qr2))
            extracted.pop("_raw_text", None)
            result = _build_result(doc_type, checks, extracted, start)

        elif doc_type in _NOTARIAL_VERIFIER_MAP:
            # Todos los documentos notariales: OCR → verifier → result
            verifier_cls = _NOTARIAL_VERIFIER_MAP[doc_type]
            extracted = {"_raw_text": raw_text}
            notarial_qr: list = []
            try:
                page_images = pdf_processor.convert_to_images(tmp_path)
                notarial_qr = qr_service.scan_images(page_images)
            except Exception:
                pass
            checks = await verifier_cls().verify(tmp_path, extracted, preloaded_qr_codes=notarial_qr)
            extracted.pop("_raw_text", None)
            result = _build_result(doc_type, checks, extracted, start)

        else:
            # employment_letter, tax_return, curp o truly unknown
            # Map doc_type → (extractor_fn, check_builder)
            def _build_payroll_checks(ext: dict) -> list[CheckItem]:
                checks = []
                checks.append(CheckItem(
                    name="nombre_empleado",
                    status=CheckStatus.PASSED if ext.get("employee_name") else CheckStatus.WARNING,
                    detail=f"Empleado: {ext['employee_name']}" if ext.get("employee_name") else "No se detectó nombre del empleado",
                ))
                checks.append(CheckItem(
                    name="salario_neto",
                    status=CheckStatus.PASSED if ext.get("net_salary") else CheckStatus.WARNING,
                    detail=f"Salario neto: ${ext['net_salary']:,.2f}" if ext.get("net_salary") else "No se detectó salario neto",
                ))
                checks.append(CheckItem(
                    name="salario_bruto",
                    status=CheckStatus.PASSED if ext.get("gross_salary") else CheckStatus.SKIPPED,
                    detail=f"Salario bruto: ${ext['gross_salary']:,.2f}" if ext.get("gross_salary") else "Salario bruto no encontrado",
                ))
                checks.append(CheckItem(
                    name="rfc_empleado",
                    status=CheckStatus.PASSED if ext.get("employee_rfc") else CheckStatus.WARNING,
                    detail=f"RFC: {ext['employee_rfc']}" if ext.get("employee_rfc") else "RFC no detectado",
                ))
                checks.append(CheckItem(
                    name="empresa_empleadora",
                    status=CheckStatus.PASSED if ext.get("employer_name") else CheckStatus.WARNING,
                    detail=f"Empresa: {ext['employer_name']}" if ext.get("employer_name") else "Nombre de empresa no detectado",
                ))
                return checks

            def _build_employment_letter_checks(ext: dict) -> list[CheckItem]:
                checks = []
                checks.append(CheckItem(
                    name="empresa",
                    status=CheckStatus.PASSED if ext.get("employer_name") else CheckStatus.WARNING,
                    detail=f"Empresa: {ext['employer_name']}" if ext.get("employer_name") else "Nombre de empresa no encontrado",
                ))
                checks.append(CheckItem(
                    name="cargo_puesto",
                    status=CheckStatus.PASSED if ext.get("position") else CheckStatus.WARNING,
                    detail=f"Cargo: {ext['position']}" if ext.get("position") else "Cargo no detectado",
                ))
                checks.append(CheckItem(
                    name="fecha_ingreso",
                    status=CheckStatus.PASSED if ext.get("start_date") else CheckStatus.SKIPPED,
                    detail=f"Fecha de ingreso: {ext['start_date']}" if ext.get("start_date") else "Fecha de ingreso no encontrada",
                ))
                return checks

            def _build_tax_return_checks(ext: dict) -> list[CheckItem]:
                checks = []
                checks.append(CheckItem(
                    name="rfc",
                    status=CheckStatus.PASSED if ext.get("rfc") else CheckStatus.WARNING,
                    detail=f"RFC: {ext['rfc']}" if ext.get("rfc") else "RFC no detectado",
                ))
                checks.append(CheckItem(
                    name="ingreso_anual",
                    status=CheckStatus.PASSED if ext.get("annual_income") else CheckStatus.WARNING,
                    detail=f"Ingreso anual: ${ext['annual_income']:,.2f}" if ext.get("annual_income") else "Ingreso anual no detectado",
                ))
                checks.append(CheckItem(
                    name="año_fiscal",
                    status=CheckStatus.PASSED if ext.get("fiscal_year") else CheckStatus.SKIPPED,
                    detail=f"Año fiscal: {ext['fiscal_year']}" if ext.get("fiscal_year") else "Año fiscal no encontrado",
                ))
                return checks

            TYPE_MAP = {
                "payroll":           (extract_payroll_data,           _build_payroll_checks),
                "income_proof":      (extract_payroll_data,           _build_payroll_checks),
                "employment_letter": (extract_employment_letter_data, _build_employment_letter_checks),
                "tax_return":        (extract_tax_return_data,        _build_tax_return_checks),
            }

            if doc_type in TYPE_MAP:
                extractor_fn, check_builder = TYPE_MAP[doc_type]
                extracted = extractor_fn(raw_text)
                checks = check_builder(extracted)
                checks.extend(await _fraud_analysis(tmp_path, doc_type, extracted))
                result = _build_result(doc_type, checks, extracted, start)
            else:
                # Truly unknown — minimal result
                doc_type = hint or "document"
                snippet = raw_text[:800].strip() if raw_text else ""
                extracted = {"texto_extraido": snippet} if snippet else {}
                elapsed = int(time.time() * 1000 - start)
                result = VerificationResult(
                    document_type=doc_type,
                    status=VerificationStatus.MANUAL_REVIEW,
                    confidence_score=0.0,
                    extracted_data=extracted,
                    checks=[],
                    conclusion="Documento recibido pero no se pudo identificar el tipo. Requiere revisión manual.",
                    warnings=["Tipo de documento no identificado automáticamente"],
                    processing_time_ms=elapsed,
                )

        await _save_log(result, institution_id, doc_hash, request, file_path=stored_path, original_filename=original_filename or file.filename, pending_id=pending_id or None, client_reference_id=client_reference_id.strip() or None)
        return result

    except Exception as e:
        logger.error(f"Error en verificación auto: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _classify_with_vision(file_path: str) -> str | None:
    """Usa Claude Vision para clasificar el tipo de documento cuando el texto no es suficiente."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None
    try:
        import anthropic, base64
        from pathlib import Path as _Path

        ext = _Path(file_path).suffix.lower()
        # Para PDF, convertir primera página
        if ext == ".pdf":
            try:
                from pdf2image import convert_from_path
                import tempfile
                pages = convert_from_path(file_path, dpi=150, first_page=1, last_page=1)
                if not pages:
                    return None
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                    tmp_img = tmp.name
                pages[0].save(tmp_img, "PNG")
                file_path = tmp_img
                ext = ".png"
            except Exception:
                return None

        media_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
        media_type = media_map.get(ext, "image/jpeg")
        with open(file_path, "rb") as f:
            img_data = base64.standard_b64encode(f.read()).decode()

        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=32,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": img_data}},
                    {"type": "text", "text": (
                        "Identifica el tipo de documento mexicano en la imagen. "
                        "Responde SOLO con una de estas palabras exactas: "
                        "ine, curp, csf, rfc, cfdi, bank_statement, payroll, proof_of_address, "
                        "employment_letter, tax_return, spei, escritura, predial, passport, "
                        "acta_nacimiento, acta_matrimonio, acta_defuncion, cert_libertad_gravamen, "
                        "avaluo, carta_no_adeudo, licencia, fm_residencia, cedula_profesional, unknown"
                    )},
                ],
            }],
        )
        result = msg.content[0].text.strip().lower().split()[0]
        valid = {
            "ine", "curp", "bank_statement", "payroll", "proof_of_address",
            "employment_letter", "tax_return", "csf", "spei", "escritura",
            "predial", "acta_nacimiento", "acta_matrimonio", "acta_defuncion",
            "rfc", "cfdi", "cert_libertad_gravamen", "avaluo", "carta_no_adeudo",
            "passport", "licencia", "fm_residencia", "cedula_profesional",
        }
        detected = result if result in valid else None
        logger.info(f"Vision clasificó documento como: {detected!r}")
        return detected
    except Exception as e:
        logger.warning(f"Vision clasificación falló: {e}")
        return None


def _extract_payroll_vision_sync(file_path: str, suffix: str) -> dict:
    """Convierte PDF→PNG si es necesario y llama a Vision para extraer datos de nómina.
    Diseñado para correr en asyncio.to_thread — no bloquea el event loop."""
    from services.vision_extractor import extract_payroll_data_with_vision
    vision_path = file_path
    try:
        if suffix == ".pdf":
            from pdf2image import convert_from_path
            pages = convert_from_path(file_path, dpi=150, first_page=1, last_page=1)
            if not pages:
                return {}
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as vf:
                vision_path = vf.name
            pages[0].save(vision_path, "PNG")
        return extract_payroll_data_with_vision(vision_path)
    except Exception as e:
        logger.warning(f"Vision nómina sync falló: {e}")
        return {}
    finally:
        if vision_path != file_path:
            try:
                os.unlink(vision_path)
            except OSError:
                pass


_SAT_QR_DOMAINS = ("verificacfdi.facturaelectronica.sat.gob.mx", "sat.gob.mx", "verificacfdi")
_UUID_RE_STR = re.compile(r'[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}', re.IGNORECASE)


def _build_payroll_checks_inline(ext: dict, qr_codes: list | None = None) -> list[CheckItem]:
    """Construye checks para recibo de nómina/CFDI incluyendo validación de timbrado SAT."""
    checks = []

    # ── Timbrado SAT (check crítico — FAILED bloquea aceptación) ─────────────
    cfdi_uuid = ext.get("cfdi_uuid", "")
    # También buscar UUID en QR codes
    qr_has_sat = False
    qr_uuid = ""
    for qr in (qr_codes or []):
        qr_data = qr.get("data", "")
        if any(d in qr_data.lower() for d in _SAT_QR_DOMAINS):
            qr_has_sat = True
            m = _UUID_RE_STR.search(qr_data)
            if m:
                qr_uuid = m.group(0).upper()
            break
        # UUID en texto plano dentro del QR
        m = _UUID_RE_STR.search(qr_data)
        if m:
            qr_uuid = m.group(0).upper()

    if cfdi_uuid:
        detail = f"Folio Fiscal (UUID): {cfdi_uuid}"
        if qr_has_sat:
            detail += " — QR de verificación SAT presente"
        checks.append(CheckItem(name="cfdi_timbrado", status=CheckStatus.PASSED, detail=detail))
    elif qr_uuid:
        checks.append(CheckItem(
            name="cfdi_timbrado",
            status=CheckStatus.PASSED,
            detail=f"UUID detectado en QR: {qr_uuid}" + (" — QR de verificación SAT presente" if qr_has_sat else ""),
        ))
    else:
        checks.append(CheckItem(
            name="cfdi_timbrado",
            status=CheckStatus.FAILED,
            detail=(
                "El documento NO está timbrado por el SAT. "
                "No se encontró UUID/Folio Fiscal ni código QR de verificación del SAT. "
                "Un recibo de nómina válido en México debe ser un CFDI timbrado por el SAT "
                "a través de un PAC (Proveedor Autorizado de Certificación)."
            ),
        ))

    # ── Checks de datos básicos ───────────────────────────────────────────────
    checks.append(CheckItem(
        name="nombre_empleado",
        status=CheckStatus.PASSED if ext.get("employee_name") else CheckStatus.WARNING,
        detail=f"Empleado: {ext['employee_name']}" if ext.get("employee_name") else "No se detectó nombre del empleado",
    ))
    checks.append(CheckItem(
        name="salario_neto",
        status=CheckStatus.PASSED if ext.get("net_salary") else CheckStatus.WARNING,
        detail=f"Salario neto: ${ext['net_salary']:,.2f}" if ext.get("net_salary") else "No se detectó salario neto",
    ))
    checks.append(CheckItem(
        name="empresa",
        status=CheckStatus.PASSED if ext.get("employer_name") else CheckStatus.WARNING,
        detail=f"Empresa: {ext['employer_name']}" if ext.get("employer_name") else "No se detectó nombre de la empresa",
    ))
    checks.append(CheckItem(
        name="rfc_empleado",
        status=CheckStatus.PASSED if ext.get("employee_rfc") else CheckStatus.SKIPPED,
        detail=f"RFC: {ext['employee_rfc']}" if ext.get("employee_rfc") else "RFC del empleado no detectado",
    ))
    return checks


async def _fraud_analysis(file_path: str, doc_type: str, extracted: dict, preloaded_qr: list | None = None) -> list[CheckItem]:
    """Wrapper conveniente para llamar al fraud detector desde el router."""
    try:
        from services.fraud_detector import analyze_document
        return await analyze_document(file_path, doc_type, extracted, preloaded_qr_codes=preloaded_qr)
    except Exception as e:
        logger.warning(f"Fraud analysis falló: {e}")
        return []


def _detect_document_type(raw_text_lower: str) -> str:
    t = raw_text_lower
    scores = {
        "ine": sum([
            "clave de elector" in t,
            "instituto nacional electoral" in t,
            "credencial para votar" in t,
            "curp" in t and "ine" in t,
        ]),
        "bank_statement": sum([
            "estado de cuenta" in t,
            "saldo" in t and "banco" in t,
            "depósito" in t or "deposito" in t,
            "clabe" in t,
        ]),
        "payroll": sum([
            "nómina" in t or "nomina" in t,
            "percepciones" in t,
            "deducciones" in t,
            "salario" in t or "sueldo" in t,
            "cfdi" in t and ("nómina" in t or "nomina" in t or "percepciones" in t),
            "folio fiscal" in t or ("uuid" in t and "rfc" in t),
            "imss" in t or "infonavit" in t,
            "recibo de nómina" in t or "recibo de nomina" in t,
        ]),
        "proof_of_address": sum([
            "comprobante de domicilio" in t,
            "cfe" in t,
            "telmex" in t or "totalplay" in t or "izzi" in t or "megacable" in t,
            "servicio" in t and "domicilio" in t,
            "lectura" in t and ("luz" in t or "agua" in t or "gas" in t),
        ]),
        # Notarial documents
        "csf": sum([
            "constancia de situación fiscal" in t,
            "servicio de administración tributaria" in t,
            "régimen fiscal" in t or "regimen fiscal" in t,
            "rfc:" in t or "registro federal de contribuyentes" in t,
        ]),
        "spei": sum([
            "spei" in t,
            "clave de rastreo" in t or "folio" in t and "banxico" in t,
            "clabe" in t and "transferencia" in t,
            "banco receptor" in t or "cuenta destino" in t,
        ]),
        "escritura": sum([
            "escritura pública" in t or "instrumento notarial" in t,
            "notario público" in t,
            "registro público de la propiedad" in t or "folio real" in t,
            "vendedor" in t and ("comprador" in t or "adquirente" in t),
        ]),
        "predial": sum([
            "impuesto predial" in t or "boleta predial" in t,
            "clave catastral" in t or "catastro" in t,
            "tesorería" in t or "hacienda municipal" in t,
            "municipio" in t and "predial" in t,
        ]),
        "acta_nacimiento": sum([
            "acta de nacimiento" in t,
            "registro civil" in t and "nacimiento" in t,
            "oficialía" in t and ("nacimiento" in t or "nació" in t),
        ]),
        "acta_matrimonio": sum([
            "acta de matrimonio" in t,
            "registro civil" in t and "matrimonio" in t,
            "contrayentes" in t or "cónyuge" in t,
        ]),
        "acta_defuncion": sum([
            "acta de defunción" in t or "acta de fallecimiento" in t,
            "falleció" in t or "fallecimiento" in t,
            "registro civil" in t and "defunción" in t,
        ]),
        "rfc": sum([
            "constancia de registro" in t and "rfc" in t,
            "registro federal de contribuyentes" in t,
        ]),
        "cfdi": sum([
            "comprobante fiscal digital" in t or "cfdi" in t,
            "timbre fiscal digital" in t or "folio fiscal" in t,
            "uuid" in t and "sat" in t,
        ]),
        "cert_libertad_gravamen": sum([
            "certificado de libertad" in t or "libertad de gravamen" in t,
            "registro público de la propiedad" in t,
            "libre de gravamen" in t or "sin gravamen" in t,
        ]),
        "avaluo": sum([
            "avalúo" in t or "valuación" in t,
            "valor de mercado" in t or "valor comercial" in t,
            "perito valuador" in t or "dictamen valuatorio" in t,
        ]),
        "carta_no_adeudo": sum([
            "carta de no adeudo" in t or "constancia de no adeudo" in t,
            "sin adeudo" in t or "al corriente" in t,
            "no registra adeudo" in t or "libre de adeudo" in t,
        ]),
        "passport": sum([
            "pasaporte" in t or "passport" in t,
            "mrz" in t or "p<mex" in t or "p<" in t,
            "secretaría de relaciones exteriores" in t or "sre" in t,
        ]),
        "licencia": sum([
            "licencia de conducir" in t or "permiso de conducir" in t,
            "secretaría de movilidad" in t or "dirección de tránsito" in t,
        ]),
        "cert_libertad_gravamen": sum([
            "certificado de libertad" in t or "libertad de gravamen" in t,
            "registro público de la propiedad" in t,
        ]),
    }
    best = max(scores, key=scores.get)
    return best if scores[best] >= 2 else "unknown"
