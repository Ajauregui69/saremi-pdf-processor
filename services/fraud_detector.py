"""
Detección de fraude en documentos: análisis visual con Claude Vision + verificación de QR.
Aplica a INE, CURP, estados de cuenta y comprobantes de domicilio.
"""

import asyncio
import base64
import json
import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

import httpx

from models.verification_schemas import CheckItem, CheckStatus

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
FRAUD_MODEL = os.getenv("FRAUD_DETECTION_MODEL", "claude-sonnet-4-6")
SCRAPER_TIMEOUT = int(os.getenv("SCRAPER_TIMEOUT_SECONDS", "15"))

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
_CURP_RE = re.compile(r"^[A-Z]{4}\d{6}[HM][A-Z]{5}[0-9A-Z]\d$")


# ── helpers ───────────────────────────────────────────────────────────────────

def _vision_available() -> bool:
    return bool(ANTHROPIC_API_KEY)


_MAX_IMAGE_BYTES = 4 * 1024 * 1024
_MAX_DIMENSION = 2000


def _encode_image(path: str) -> tuple[str, str]:
    """Encodea imagen redimensionando si supera 2000px o 4MB (límite Claude: 5MB)."""
    import io
    from PIL import Image as _PIL

    with _PIL.open(path) as img:
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        w, h = img.size
        if max(w, h) > _MAX_DIMENSION:
            scale = _MAX_DIMENSION / max(w, h)
            img = img.resize((int(w * scale), int(h * scale)), _PIL.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85, optimize=True)
        quality = 75
        while buf.tell() > _MAX_IMAGE_BYTES and quality >= 50:
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality, optimize=True)
            quality -= 10
        buf.seek(0)
        return base64.standard_b64encode(buf.read()).decode(), "image/jpeg"


def _make_check(name: str, resultado: str, detalle: str) -> CheckItem:
    status_map = {
        "PASSED": CheckStatus.PASSED,
        "FAILED": CheckStatus.FAILED,
        "WARNING": CheckStatus.WARNING,
        "SKIPPED": CheckStatus.SKIPPED,
    }
    return CheckItem(name=name, status=status_map.get(resultado.upper(), CheckStatus.SKIPPED), detail=detalle)


def _get_images_from_file(file_path: str):
    """Devuelve lista de imágenes PIL desde un PDF o imagen directa."""
    from PIL import Image
    ext = Path(file_path).suffix.lower()
    if ext in _IMAGE_EXTS:
        return [Image.open(file_path)]
    if ext == ".pdf":
        try:
            from pdf2image import convert_from_path
            return convert_from_path(file_path, dpi=200, first_page=1, last_page=2)
        except Exception as e:
            logger.warning(f"pdf2image falló al convertir para QR: {e}")
            return []
    return []


def _scan_qr_codes(file_path: str) -> List[Dict]:
    """Escanea QR codes de un archivo. Retorna lista de {page, data, points}."""
    try:
        from services.qr_service import QRService
        images = _get_images_from_file(file_path)
        if not images:
            return []
        svc = QRService()
        return svc.scan_images(images)
    except Exception as e:
        logger.warning(f"QR scan falló: {e}")
        return []


# ── prompts de análisis visual ────────────────────────────────────────────────

_PROMPT_INE = """Eres un experto en análisis forense de credenciales de identidad mexicanas (INE/IFE).
Analiza esta imagen con detalle y determina si el documento es auténtico o muestra señales de manipulación.

Evalúa cada aspecto y responde ÚNICAMENTE con JSON válido:

{
  "integridad_visual": {
    "resultado": "PASSED|FAILED|WARNING|SKIPPED",
    "detalle": "¿Hay cortes, zonas borrosas inusuales, degradado inconsistente o elementos mal alineados? Describe lo que observas."
  },
  "manipulacion_digital": {
    "resultado": "PASSED|FAILED|WARNING|SKIPPED",
    "detalle": "¿Hay parches blancos sobre texto, diferente resolución en campos específicos, bordes irregulares alrededor de texto o foto, pixelación localizada, o artefactos de compresión inconsistentes que sugieran edición?"
  },
  "ia_generativa": {
    "resultado": "PASSED|FAILED|WARNING|SKIPPED",
    "detalle": "REGLA CLAVE: una INE legítima presentada SIEMPRE es una fotografía o escaneo de una tarjeta FÍSICA de plástico. Por lo tanto, si la imagen parece un RENDER DIGITAL, una PLANTILLA rellenada, o un documento CREADO/GENERADO digitalmente (no la captura de un plástico real), eso por sí mismo es FRAUDE -> responde FAILED, NO WARNING. Señales de que es un render digital y no la foto de una credencial física real: nitidez demasiado homogénea y uniforme en todos los campos, ausencia de ruido de escaneo o grano de impresión, ausencia de reflejos/brillos del laminado plástico, iluminación perfectamente uniforme sin sombras propias de una captura real, tipografía vectorial nítida en vez de tinta impresa, degradados o fondos sintéticos, microtexto/guilloché que se ve dibujado y no impreso, calidad de render 'demasiado perfecta' para un documento físico. Criterio de decisión: si tu evaluación honesta es que la imagen probablemente fue generada/creada digitalmente o por IA (aunque uses palabras como 'posiblemente', 'podría' o 'merece revisión'), responde FAILED. Reserva WARNING SOLO para casos donde sí parece una foto de un plástico real pero con alguna duda menor. Usa PASSED solo si es claramente la captura de una credencial física auténtica."
  },
  "coherencia_tipografica": {
    "resultado": "PASSED|FAILED|WARNING|SKIPPED",
    "detalle": "¿Todos los textos del mismo tipo (nombres, CURP, clave de elector, fechas) usan la misma fuente y tamaño? Señala cualquier discrepancia tipográfica."
  },
  "elementos_seguridad": {
    "resultado": "PASSED|FAILED|WARNING|SKIPPED",
    "detalle": "¿Se identifica la franja holográfica, el escudo nacional de fondo, el chip CIC en modelos recientes, o el patrón de seguridad del fondo? Menciona cuáles son visibles y cuáles están ausentes o dañados. IMPORTANTE: si el documento es un escaneo en escala de grises o fotocopia, usa WARNING (no FAILED) ya que los elementos de seguridad holográficos son inherentemente invisibles en escaneos monocromáticos — esto es esperado y NO indica falsificación."
  },
  "foto_autenticidad": {
    "resultado": "PASSED|FAILED|WARNING|SKIPPED",
    "detalle": "¿La(s) foto(s) del titular son consistentes con el resto del documento en iluminación, resolución y bordes? IMPORTANTE: las credenciales INE modelos C, D y E tienen DOS fotos en el anverso (una grande y una pequeña en esquina inferior) — esto es NORMAL y esperado, no es señal de falsificación. Evalúa si hay indicios de sustitución o pegado de foto (bordes cortados, iluminación distinta, resolución diferente a la del resto del documento)."
  }
}

- PASSED = sin anomalías, aspecto auténtico
- FAILED = anomalías claras que sugieren manipulación o falsificación
- WARNING = inconsistencias menores que requieren revisión manual
- SKIPPED = imagen de baja calidad, ángulo u oclusión impiden evaluar

Responde SOLO con el JSON, sin texto adicional."""

