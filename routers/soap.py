"""
Router SOAP para clientes que requieren XML/SOAP (e.g. QuickBase).

Expone el pipeline de verificación existente como servicio SOAP 1.1
(document/literal wrapped) sin dependencias nuevas — solo stdlib XML.

Endpoints:
  GET  /soap?wsdl  → WSDL del servicio
  POST /soap       → operaciones SOAP:
                      - VerifyDocument       (síncrona: espera el resultado)
                      - SubmitDocument       (asíncrona: retorna verificationId)
                      - GetVerificationResult (polling por verificationId)

Autenticación: <apiKey> dentro del body SOAP, o header X-API-Key.
El archivo viaja como base64 en <fileContentBase64>.
"""

import asyncio
import base64
import binascii
import json
import logging
import os
import tempfile
import time
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

from fastapi import APIRouter, HTTPException, Request, Response

from auth.api_key_auth import get_api_key
from auth.entitlements import doc_type_allowed, get_request_config
from models.verification_schemas import CheckItem, VerificationResult, VerificationStatus
from services.conclusion_engine import extract_fraud_flags

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/soap", tags=["soap"])

SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
TNS = "urn:saremi:verify:v1"

# Tamaño máximo del archivo decodificado (bytes)
MAX_FILE_BYTES = int(os.getenv("SOAP_MAX_FILE_BYTES", str(30 * 1024 * 1024)))

# Tipos aceptados en <documentType>. "auto" activa la auto-detección.
_BASE_TYPES = {"ine", "curp", "bank_statement", "proof_of_address", "payroll", "income_proof"}


def _allowed_types() -> set[str]:
    from routers.verify import _NOTARIAL_VERIFIER_MAP
    return _BASE_TYPES | set(_NOTARIAL_VERIFIER_MAP.keys()) | {"auto"}


# Referencias a tareas en background para que el GC no las cancele
_bg_tasks: set[asyncio.Task] = set()


# ── helpers XML ───────────────────────────────────────────────────────────────

def _local(tag: str) -> str:
    """Nombre local sin namespace: '{ns}Foo' → 'Foo'."""
    return tag.rsplit("}", 1)[-1]


def _find_operation(envelope: ET.Element) -> ET.Element | None:
    """Encuentra el primer elemento hijo del soap:Body (la operación)."""
    for child in envelope:
        if _local(child.tag) == "Body":
            for op in child:
                return op
    return None


def _child_text(op: ET.Element, name: str) -> str:
    """Texto de un hijo directo por nombre local (case-insensitive)."""
    target = name.lower()
    for child in op:
        if _local(child.tag).lower() == target:
            return (child.text or "").strip()
    return ""


def _soap_response(operation: str, inner_xml: str) -> Response:
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<soap:Envelope xmlns:soap="{SOAP_NS}">'
        "<soap:Body>"
        f'<{operation}Response xmlns="{TNS}">'
        f"{inner_xml}"
        f"</{operation}Response>"
        "</soap:Body>"
        "</soap:Envelope>"
    )
    return Response(content=body, media_type="text/xml; charset=utf-8")


def _soap_fault(code: str, message: str, http_status: int = 500) -> Response:
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<soap:Envelope xmlns:soap="{SOAP_NS}">'
        "<soap:Body>"
        "<soap:Fault>"
        f"<faultcode>soap:{escape(code)}</faultcode>"
        f"<faultstring>{escape(message)}</faultstring>"
        "</soap:Fault>"
        "</soap:Body>"
        "</soap:Envelope>"
    )
    return Response(content=body, media_type="text/xml; charset=utf-8", status_code=http_status)


