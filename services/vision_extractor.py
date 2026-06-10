"""
Claude Vision — extracción de datos de documentos de identidad y otros.
Se usa cuando pytesseract falla o el documento es una imagen de baja calidad.
"""
import base64
import json as _json_module
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")


def _parse_json_robust(text: str) -> dict:
    """
    Parses JSON from Claude responses that may include markdown fences,
    trailing commas, or extra commentary.
    """
    # Strip markdown fences
    raw = text.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        # parts[1] is inside the first fence pair
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    # Try strict parse first
    try:
        return _json_module.loads(raw)
    except _json_module.JSONDecodeError:
        pass

    # Find the outermost JSON object via brace matching
    start = raw.find("{")
    if start != -1:
        depth = 0
        end = start
        in_str = False
        escape = False
        for i, ch in enumerate(raw[start:], start):
            if escape:
                escape = False
                continue
            if ch == "\\" and in_str:
                escape = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        candidate = raw[start:end + 1]
        # Remove trailing commas before } or ]
        candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
        # Remove single-line comments
        candidate = re.sub(r"//[^\n]*", "", candidate)
        try:
            return _json_module.loads(candidate)
        except _json_module.JSONDecodeError as e:
            raise ValueError(f"No se pudo parsear JSON de Vision: {e}\nTexto: {raw[:300]}") from e

    raise ValueError(f"No se encontró objeto JSON en respuesta de Vision: {raw[:300]}")


def _is_available() -> bool:
    return bool(ANTHROPIC_API_KEY)


_MAX_IMAGE_BYTES = 4 * 1024 * 1024  # 4 MB — margen bajo el límite de 5 MB de Claude
_MAX_DIMENSION = 2000               # px máximos en el lado más largo


def _encode_image(path: str) -> tuple[str, str]:
    """
    Encodea imagen a base64 para Claude API.
    Redimensiona si supera 2000px o 4MB para evitar el error 413.
    """
    from PIL import Image as _PIL
    import io

    ext = Path(path).suffix.lower()
    media_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
    media_type = media_map.get(ext, "image/jpeg")

    with _PIL.open(path) as img:
        # Convertir a RGB si hace falta (RGBA, P, etc.)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        # Redimensionar si algún lado supera _MAX_DIMENSION
        w, h = img.size
        if max(w, h) > _MAX_DIMENSION:
            scale = _MAX_DIMENSION / max(w, h)
            img = img.resize((int(w * scale), int(h * scale)), _PIL.LANCZOS)

        # Encodear como JPEG con calidad 85 — siempre más pequeño que PNG
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85, optimize=True)

        # Si aún supera el límite, reducir calidad progresivamente
        quality = 75
        while buf.tell() > _MAX_IMAGE_BYTES and quality >= 50:
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality, optimize=True)
            quality -= 10

        buf.seek(0)
        data = base64.standard_b64encode(buf.read()).decode()

    logger.debug(f"Imagen encodada: {len(data) * 3 // 4 / 1024:.0f} KB")
    return data, "image/jpeg"


def extract_text_with_vision(image_path: str) -> str:
    """
    Usa Claude Vision para extraer TODO el texto visible de una imagen.
    Retorna string vacío si no está configurado o falla.
    """
    if not _is_available():
        logger.debug("ANTHROPIC_API_KEY no configurado — Vision deshabilitado")
        return ""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        data, media_type = _encode_image(image_path)

        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}},
                    {"type": "text", "text": (
                        "Transcribe exactamente todo el texto visible en este documento. "
                        "Incluye cada campo tal como aparece: nombres, apellidos, CURP, clave de elector, "
                        "domicilio, fechas, números. No interpretes ni traduzcas. Solo el texto literal."
                    )},
                ],
            }],
        )
        text = msg.content[0].text.strip()
        logger.info(f"✅ Claude Vision extrajo {len(text)} chars de {Path(image_path).name}")
        return text
    except Exception as e:
        logger.warning(f"Claude Vision falló: {e}")
        return ""


def _validate_ine_fields(raw: dict) -> dict:
    """
    Descarta campos INE que no cumplen formato exacto.
    Evita que valores truncados/corruptos pasen al pipeline de verificación.
    """
    out = {}
    for k, v in raw.items():
        if v is None:
            continue
        if k == "curp":
            v_clean = v.strip().upper().replace(" ", "")
            if len(v_clean) == 18:
                out[k] = v_clean
            else:
                logger.warning(f"CURP descartado (len={len(v_clean)}): '{v_clean}'")
        elif k == "voter_id":
            v_clean = v.strip().upper().replace(" ", "")
            if len(v_clean) == 18:
                out[k] = v_clean
            else:
                logger.warning(f"Clave de elector descartada (len={len(v_clean)}): '{v_clean}'")
        elif k == "mrz_line1":
            v_clean = v.strip().upper()
            if len(v_clean) == 30 and v_clean.startswith("ID"):
                out[k] = v_clean
            else:
                logger.warning(f"MRZ línea 1 descartada (len={len(v_clean)}): '{v_clean}'")
        elif k in ("mrz_line2", "mrz_line3"):
            v_clean = v.strip().upper()
            if len(v_clean) == 30:
                out[k] = v_clean
            else:
                logger.warning(f"{k} descartada (len={len(v_clean)}): '{v_clean}'")
        elif k == "sex":
            v_clean = v.strip().upper()
            if v_clean in ("H", "M"):
                out[k] = v_clean
        else:
            out[k] = v
    return out