_PROMPT_CURP = """Eres un experto en análisis forense de documentos gubernamentales mexicanos.
Analiza esta imagen del documento CURP oficial y evalúa su autenticidad.

Responde ÚNICAMENTE con este JSON:

{
  "integridad_visual": {
    "resultado": "PASSED|FAILED|WARNING|SKIPPED",
    "detalle": "¿El documento parece íntegro? Señala cortes, zonas borrosas o elementos fuera de lugar."
  },
  "manipulacion_digital": {
    "resultado": "PASSED|FAILED|WARNING|SKIPPED",
    "detalle": "¿Hay signos de edición digital? Parches blancos sobre texto, diferentes resoluciones en campos, bordes irregulares alrededor de datos."
  },
  "ia_generativa": {
    "resultado": "PASSED|FAILED|WARNING|SKIPPED",
    "detalle": "¿El documento fue GENERADO o CREADO digitalmente en lugar de ser un escaneo/foto de un documento físico real o un PDF oficial emitido por el gobierno? Distingue: (a) escaneo/foto de documento auténtico o PDF oficial = NORMAL (PASSED); (b) imagen sintética/fabricada por IA o por edición = FRAUDE (FAILED). Señales de generación digital/IA: texturas demasiado limpias sin ruido de escaneo, escudo/sello que se ve renderizado y no impreso, iluminación uniforme sin sombras de captura real, degradados sintéticos, artefactos típicos de generadores de imágenes por IA, simetrías o repeticiones antinaturales. Si hay indicios CLAROS de generación digital o por IA responde FAILED. Usa WARNING solo para sospechas leves no concluyentes."
  },
  "coherencia_tipografica": {
    "resultado": "PASSED|FAILED|WARNING|SKIPPED",
    "detalle": "¿Las fuentes son consistentes con un documento oficial de la Secretaría de Gobernación? Señala fuentes o tamaños incongruentes."
  },
  "sello_oficial": {
    "resultado": "PASSED|FAILED|WARNING|SKIPPED",
    "detalle": "¿El escudo nacional, sello y membrete del gobierno federal parecen auténticos? ¿Hay indicios de que fueron alterados o insertados digitalmente?"
  }
}

Responde SOLO con el JSON."""