def _result_to_xml(result: VerificationResult, verification_id: str | None) -> str:
    """Serializa un VerificationResult al cuerpo XML de la respuesta SOAP."""
    parts = [
        f"<verificationId>{escape(verification_id or '')}</verificationId>",
        f"<documentType>{escape(result.document_type)}</documentType>",
        f"<status>{escape(result.status.value)}</status>",
        f"<confidenceScore>{result.confidence_score:.3f}</confidenceScore>",
        f"<conclusion>{escape(result.conclusion or '')}</conclusion>",
        f"<processingTimeMs>{result.processing_time_ms}</processingTimeMs>",
    ]

    parts.append("<checks>")
    for c in result.checks:
        parts.append(
            "<check>"
            f"<name>{escape(c.name)}</name>"
            f"<status>{escape(c.status.value)}</status>"
            f"<detail>{escape(c.detail)}</detail>"
            "</check>"
        )
    parts.append("</checks>")

    parts.append("<fraudFlags>")
    for f in result.fraud_flags:
        parts.append(
            "<fraudFlag>"
            f"<code>{escape(f.code)}</code>"
            f"<severity>{escape(f.severity.value)}</severity>"
            f"<description>{escape(f.description)}</description>"
            "</fraudFlag>"
        )
    parts.append("</fraudFlags>")

    parts.append("<warnings>")
    for w in result.warnings:
        parts.append(f"<warning>{escape(str(w))}</warning>")
    parts.append("</warnings>")

    parts.append("<extractedData>")
    for key, value in (result.extracted_data or {}).items():
        if key.startswith("_"):
            continue
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, default=str)
        parts.append(
            "<field>"
            f"<name>{escape(str(key))}</name>"
            f"<value>{escape(str(value))}</value>"
            "</field>"
        )
    parts.append("</extractedData>")

    return "".join(parts)


# ── helpers de negocio ────────────────────────────────────────────────────────

def _decode_file(op: ET.Element) -> tuple[str, str]:
    """
    Decodifica <fileContentBase64> a un archivo temporal.
    Retorna (tmp_path, suffix). Lanza ValueError con mensaje legible si falla.
    """
    b64 = _child_text(op, "fileContentBase64")
    if not b64:
        raise ValueError("Se requiere el elemento <fileContentBase64> con el documento en base64")

    try:
        raw = base64.b64decode(b64, validate=False)
    except (binascii.Error, ValueError):
        raise ValueError("El contenido de <fileContentBase64> no es base64 válido")

    if len(raw) > MAX_FILE_BYTES:
        raise ValueError(f"El archivo excede el tamaño máximo permitido ({MAX_FILE_BYTES // (1024*1024)} MB)")
    if len(raw) < 100:
        raise ValueError("El archivo decodificado es demasiado pequeño para ser un documento válido")

    file_name = _child_text(op, "fileName") or "document.pdf"
    suffix = os.path.splitext(file_name)[1].lower() or ".pdf"
    if suffix not in (".pdf", ".jpg", ".jpeg", ".png", ".webp", ".xml"):
        suffix = ".pdf"

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(raw)
        return tmp.name, suffix


async def _detect_type(file_path: str) -> str:
    """Auto-detección de tipo: keywords sobre el texto extraído → Claude Vision."""
    from routers.verify import _extract_text_from_file, _detect_document_type, _classify_with_vision
    raw_text = await asyncio.to_thread(_extract_text_from_file, file_path)
    doc_type = _detect_document_type(raw_text.lower())
    if doc_type == "unknown":
        suffix = os.path.splitext(file_path)[1].lower()
        if suffix in (".jpg", ".jpeg", ".png", ".webp", ".pdf"):
            doc_type = await asyncio.to_thread(_classify_with_vision, file_path) or "unknown"
    return doc_type


def _unknown_result(start_ms: float) -> VerificationResult:
    return VerificationResult(
        document_type="document",
        status=VerificationStatus.MANUAL_REVIEW,
        confidence_score=0.0,
        extracted_data={},
        checks=[],
        conclusion="Documento recibido pero no se pudo identificar el tipo. Requiere revisión manual.",
        warnings=["Tipo de documento no identificado automáticamente"],
        processing_time_ms=int(time.time() * 1000 - start_ms),
    )


async def _run_pipeline_for(
    file_path: str, doc_type: str, start_ms: float, config: dict | None = None
) -> VerificationResult:
    """Resuelve 'auto', valida entitlements sobre el tipo final y corre el pipeline."""
    from routers.verify import run_verification_pipeline
    if doc_type == "auto":
        doc_type = await _detect_type(file_path)
        if doc_type == "unknown":
            return _unknown_result(start_ms)
    if config is not None and not doc_type_allowed(config, doc_type):
        raise ValueError(
            f"El tipo de documento detectado ('{doc_type}') no está habilitado para su institución."
        )
    return await run_verification_pipeline(file_path, doc_type, start_ms)


async def _authenticate(request: Request, op: ET.Element) -> str:
    """Valida apiKey del body SOAP (o header X-API-Key). Retorna institution_id."""
    api_key = _child_text(op, "apiKey") or request.headers.get("X-API-Key", "")
    return await get_api_key(request, api_key)