def extract_ine_data_with_vision(image_path: str) -> dict:
    """
    Usa Claude Vision para extraer campos estructurados de una INE.
    Retorna dict con los campos encontrados (solo los que pasan validación de formato).
    """
    if not _is_available():
        return {}
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        data, media_type = _encode_image(image_path)

        prompt = """Analiza esta INE / Credencial para Votar mexicana y extrae los campos en JSON.
Si un campo no es visible o legible, usa null.

INSTRUCCIONES CRÍTICAS DE LONGITUD — cuenta los caracteres antes de responder:
- CURP: EXACTAMENTE 18 caracteres. Formato: 4 letras + AAMMDD + H/M + 2 letras estado + 3 consonantes + 2 caracteres homoclave. Si ves más o menos de 18 caracteres, relee la imagen.
- CLAVE DE ELECTOR: EXACTAMENTE 18 caracteres alfanuméricos, sin espacios. Si ves más o menos de 18, relee.
- MRZ LÍNEA 1: EXACTAMENTE 30 caracteres. Empieza con IDMEX seguido de 25 caracteres (letras, dígitos y <).
- MRZ LÍNEA 2: EXACTAMENTE 30 caracteres. Solo dígitos, letras mayúsculas y <.
- MRZ LÍNEA 3: EXACTAMENTE 30 caracteres. Nombre en mayúsculas con << separando apellidos y nombre, relleno con <.

ESTRUCTURA DE LA INE:
- FRENTE: campos NOMBRE, DOMICILIO, CURP, CLAVE DE ELECTOR, FECHA DE NACIMIENTO, VIGENCIA, SECCIÓN, foto.
- REVERSO: zona MRZ de 3 líneas de exactamente 30 caracteres cada una (empieza con IDMEX), código de barras y QR.

Transcribe la MRZ carácter por carácter. Es la parte más crítica del documento.

{
  "full_name": "apellido1 apellido2 nombre(s) tal como aparece en el campo NOMBRE del frente",
  "curp": "18 caracteres exactos del CURP",
  "voter_id": "18 caracteres exactos de la CLAVE DE ELECTOR (sin espacios)",
  "birth_date": "DD/MM/YYYY del campo FECHA DE NACIMIENTO",
  "expiration_date": "YYYY-YYYY del campo VIGENCIA",
  "address": "domicilio completo del campo DOMICILIO",
  "section": "número de sección electoral",
  "sex": "H o M",
  "state": "estado o entidad federativa",
  "mrz_line1": "30 caracteres exactos de la línea 1 del MRZ",
  "mrz_line2": "30 caracteres exactos de la línea 2 del MRZ",
  "mrz_line3": "30 caracteres exactos de la línea 3 del MRZ"
}

Responde SOLO con el JSON, sin texto adicional ni explicaciones."""

        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}},
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        raw = msg.content[0].text.strip()
        parsed = _parse_json_robust(raw)
        # Remove null values then validate field formats
        parsed = {k: v for k, v in parsed.items() if v is not None}
        result = _validate_ine_fields(parsed)
        logger.info(f"✅ Claude Vision extrajo {len(result)}/{len(parsed)} campos INE válidos de {Path(image_path).name}")
        return result
    except Exception as e:
        logger.warning(f"Claude Vision INE extractor falló: {e}")
        return {}


def extract_payroll_data_with_vision(image_path: str) -> dict:
    """
    Usa Claude Vision para extraer campos estructurados de un recibo de nómina / CFDI.
    Retorna dict con los campos encontrados.
    """
    if not _is_available():
        return {}
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        data, media_type = _encode_image(image_path)

        prompt = """Analiza este recibo de nómina o CFDI de nómina mexicano y extrae los campos en JSON.
Si un campo no es visible, usa null.

{
  "employee_name": "Nombre completo del trabajador/empleado",
  "employer_name": "Razón social o nombre de la empresa que paga",
  "employee_rfc": "RFC del trabajador (13 caracteres)",
  "employer_rfc": "RFC del patrón/empresa (12 caracteres)",
  "gross_salary": 0.00,
  "net_salary": 0.00,
  "payment_period": "período de pago (fechas)",
  "position": "puesto o cargo del empleado",
  "cfdi_uuid": "UUID / folio fiscal del CFDI si está presente"
}

IMPORTANTE:
- employee_name es el NOMBRE DE LA PERSONA, NO el nombre del campo "PUESTO" ni "CARGO".
- gross_salary es el total de percepciones (número, sin signos).
- net_salary es el neto a pagar / líquido (número, sin signos).

Responde SOLO con el JSON, sin texto adicional."""

        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}},
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        raw = msg.content[0].text.strip()
        result = _parse_json_robust(raw)
        result = {k: v for k, v in result.items() if v is not None}
        logger.info(f"✅ Claude Vision extrajo {len(result)} campos nómina de {Path(image_path).name}")
        return result
    except Exception as e:
        logger.warning(f"Claude Vision nómina extractor falló: {e}")
        return {}