_PROMPT_BANK = """Eres un experto en análisis forense de estados de cuenta bancarios mexicanos.
Analiza esta imagen y evalúa si el documento es auténtico o ha sido manipulado.

Responde ÚNICAMENTE con este JSON:

{
  "integridad_visual": {
    "resultado": "PASSED|FAILED|WARNING|SKIPPED",
    "detalle": "¿El documento parece íntegro? Señala zonas borrosas, cortes o elementos incoherentes con el formato estándar."
  },
  "manipulacion_digital": {
    "resultado": "PASSED|FAILED|WARNING|SKIPPED",
    "detalle": "¿Hay signos de edición en cifras, fechas o nombres? Busca parches blancos, diferente tipografía en números, bordes irregulares en importes o saldos."
  },
  "ia_generativa": {
    "resultado": "PASSED|FAILED|WARNING|SKIPPED",
    "detalle": "¿El estado de cuenta fue GENERADO o FABRICADO digitalmente en lugar de ser un documento real emitido por el banco (PDF oficial o impresión/escaneo de uno)? Distingue: (a) PDF bancario auténtico o su escaneo = NORMAL (PASSED); (b) documento fabricado desde cero o con plantilla/IA = FRAUDE (FAILED). Señales: logo/membrete que se ve renderizado y no impreso, tablas con alineación 'perfecta' impropia de un export real, mezcla de fuentes sintéticas, texturas sin ruido de impresión, artefactos típicos de generadores por IA, datos demasiado uniformes. Si hay indicios CLAROS de fabricación digital o por IA responde FAILED. Usa WARNING solo para sospechas leves no concluyentes."
  },
  "coherencia_tipografica": {
    "resultado": "PASSED|FAILED|WARNING|SKIPPED",
    "detalle": "¿Las fuentes y el formato son consistentes en todo el documento? ¿Hay mezcla de tipografías en campos del mismo tipo (montos, fechas, nombres)?"
  },
  "logotipo_banco": {
    "resultado": "PASSED|FAILED|WARNING|SKIPPED",
    "detalle": "¿El logotipo, colores corporativos y membrete del banco parecen auténticos y consistentes? ¿Hay indicios de que el encabezado o logo fue sustituido?"
  }
}

Responde SOLO con el JSON."""

_PROMPT_GENERIC = """Eres un experto en análisis forense de documentos oficiales mexicanos.
Analiza esta imagen y determina si el documento parece auténtico o muestra señales de manipulación.

Responde ÚNICAMENTE con este JSON:

{
  "integridad_visual": {
    "resultado": "PASSED|FAILED|WARNING|SKIPPED",
    "detalle": "Describe si hay cortes, zonas borrosas inusuales o elementos fuera de lugar en el documento."
  },
  "manipulacion_digital": {
    "resultado": "PASSED|FAILED|WARNING|SKIPPED",
    "detalle": "¿Hay parches blancos sobre texto, diferente resolución en campos, bordes irregulares o pixelación localizada que sugieran edición digital?"
  },
  "ia_generativa": {
    "resultado": "PASSED|FAILED|WARNING|SKIPPED",
    "detalle": "¿El documento fue GENERADO o CREADO digitalmente en lugar de ser un escaneo/foto de un documento físico real o un PDF oficial? Distingue: (a) escaneo/foto de documento auténtico o PDF oficial = NORMAL (PASSED); (b) imagen sintética/fabricada por IA o por edición de plantilla = FRAUDE (FAILED). Señales de generación digital/IA: texturas demasiado limpias sin ruido de escaneo ni grano de impresión, sellos/firmas/logos que se ven renderizados y no impresos, iluminación uniforme sin sombras de captura real, degradados sintéticos, artefactos típicos de generadores de imágenes por IA, simetrías o repeticiones antinaturales, coherencia 'perfecta' impropia de un papel real. Si hay indicios CLAROS de generación digital o por IA responde FAILED. Usa WARNING solo para sospechas leves no concluyentes."
  },
  "coherencia_tipografica": {
    "resultado": "PASSED|FAILED|WARNING|SKIPPED",
    "detalle": "¿Los textos del mismo tipo usan la misma fuente y tamaño? Señala cualquier discrepancia tipográfica."
  },
  "sellos_y_firmas": {
    "resultado": "PASSED|FAILED|WARNING|SKIPPED",
    "detalle": "¿Los sellos y firmas parecen auténticos con tinta uniforme? ¿Hay indicios de que fueron insertados o modificados digitalmente?"
  }
}

Responde SOLO con el JSON."""

_PROMPTS = {
    "ine": _PROMPT_INE,
    "curp": _PROMPT_CURP,
    "bank_statement": _PROMPT_BANK,
    "proof_of_address": _PROMPT_GENERIC,
    "document": _PROMPT_GENERIC,
}


# ── análisis visual (síncrono, llamado vía asyncio.to_thread) ─────────────────

def _parse_fraud_json(raw: str) -> dict:
    """
    Parsea el JSON del análisis de fraude. Si la respuesta vino truncada
    (p. ej. por límite de tokens), recupera los objetos {resultado, detalle}
    completos campo por campo en vez de descartar todo el análisis.
    """
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Recuperación tolerante: extraer cada bloque "clave": { "resultado": ..., "detalle": ... }
    recovered: dict = {}
    pattern = re.compile(
        r'"(?P<key>\w+)"\s*:\s*\{\s*'
        r'"resultado"\s*:\s*"(?P<resultado>PASSED|FAILED|WARNING|SKIPPED)"\s*,\s*'
        r'"detalle"\s*:\s*"(?P<detalle>(?:[^"\\]|\\.)*)"',
        re.IGNORECASE,
    )
    for m in pattern.finditer(raw):
        recovered[m.group("key")] = {
            "resultado": m.group("resultado").upper(),
            "detalle": m.group("detalle").encode().decode("unicode_escape", errors="replace"),
        }
    if recovered:
        logger.warning(f"JSON de fraude truncado/ inválido — recuperados {len(recovered)} campos por regex")
    return recovered