# ── operaciones ───────────────────────────────────────────────────────────────

async def _op_verify_document(request: Request, op: ET.Element) -> Response:
    """Verificación síncrona: espera el resultado completo (puede tardar 10-60s)."""
    from routers.verify import _file_hash, _persist_file, _save_log

    institution_id = await _authenticate(request, op)
    config = get_request_config(request)

    doc_type = (_child_text(op, "documentType") or "auto").strip().lower()
    if doc_type not in _allowed_types():
        return _soap_fault(
            "Client.InvalidDocumentType",
            f"documentType '{doc_type}' no soportado. Valores válidos: {', '.join(sorted(_allowed_types()))}",
        )
    if not doc_type_allowed(config, doc_type):
        return _soap_fault(
            "Client.DocumentTypeNotEnabled",
            f"El tipo de documento '{doc_type}' no está habilitado para su institución.",
        )

    file_name = _child_text(op, "fileName") or "document.pdf"
    client_ref = _child_text(op, "clientReferenceId") or None
    start_ms = time.time() * 1000

    tmp_path = None
    try:
        tmp_path, suffix = _decode_file(op)
        doc_hash = _file_hash(tmp_path)
        stored_path = _persist_file(tmp_path, doc_hash, suffix)

        logger.info(f"[SOAP][{institution_id}] VerifyDocument type={doc_type} file={file_name}")
        result = await _run_pipeline_for(tmp_path, doc_type, start_ms, config)

        log_id = await _save_log(
            result, institution_id, doc_hash, request,
            file_path=stored_path, original_filename=file_name,
            client_reference_id=client_ref,
        )
        return _soap_response("VerifyDocument", _result_to_xml(result, log_id))
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


async def _op_submit_document(request: Request, op: ET.Element) -> Response:
    """Verificación asíncrona: registra 'processing', procesa en background y retorna el id."""
    from routers.verify import _file_hash, _persist_file, _save_log
    from db_helpers import get_conn

    institution_id = await _authenticate(request, op)
    config = get_request_config(request)

    doc_type = (_child_text(op, "documentType") or "auto").strip().lower()
    if doc_type not in _allowed_types():
        return _soap_fault(
            "Client.InvalidDocumentType",
            f"documentType '{doc_type}' no soportado. Valores válidos: {', '.join(sorted(_allowed_types()))}",
        )
    if not doc_type_allowed(config, doc_type):
        return _soap_fault(
            "Client.DocumentTypeNotEnabled",
            f"El tipo de documento '{doc_type}' no está habilitado para su institución.",
        )

    file_name = _child_text(op, "fileName") or "document.pdf"
    client_ref = _child_text(op, "clientReferenceId") or None
    ip = request.client.host if request.client else None

    tmp_path, suffix = _decode_file(op)
    doc_hash = _file_hash(tmp_path)
    # Persistir de inmediato: el background task procesa el archivo ya almacenado
    stored_path = _persist_file(tmp_path, doc_hash, suffix)
    os.unlink(tmp_path)
    if not stored_path:
        return _soap_fault("Server", "No se pudo almacenar el documento para procesamiento")

    # Registro pending (mismo patrón que POST /v1/verify/pending)
    async with get_conn() as conn:
        inst_row = await conn.fetchrow("SELECT id FROM institutions WHERE id = %s", institution_id)
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
                    0, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            inst_pk, doc_type if doc_type != "auto" else "document",
            doc_hash, ip, stored_path, file_name, client_ref,
        )
    log_id = str(log_id)
    logger.info(f"[SOAP][{institution_id}] SubmitDocument pending={log_id} type={doc_type}")

    async def _process() -> None:
        start_ms = time.time() * 1000
        try:
            result = await _run_pipeline_for(stored_path, doc_type, start_ms, config)
            await _save_log(
                result, institution_id, doc_hash, request,
                file_path=stored_path, original_filename=file_name,
                pending_id=log_id, client_reference_id=client_ref,
            )
            logger.info(f"[SOAP] Background {log_id} completado: {result.status.value}")
        except Exception as e:
            logger.error(f"[SOAP] Background {log_id} falló: {e}", exc_info=True)
            try:
                async with get_conn() as conn:
                    await conn.execute(
                        "UPDATE verification_logs SET status = 'manual_review', "
                        "conclusion = %s WHERE id = %s AND status = 'processing'",
                        f"Error durante el procesamiento automático: {e}. Requiere revisión manual.",
                        log_id,
                    )
            except Exception:
                pass

    task = asyncio.create_task(_process())
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)

    inner = (
        f"<verificationId>{escape(log_id)}</verificationId>"
        "<status>processing</status>"
        "<message>Documento recibido. Consulte el resultado con GetVerificationResult.</message>"
    )
    return _soap_response("SubmitDocument", inner)