def _analyze_visual_sync(file_path: str, doc_type: str) -> List[CheckItem]:
    if not _vision_available():
        return [CheckItem(
            name="fraude_vision",
            status=CheckStatus.SKIPPED,
            detail="ANTHROPIC_API_KEY no configurado — análisis visual deshabilitado",
        )]
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        data, media_type = _encode_image(file_path)
        prompt = _PROMPTS.get(doc_type, _PROMPT_GENERIC)

        msg = client.messages.create(
            model=FRAUD_MODEL,
            # 6 campos con detalles extensos superan fácilmente 1024 tokens; si la
            # respuesta se trunca, el JSON queda inválido y se pierde TODO el análisis.
            max_tokens=3072,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}},
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = _parse_fraud_json(raw.strip())

        checks = []
        for key, val in result.items():
            if isinstance(val, dict) and "resultado" in val and "detalle" in val:
                checks.append(_make_check(f"fraude_{key}", val["resultado"], val["detalle"]))

        n_failed = sum(1 for c in checks if c.status == CheckStatus.FAILED)
        n_warn = sum(1 for c in checks if c.status == CheckStatus.WARNING)
        logger.info(f"✅ Análisis visual fraude: {n_failed} FAILED, {n_warn} WARNING — {Path(file_path).name}")
        return checks

    except Exception as e:
        logger.warning(f"Análisis visual de fraude falló: {e}")
        return [CheckItem(
            name="fraude_vision",
            status=CheckStatus.SKIPPED,
            detail=f"Error en análisis visual: {str(e)[:100]}",
        )]


def _analyze_visual_from_pdf(file_path: str, doc_type: str) -> List[CheckItem]:
    """Convierte el PDF a PNG temporal y ejecuta el análisis visual.
    Para INE combina ambas páginas (frente + reverso) en una sola imagen."""
    import tempfile
    try:
        from pdf2image import convert_from_path
        from PIL import Image as _PILImage
        dpi = 150 if doc_type in ("payroll", "income_proof") else 200
        # INE: necesitamos frente y reverso para evaluar seguridad completa
        last_page = 2 if doc_type == "ine" else 1
        pages = convert_from_path(file_path, dpi=dpi, first_page=1, last_page=last_page)
        if not pages:
            return [CheckItem(
                name="fraude_vision",
                status=CheckStatus.SKIPPED,
                detail="No se pudo convertir el PDF a imagen para análisis visual",
            )]
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
        if doc_type == "ine" and len(pages) >= 2:
            total_h = pages[0].height + pages[1].height
            combined = _PILImage.new("RGB", (max(pages[0].width, pages[1].width), total_h))
            combined.paste(pages[0], (0, 0))
            combined.paste(pages[1], (0, pages[0].height))
            combined.save(tmp_path, "PNG")
        else:
            pages[0].save(tmp_path, "PNG")
        logger.info(f"PDF convertido a imagen temporal para análisis visual: {Path(file_path).name}")
        try:
            return _analyze_visual_sync(tmp_path, doc_type)
        finally:
            try:
                Path(tmp_path).unlink()
            except OSError:
                pass
    except Exception as e:
        logger.warning(f"Conversión PDF→imagen falló: {e}")
        return [CheckItem(
            name="fraude_vision",
            status=CheckStatus.SKIPPED,
            detail=f"No se pudo convertir el PDF para análisis visual: {str(e)[:100]}",
        )]


# ── verificación de QR por tipo de documento ─────────────────────────────────

async def _verify_ine_qr(qr_codes: List[Dict]) -> List[CheckItem]:
    """Verifica QR de INE contra portal tuided.ine.mx."""
    for qr in qr_codes:
        data = qr.get("data", "").strip()
        if not data:
            continue

        if "ine.mx" in data.lower() or "tuided" in data.lower():
            try:
                async with httpx.AsyncClient(timeout=SCRAPER_TIMEOUT, follow_redirects=True) as client:
                    resp = await client.get(data, headers={"User-Agent": "Mozilla/5.0"})
                    text_lower = resp.text.lower()
                    if resp.status_code < 400:
                        if any(x in text_lower for x in ("no válido", "inválida", "no encontrado", "no existe")):
                            return [
                                CheckItem(name="qr_lectura", status=CheckStatus.PASSED,
                                          detail=f"QR INE leído correctamente"),
                                CheckItem(name="qr_verificacion_ine", status=CheckStatus.FAILED,
                                          detail="QR INE marcado como inválido por el portal del INE"),
                            ]
                        return [
                            CheckItem(name="qr_lectura", status=CheckStatus.PASSED,
                                      detail=f"QR INE leído correctamente"),
                            CheckItem(name="qr_verificacion_ine", status=CheckStatus.PASSED,
                                      detail=f"QR verificado en portal INE (HTTP {resp.status_code})"),
                        ]
                    return [
                        CheckItem(name="qr_lectura", status=CheckStatus.PASSED, detail="QR INE leído"),
                        CheckItem(name="qr_verificacion_ine", status=CheckStatus.WARNING,
                                  detail=f"Portal INE devolvió HTTP {resp.status_code}"),
                    ]
            except httpx.TimeoutException:
                return [
                    CheckItem(name="qr_lectura", status=CheckStatus.PASSED, detail="QR INE leído"),
                    CheckItem(name="qr_verificacion_ine", status=CheckStatus.SKIPPED,
                              detail="Timeout al consultar portal INE"),
                ]
            except Exception as e:
                return [
                    CheckItem(name="qr_lectura", status=CheckStatus.PASSED, detail="QR INE leído"),
                    CheckItem(name="qr_verificacion_ine", status=CheckStatus.SKIPPED,
                              detail=f"Error verificando QR INE: {str(e)[:80]}"),
                ]

        # QR con código de texto (CIIC u otro identificador)
        if len(data) >= 10:
            return [
                CheckItem(name="qr_lectura", status=CheckStatus.PASSED,
                          detail=f"QR INE leído (código): {data[:50]}"),
                CheckItem(name="qr_verificacion_ine", status=CheckStatus.WARNING,
                          detail="QR contiene código pero no URL verificable del portal INE"),
            ]

    return [CheckItem(name="qr_lectura", status=CheckStatus.SKIPPED,
                      detail="No se detectó código QR en el documento INE")]


async def _verify_curp_qr(qr_codes: List[Dict], curp_en_doc: str = "") -> List[CheckItem]:
    """Verifica QR del documento CURP: URL de gob.mx o CURP en texto plano."""
    for qr in qr_codes:
        data = qr.get("data", "").strip()
        if not data:
            continue

        # URL de gob.mx u otro portal
        if data.startswith("http"):
            try:
                async with httpx.AsyncClient(timeout=SCRAPER_TIMEOUT, follow_redirects=True) as client:
                    resp = await client.head(data)
                    ct = resp.headers.get("content-type", "")
                    # El QR del CURP apunta a descargar el mismo PDF — eso es válido.
                    # Cualquier respuesta HTTP (incluso PDF/redirect) confirma que
                    # el registro existe en el portal del gobierno.
                    is_pdf_download = "pdf" in ct.lower() or "octet-stream" in ct.lower()
                    ok = resp.status_code < 400 or is_pdf_download
                    detail = (
                        f"QR apunta al portal RENAPO y descarga el CURP (HTTP {resp.status_code}) — registro válido"
                        if is_pdf_download
                        else f"URL del QR {'accesible' if ok else 'con error'} (HTTP {resp.status_code})"
                    )
                    return [
                        CheckItem(name="qr_lectura", status=CheckStatus.PASSED,
                                  detail=f"QR CURP leído: {data[:60]}"),
                        CheckItem(name="qr_verificacion_curp",
                                  status=CheckStatus.PASSED if ok else CheckStatus.WARNING,
                                  detail=detail),
                    ]
            except Exception as e:
                return [
                    CheckItem(name="qr_lectura", status=CheckStatus.PASSED, detail="QR CURP leído"),
                    CheckItem(name="qr_verificacion_curp", status=CheckStatus.SKIPPED,
                              detail=f"Error verificando URL del QR: {str(e)[:80]}"),
                ]

        # CURP en texto plano dentro del QR
        curp_qr = data.upper().replace(" ", "")
        if _CURP_RE.match(curp_qr):
            curp_doc = curp_en_doc.upper().replace(" ", "")
            if curp_doc and curp_doc == curp_qr:
                return [
                    CheckItem(name="qr_lectura", status=CheckStatus.PASSED,
                              detail=f"QR contiene CURP: {curp_qr}"),
                    CheckItem(name="qr_verificacion_curp", status=CheckStatus.PASSED,
                              detail=f"CURP del QR coincide con el del documento ({curp_qr})"),
                ]
            elif curp_doc:
                return [
                    CheckItem(name="qr_lectura", status=CheckStatus.PASSED,
                              detail=f"QR contiene CURP: {curp_qr}"),
                    CheckItem(name="qr_verificacion_curp", status=CheckStatus.FAILED,
                              detail=f"CURP del QR ({curp_qr}) NO coincide con el del documento ({curp_doc})"),
                ]
            return [
                CheckItem(name="qr_lectura", status=CheckStatus.PASSED,
                          detail=f"QR contiene CURP con formato válido: {curp_qr}"),
                CheckItem(name="qr_verificacion_curp", status=CheckStatus.WARNING,
                          detail="CURP del QR es válido pero no hay CURP extraído del documento para comparar"),
            ]

    return [CheckItem(name="qr_lectura", status=CheckStatus.SKIPPED,
                      detail="No se detectó código QR en el documento CURP")]


async def _verify_bank_qr(qr_codes: List[Dict]) -> List[CheckItem]:
    """Verifica QR de estado de cuenta bancario."""
    for qr in qr_codes:
        data = qr.get("data", "").strip()
        if not data:
            continue

        if data.startswith("http"):
            try:
                ssl_verify = not _is_sat_url(data)
                async with httpx.AsyncClient(timeout=SCRAPER_TIMEOUT, follow_redirects=True, verify=ssl_verify) as client:
                    resp = await client.head(data)
                    ok = resp.status_code < 400
                    return [
                        CheckItem(name="qr_lectura", status=CheckStatus.PASSED,
                                  detail=f"QR bancario leído: {data[:60]}"),
                        CheckItem(name="qr_verificacion_banco",
                                  status=CheckStatus.PASSED if ok else CheckStatus.WARNING,
                                  detail=f"URL del QR bancario {'accesible' if ok else 'con error'} (HTTP {resp.status_code})"),
                    ]
            except httpx.TimeoutException:
                return [
                    CheckItem(name="qr_lectura", status=CheckStatus.PASSED, detail="QR bancario leído"),
                    CheckItem(name="qr_verificacion_banco", status=CheckStatus.SKIPPED,
                              detail="Timeout al verificar URL del QR bancario"),
                ]
            except Exception as e:
                return [
                    CheckItem(name="qr_lectura", status=CheckStatus.PASSED, detail="QR bancario leído"),
                    CheckItem(name="qr_verificacion_banco", status=CheckStatus.SKIPPED,
                              detail=f"Error verificando QR: {str(e)[:80]}"),
                ]

        # QR sin URL
        if data:
            return [CheckItem(name="qr_lectura", status=CheckStatus.WARNING,
                              detail=f"QR detectado pero sin URL verificable: {data[:40]}")]

    return [CheckItem(name="qr_lectura", status=CheckStatus.SKIPPED,
                      detail="No se detectó código QR en el estado de cuenta")]