async def _op_get_verification_result(request: Request, op: ET.Element) -> Response:
    """Consulta el resultado de una verificación por verificationId."""
    from db_helpers import get_conn

    institution_id = await _authenticate(request, op)

    verification_id = _child_text(op, "verificationId")
    if not verification_id:
        return _soap_fault("Client", "Se requiere el elemento <verificationId>")

    async with get_conn() as conn:
        row = await conn.fetchrow(
            """
            SELECT vl.*, i.id AS inst_pk
            FROM verification_logs vl
            LEFT JOIN institutions i ON i.id = vl.institution_id
            WHERE vl.id = %s
            """,
            verification_id,
        )

    if not row:
        return _soap_fault("Client.NotFound", f"No existe verificación con id {verification_id}")

    # Aislamiento entre instituciones: solo el dueño puede consultar su verificación
    if row.get("institution_id") is not None and str(row["institution_id"]) != institution_id:
        return _soap_fault("Client.Forbidden", "La verificación no pertenece a esta institución")

    status = row["status"]
    if status == "processing":
        inner = (
            f"<verificationId>{escape(verification_id)}</verificationId>"
            "<status>processing</status>"
            "<message>El documento sigue en análisis. Intente de nuevo en unos segundos.</message>"
        )
        return _soap_response("GetVerificationResult", inner)

    checks_raw = row.get("checks") or []
    if isinstance(checks_raw, str):
        checks_raw = json.loads(checks_raw)
    warnings_raw = row.get("warnings") or []
    if isinstance(warnings_raw, str):
        warnings_raw = json.loads(warnings_raw)
    extracted_raw = row.get("extracted_data") or {}
    if isinstance(extracted_raw, str):
        extracted_raw = json.loads(extracted_raw)

    checks = [CheckItem(**c) for c in checks_raw]
    result = VerificationResult(
        document_type=row["document_type"],
        status=VerificationStatus(status),
        confidence_score=float(row["confidence_score"]),
        extracted_data=extracted_raw,
        checks=checks,
        conclusion=row.get("conclusion") or "",
        warnings=warnings_raw,
        fraud_flags=extract_fraud_flags(checks),
        processing_time_ms=int(row.get("processing_time_ms") or 0),
    )
    return _soap_response("GetVerificationResult", _result_to_xml(result, verification_id))


_OPERATIONS = {
    "verifydocument": _op_verify_document,
    "submitdocument": _op_submit_document,
    "getverificationresult": _op_get_verification_result,
}


# ── endpoints HTTP ────────────────────────────────────────────────────────────

@router.get("")
@router.get("/")
async def soap_wsdl(request: Request):
    """Sirve el WSDL. Convención: GET /soap?wsdl (el WSDL se sirve en cualquier GET)."""
    base = os.getenv("SOAP_PUBLIC_URL", "").rstrip("/")
    if not base:
        base = str(request.base_url).rstrip("/") + "/soap"
    return Response(content=_build_wsdl(base), media_type="text/xml; charset=utf-8")


@router.post("")
@router.post("/")
async def soap_endpoint(request: Request):
    """Punto de entrada SOAP: enruta según el elemento del soap:Body."""
    body = await request.body()
    if not body:
        return _soap_fault("Client", "Cuerpo de la petición vacío: se esperaba un envelope SOAP")

    try:
        envelope = ET.fromstring(body)
    except ET.ParseError as e:
        return _soap_fault("Client", f"XML inválido: {e}")

    op = _find_operation(envelope)
    if op is None:
        return _soap_fault("Client", "No se encontró ninguna operación dentro de soap:Body")

    # 'VerifyDocumentRequest' y 'VerifyDocument' son equivalentes
    op_name = _local(op.tag).lower()
    if op_name.endswith("request"):
        op_name = op_name[: -len("request")]

    handler = _OPERATIONS.get(op_name)
    if handler is None:
        return _soap_fault(
            "Client",
            f"Operación '{_local(op.tag)}' no soportada. "
            "Operaciones válidas: VerifyDocument, SubmitDocument, GetVerificationResult",
        )

    try:
        return await handler(request, op)
    except HTTPException as e:
        detail = str(e.detail)
        if e.status_code == 403 and "API Key" in detail:
            code = "Client.AuthenticationFailed"
        elif e.status_code == 403:
            code = "Client.Forbidden"
        else:
            code = "Client"
        return _soap_fault(code, detail)
    except ValueError as e:
        return _soap_fault("Client", str(e))
    except Exception as e:
        logger.error(f"[SOAP] Error no controlado en {op_name}: {e}", exc_info=True)
        return _soap_fault("Server", f"Error interno del servidor: {e}")