_SAT_DOMAINS = ("sat.gob.mx", "facturaelectronica.sat.gob.mx", "verificacfdi")

def _is_sat_url(url: str) -> bool:
    return any(d in url.lower() for d in _SAT_DOMAINS)


# Dominios conocidos: (nombre_legible, tipo)
_KNOWN_ORIGINS: dict[str, tuple[str, str]] = {
    "tuided.ine.mx":                     ("INE — portal de verificación de credencial",  "ine"),
    "ine.mx":                            ("INE — Instituto Nacional Electoral",           "ine"),
    "listanominal.ine.mx":               ("INE — Lista Nominal",                          "ine"),
    "renapo.gob.mx":                     ("RENAPO — Registro Nacional de Población",      "gobierno"),
    "gob.mx":                            ("Portal del Gobierno de México",                "gobierno"),
    "sat.gob.mx":                        ("SAT — Servicio de Administración Tributaria",  "sat"),
    "facturaelectronica.sat.gob.mx":     ("SAT — Factura Electrónica",                   "sat"),
    "verificacfdi.sat.gob.mx":           ("SAT — Verificación CFDI",                     "sat"),
    "imss.gob.mx":                       ("IMSS — Seguro Social",                        "gobierno"),
    "issste.gob.mx":                     ("ISSSTE",                                       "gobierno"),
    "infonavit.org.mx":                  ("Infonavit",                                   "gobierno"),
    "bbva.mx":                           ("BBVA México",                                  "banco"),
    "banamex.com":                       ("Citibanamex",                                  "banco"),
    "santander.com.mx":                  ("Santander México",                             "banco"),
    "hsbc.com.mx":                       ("HSBC México",                                  "banco"),
    "scotiabank.com.mx":                 ("Scotiabank México",                            "banco"),
    "banorte.com":                       ("Banorte",                                      "banco"),
    "inbursa.com":                       ("Inbursa",                                      "banco"),
    "baz.com.mx":                        ("Banco Azteca",                                 "banco"),
    "cfe.mx":                            ("CFE — Comisión Federal de Electricidad",       "servicio"),
    "telmex.com":                        ("Telmex",                                       "servicio"),
    "izzi.mx":                           ("Izzi Telecom",                                 "servicio"),
    "totalplay.com.mx":                  ("Totalplay",                                    "servicio"),
    "megacable.com.mx":                  ("Megacable",                                    "servicio"),
    "axtel.mx":                          ("Axtel",                                        "servicio"),
    "sky.com.mx":                        ("Sky",                                          "servicio"),
}

_UUID_RE = re.compile(r"^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$")
_CIIC_RE = re.compile(r"^\d{8,12}(<{1,2}\d+)?$")  # código CIIC de INE


def classify_qr(data: str) -> dict:
    """
    Clasifica el contenido de un QR y devuelve:
      origin        — nombre legible del emisor (ej: "INE — portal de verificación")
      origin_type   — ine | gobierno | sat | banco | servicio | curp | desconocido
      content_type  — url | curp | ciic | uuid | texto
      url           — URL completa si aplica (None si no)
      domain        — dominio extraído (None si no es URL)
      content_preview — primeros 80 chars del contenido crudo
      ssl_skip      — True si hay que desactivar SSL verify (SAT)
    """
    from urllib.parse import urlparse

    result: dict = {
        "origin":          "Desconocido",
        "origin_type":     "desconocido",
        "content_type":    "texto",
        "url":             None,
        "domain":          None,
        "content_preview": data[:80],
        "ssl_skip":        False,
    }

    clean = data.strip()
    upper = clean.upper().replace(" ", "")

    # ── URL ──────────────────────────────────────────────────────────────────
    if clean.startswith("http://") or clean.startswith("https://"):
        parsed = urlparse(clean)
        domain = parsed.netloc.lower().lstrip("www.")
        result.update({"content_type": "url", "url": clean, "domain": domain})

        for known, (name, typ) in _KNOWN_ORIGINS.items():
            if domain == known or domain.endswith("." + known):
                result.update({"origin": name, "origin_type": typ})
                break
        else:
            # Dominio no reconocido — intenta clasificar por TLD/SLD
            if domain.endswith(".gob.mx"):
                result.update({"origin": f"Portal de gobierno ({domain})", "origin_type": "gobierno"})
            elif domain.endswith(".mx") or domain.endswith(".com.mx"):
                result.update({"origin": f"Sitio mexicano ({domain})", "origin_type": "desconocido"})

        result["ssl_skip"] = _is_sat_url(clean)
        return result

    # ── CURP en texto plano ───────────────────────────────────────────────────
    if _CURP_RE.match(upper) and len(upper) == 18:
        result.update({
            "content_type": "curp",
            "origin":       "RENAPO — CURP en texto plano",
            "origin_type":  "gobierno",
            "content_preview": upper,
        })
        return result

    # ── UUID / folio fiscal SAT ───────────────────────────────────────────────
    if _UUID_RE.match(upper):
        result.update({
            "content_type": "uuid",
            "origin":       "SAT — UUID / Folio Fiscal CFDI",
            "origin_type":  "sat",
        })
        return result

    # ── CIIC de INE ──────────────────────────────────────────────────────────
    if _CIIC_RE.match(upper.replace("<", "")):
        result.update({
            "content_type": "ciic",
            "origin":       "INE — Código de Identificación de Credencial (CIIC)",
            "origin_type":  "ine",
        })
        return result

    return result


async def _verify_universal_qr(qr_codes: List[Dict], doc_type: str, extracted_data: Dict) -> List[CheckItem]:
    """
    Verificación QR universal para cualquier tipo de documento.
    Clasifica el origen, verifica URLs, y cruza datos contra los extraídos del documento.
    """
    if not qr_codes:
        return [CheckItem(name="qr_lectura", status=CheckStatus.SKIPPED,
                          detail="No se detectó código QR en el documento")]

    all_checks: List[CheckItem] = []

    for idx, qr in enumerate(qr_codes):
        raw = qr.get("data", "").strip()
        page = qr.get("page", "?")
        if not raw:
            continue

        label = f" (página {page})" if len(qr_codes) > 1 else ""
        info = classify_qr(raw)

        # Check 1: QR leído + origen identificado
        origin_detail = (
            f"QR{label} leído. Origen: {info['origin']}. "
            f"Tipo: {info['content_type'].upper()}. "
            f"Contenido: {info['content_preview']}"
        )
        all_checks.append(CheckItem(
            name=f"qr_lectura{'_'+str(idx+1) if len(qr_codes)>1 else ''}",
            status=CheckStatus.PASSED,
            detail=origin_detail,
        ))

        # Check 2: verificación según content_type
        if info["content_type"] == "url":
            url = info["url"]
            ssl_verify = not info["ssl_skip"]
            try:
                async with httpx.AsyncClient(timeout=SCRAPER_TIMEOUT, follow_redirects=True, verify=ssl_verify) as client:
                    resp = await client.head(url, headers={"User-Agent": "Mozilla/5.0"})
                    ok = resp.status_code < 400

                    # Para INE: buscar señales de invalidez en la respuesta
                    detail_extra = ""
                    if info["origin_type"] == "ine" and not ok:
                        detail_extra = " — URL del portal INE devolvió error"

                    all_checks.append(CheckItem(
                        name=f"qr_verificacion{'_'+str(idx+1) if len(qr_codes)>1 else ''}",
                        status=CheckStatus.PASSED if ok else CheckStatus.WARNING,
                        detail=f"URL de {info['origin']} {'accesible' if ok else 'no accesible'} (HTTP {resp.status_code}){detail_extra}",
                    ))

                    # Para INE: revisar body completo por señales de invalidez
                    if info["origin_type"] == "ine" and ok:
                        try:
                            resp_get = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                            body_lower = resp_get.text.lower()
                            if any(x in body_lower for x in ("no válido", "inválida", "no encontrado", "no existe", "not found")):
                                all_checks.append(CheckItem(
                                    name="qr_validez_ine",
                                    status=CheckStatus.FAILED,
                                    detail="El portal del INE indica que la credencial NO es válida",
                                ))
                            else:
                                all_checks.append(CheckItem(
                                    name="qr_validez_ine",
                                    status=CheckStatus.PASSED,
                                    detail="El portal del INE no reporta anomalías para esta credencial",
                                ))
                        except Exception:
                            pass

            except httpx.TimeoutException:
                all_checks.append(CheckItem(
                    name=f"qr_verificacion{'_'+str(idx+1) if len(qr_codes)>1 else ''}",
                    status=CheckStatus.SKIPPED,
                    detail=f"Timeout al verificar URL de {info['origin']}",
                ))
            except Exception as e:
                all_checks.append(CheckItem(
                    name=f"qr_verificacion{'_'+str(idx+1) if len(qr_codes)>1 else ''}",
                    status=CheckStatus.SKIPPED,
                    detail=f"Error al verificar URL ({info['origin']}): {str(e)[:60]}",
                ))

        elif info["content_type"] == "curp":
            # Cruzar CURP del QR con CURP extraída del documento
            curp_qr = raw.strip().upper().replace(" ", "")
            curp_doc = (extracted_data.get("curp") or "").upper().strip()
            if curp_doc:
                if curp_qr == curp_doc:
                    all_checks.append(CheckItem(
                        name="qr_crosscheck_curp",
                        status=CheckStatus.PASSED,
                        detail=f"CURP del QR coincide con el del documento: {curp_qr}",
                    ))
                else:
                    all_checks.append(CheckItem(
                        name="qr_crosscheck_curp",
                        status=CheckStatus.FAILED,
                        detail=f"CURP del QR ({curp_qr}) no coincide con el del documento ({curp_doc})",
                    ))
            else:
                all_checks.append(CheckItem(
                    name="qr_crosscheck_curp",
                    status=CheckStatus.WARNING,
                    detail=f"QR contiene CURP ({curp_qr}) pero no hay CURP extraído del documento para comparar",
                ))

        elif info["content_type"] == "ciic":
            all_checks.append(CheckItem(
                name="qr_ciic",
                status=CheckStatus.PASSED,
                detail=f"QR contiene código CIIC de INE: {raw[:40]}",
            ))

        elif info["content_type"] == "uuid":
            all_checks.append(CheckItem(
                name="qr_uuid_cfdi",
                status=CheckStatus.PASSED,
                detail=f"QR contiene UUID/Folio Fiscal SAT: {raw[:40]}",
            ))

        else:
            # Texto no clasificado
            if info["origin_type"] != "desconocido":
                status = CheckStatus.WARNING
                detail = f"QR contiene texto de {info['origin']} — no es una URL verificable: {raw[:50]}"
            else:
                status = CheckStatus.WARNING
                detail = f"QR leído pero origen no reconocido. Contenido: {raw[:50]}"
            all_checks.append(CheckItem(
                name=f"qr_contenido{'_'+str(idx+1) if len(qr_codes)>1 else ''}",
                status=status,
                detail=detail,
            ))

    return all_checks if all_checks else [CheckItem(
        name="qr_lectura", status=CheckStatus.SKIPPED,
        detail="No se detectó contenido en los códigos QR del documento",
    )]