# ── WSDL ──────────────────────────────────────────────────────────────────────

def _build_wsdl(service_url: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<wsdl:definitions name="SarEmiVerificationService"
    targetNamespace="{TNS}"
    xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/"
    xmlns:soap="http://schemas.xmlsoap.org/wsdl/soap/"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema"
    xmlns:tns="{TNS}">

  <wsdl:types>
    <xsd:schema targetNamespace="{TNS}" elementFormDefault="qualified">

      <xsd:complexType name="Check">
        <xsd:sequence>
          <xsd:element name="name" type="xsd:string"/>
          <xsd:element name="status" type="xsd:string"/>
          <xsd:element name="detail" type="xsd:string"/>
        </xsd:sequence>
      </xsd:complexType>

      <xsd:complexType name="FraudFlag">
        <xsd:sequence>
          <xsd:element name="code" type="xsd:string"/>
          <xsd:element name="severity" type="xsd:string"/>
          <xsd:element name="description" type="xsd:string"/>
        </xsd:sequence>
      </xsd:complexType>

      <xsd:complexType name="ExtractedField">
        <xsd:sequence>
          <xsd:element name="name" type="xsd:string"/>
          <xsd:element name="value" type="xsd:string"/>
        </xsd:sequence>
      </xsd:complexType>

      <xsd:complexType name="VerificationResult">
        <xsd:sequence>
          <xsd:element name="verificationId" type="xsd:string"/>
          <xsd:element name="documentType" type="xsd:string"/>
          <xsd:element name="status" type="xsd:string"/>
          <xsd:element name="confidenceScore" type="xsd:decimal"/>
          <xsd:element name="conclusion" type="xsd:string"/>
          <xsd:element name="processingTimeMs" type="xsd:int"/>
          <xsd:element name="checks">
            <xsd:complexType><xsd:sequence>
              <xsd:element name="check" type="tns:Check" minOccurs="0" maxOccurs="unbounded"/>
            </xsd:sequence></xsd:complexType>
          </xsd:element>
          <xsd:element name="fraudFlags">
            <xsd:complexType><xsd:sequence>
              <xsd:element name="fraudFlag" type="tns:FraudFlag" minOccurs="0" maxOccurs="unbounded"/>
            </xsd:sequence></xsd:complexType>
          </xsd:element>
          <xsd:element name="warnings">
            <xsd:complexType><xsd:sequence>
              <xsd:element name="warning" type="xsd:string" minOccurs="0" maxOccurs="unbounded"/>
            </xsd:sequence></xsd:complexType>
          </xsd:element>
          <xsd:element name="extractedData">
            <xsd:complexType><xsd:sequence>
              <xsd:element name="field" type="tns:ExtractedField" minOccurs="0" maxOccurs="unbounded"/>
            </xsd:sequence></xsd:complexType>
          </xsd:element>
        </xsd:sequence>
      </xsd:complexType>

      <xsd:element name="VerifyDocumentRequest">
        <xsd:complexType><xsd:sequence>
          <xsd:element name="apiKey" type="xsd:string"/>
          <xsd:element name="documentType" type="xsd:string" minOccurs="0"/>
          <xsd:element name="fileName" type="xsd:string" minOccurs="0"/>
          <xsd:element name="fileContentBase64" type="xsd:base64Binary"/>
          <xsd:element name="clientReferenceId" type="xsd:string" minOccurs="0"/>
        </xsd:sequence></xsd:complexType>
      </xsd:element>
      <xsd:element name="VerifyDocumentResponse" type="tns:VerificationResult"/>

      <xsd:element name="SubmitDocumentRequest">
        <xsd:complexType><xsd:sequence>
          <xsd:element name="apiKey" type="xsd:string"/>
          <xsd:element name="documentType" type="xsd:string" minOccurs="0"/>
          <xsd:element name="fileName" type="xsd:string" minOccurs="0"/>
          <xsd:element name="fileContentBase64" type="xsd:base64Binary"/>
          <xsd:element name="clientReferenceId" type="xsd:string" minOccurs="0"/>
        </xsd:sequence></xsd:complexType>
      </xsd:element>
      <xsd:element name="SubmitDocumentResponse">
        <xsd:complexType><xsd:sequence>
          <xsd:element name="verificationId" type="xsd:string"/>
          <xsd:element name="status" type="xsd:string"/>
          <xsd:element name="message" type="xsd:string"/>
        </xsd:sequence></xsd:complexType>
      </xsd:element>

      <xsd:element name="GetVerificationResultRequest">
        <xsd:complexType><xsd:sequence>
          <xsd:element name="apiKey" type="xsd:string"/>
          <xsd:element name="verificationId" type="xsd:string"/>
        </xsd:sequence></xsd:complexType>
      </xsd:element>
      <xsd:element name="GetVerificationResultResponse" type="tns:VerificationResult"/>

    </xsd:schema>
  </wsdl:types>

  <wsdl:message name="VerifyDocumentInput"><wsdl:part name="parameters" element="tns:VerifyDocumentRequest"/></wsdl:message>
  <wsdl:message name="VerifyDocumentOutput"><wsdl:part name="parameters" element="tns:VerifyDocumentResponse"/></wsdl:message>
  <wsdl:message name="SubmitDocumentInput"><wsdl:part name="parameters" element="tns:SubmitDocumentRequest"/></wsdl:message>
  <wsdl:message name="SubmitDocumentOutput"><wsdl:part name="parameters" element="tns:SubmitDocumentResponse"/></wsdl:message>
  <wsdl:message name="GetVerificationResultInput"><wsdl:part name="parameters" element="tns:GetVerificationResultRequest"/></wsdl:message>
  <wsdl:message name="GetVerificationResultOutput"><wsdl:part name="parameters" element="tns:GetVerificationResultResponse"/></wsdl:message>

  <wsdl:portType name="SarEmiVerificationPortType">
    <wsdl:operation name="VerifyDocument">
      <wsdl:input message="tns:VerifyDocumentInput"/>
      <wsdl:output message="tns:VerifyDocumentOutput"/>
    </wsdl:operation>
    <wsdl:operation name="SubmitDocument">
      <wsdl:input message="tns:SubmitDocumentInput"/>
      <wsdl:output message="tns:SubmitDocumentOutput"/>
    </wsdl:operation>
    <wsdl:operation name="GetVerificationResult">
      <wsdl:input message="tns:GetVerificationResultInput"/>
      <wsdl:output message="tns:GetVerificationResultOutput"/>
    </wsdl:operation>
  </wsdl:portType>

  <wsdl:binding name="SarEmiVerificationBinding" type="tns:SarEmiVerificationPortType">
    <soap:binding style="document" transport="http://schemas.xmlsoap.org/soap/http"/>
    <wsdl:operation name="VerifyDocument">
      <soap:operation soapAction="{TNS}/VerifyDocument"/>
      <wsdl:input><soap:body use="literal"/></wsdl:input>
      <wsdl:output><soap:body use="literal"/></wsdl:output>
    </wsdl:operation>
    <wsdl:operation name="SubmitDocument">
      <soap:operation soapAction="{TNS}/SubmitDocument"/>
      <wsdl:input><soap:body use="literal"/></wsdl:input>
      <wsdl:output><soap:body use="literal"/></wsdl:output>
    </wsdl:operation>
    <wsdl:operation name="GetVerificationResult">
      <soap:operation soapAction="{TNS}/GetVerificationResult"/>
      <wsdl:input><soap:body use="literal"/></wsdl:input>
      <wsdl:output><soap:body use="literal"/></wsdl:output>
    </wsdl:operation>
  </wsdl:binding>

  <wsdl:service name="SarEmiVerificationService">
    <wsdl:port name="SarEmiVerificationPort" binding="tns:SarEmiVerificationBinding">
      <soap:address location="{service_url}"/>
    </wsdl:port>
  </wsdl:service>

</wsdl:definitions>
"""