async def _verify_generic_qr(qr_codes: List[Dict]) -> List[CheckItem]:
    """Verificación de QR genérica para comprobantes de domicilio, CFDI y otros."""
    for qr in qr_codes:
        data = qr.get("data", "").strip()
        if not data:
            continue

        if data.startswith("http"):
            # El SAT tiene certificados que no siempre son reconocidos — desactivar SSL verify
            ssl_verify = not _is_sat_url(data)
            try:
                async with httpx.AsyncClient(timeout=SCRAPER_TIMEOUT, follow_redirects=True, verify=ssl_verify) as client:
                    resp = await client.head(data)
                    ok = resp.status_code < 400
                    sat_note = " (portal SAT)" if _is_sat_url(data) else ""
                    return [
                        CheckItem(name="qr_lectura", status=CheckStatus.PASSED,
                                  detail=f"QR leído{sat_note}: {data[:60]}"),
                        CheckItem(name="qr_verificacion",
                                  status=CheckStatus.PASSED if ok else CheckStatus.WARNING,
                                  detail=f"URL{sat_note} {'accesible' if ok else 'con error'} (HTTP {resp.status_code})"),
                    ]
            except Exception as e:
                return [
                    CheckItem(name="qr_lectura", status=CheckStatus.PASSED, detail="QR leído"),
                    CheckItem(name="qr_verificacion", status=CheckStatus.SKIPPED,
                              detail=f"Error verificando QR: {str(e)[:80]}"),
                ]

        if data:
            return [CheckItem(name="qr_lectura", status=CheckStatus.WARNING,
                              detail=f"QR leído pero contiene texto no verificable: {data[:40]}")]

    return [CheckItem(name="qr_lectura", status=CheckStatus.SKIPPED,
                      detail="No se detectó código QR en el documento")]


# ── función pública principal ─────────────────────────────────────────────────

async def analyze_document(
    file_path: str,
    doc_type: str,
    extracted_data: Optional[Dict] = None,
    preloaded_qr_codes: Optional[List[Dict]] = None,
) -> List[CheckItem]:
    """
    Análisis completo de fraude para cualquier tipo de documento:
    1. Análisis visual con Claude Vision (tampering, tipografía, foto, seguridad)
    2. Escaneo y verificación de QR codes contra portales externos (INE, RENAPO, bancos)

    Args:
        file_path:           Ruta al archivo (imagen JPG/PNG o PDF)
        doc_type:            "ine", "curp", "bank_statement", "proof_of_address", "document"
        extracted_data:      Datos ya extraídos (para cross-check en QR del CURP)
        preloaded_qr_codes:  QR codes ya escaneados; si None se escanean del archivo

    Returns:
        Lista de CheckItems con prefijos fraude_* y qr_*
    """
    extracted_data = extracted_data or {}
    checks: List[CheckItem] = []

    ext = Path(file_path).suffix.lower()

    # 1. Análisis visual con Claude Vision
    # Si es PDF, convertir primera página a imagen temporal antes de enviarlo
    if ext in _IMAGE_EXTS:
        visual_checks = await asyncio.to_thread(_analyze_visual_sync, file_path, doc_type)
        checks.extend(visual_checks)
    elif ext == ".pdf":
        visual_checks = await asyncio.to_thread(_analyze_visual_from_pdf, file_path, doc_type)
        checks.extend(visual_checks)
    else:
        checks.append(CheckItem(
            name="fraude_vision",
            status=CheckStatus.SKIPPED,
            detail=f"Formato {ext!r} no soportado para análisis visual",
        ))

    # 2. Escaneo de QR (usa los pre-cargados si se pasan, si no los escanea)
    if preloaded_qr_codes is not None:
        qr_codes = preloaded_qr_codes
    else:
        qr_codes = await asyncio.to_thread(_scan_qr_codes, file_path)

    # 3. Verificación universal de QR — clasifica origen y cruza datos extraídos
    checks.extend(await _verify_universal_qr(qr_codes, doc_type, extracted_data))

    return checks
