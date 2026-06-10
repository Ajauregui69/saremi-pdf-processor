"""
Verificador de INE / Credencial para Votar
Checks: formato, cross-check CURP↔nombre, vigencia, consulta padrón INE
"""

import re
import logging
import os
from datetime import date
from typing import Dict, List, Optional

import httpx
from bs4 import BeautifulSoup

from models.verification_schemas import CheckItem
from services.verifiers.base_verifier import BaseVerifier

logger = logging.getLogger(__name__)

INE_PORTAL_URL = os.getenv(
    "INE_PORTAL_URL",
    "https://listanominal.ine.mx/app/DGICERG/listaNominal",
)
SCRAPER_TIMEOUT = int(os.getenv("SCRAPER_TIMEOUT_SECONDS", "15"))

# Regex clave de elector: 6 letras + 8 dígitos + H/M + 3 dígitos
_CLAVE_ELECTOR_RE = re.compile(r"^[A-Z]{6}\d{8}[HM]\d{3}$")
# Regex CURP
_CURP_RE = re.compile(r"^[A-Z]{4}\d{6}[HM][A-Z]{5}[0-9A-Z]\d$")

# Entidades válidas en CURP (posición 9-10)
_ENTIDADES_CURP = {
    "AS", "BC", "BS", "CC", "CL", "CM", "CS", "CH", "DF", "DG",
    "GT", "GR", "HG", "JC", "MC", "MN", "MS", "NT", "NL", "OC",
    "PL", "QT", "QR", "SP", "SL", "SR", "TC", "TS", "TL", "VZ",
    "YN", "ZS", "NE",
}


class INEVerifier(BaseVerifier):
    """Verifica autenticidad de una INE/Credencial para Votar."""

    async def verify(
        self,
        file_path: str,
        extracted_data: Dict,
        preloaded_qr_codes: Optional[List] = None,
    ) -> List[CheckItem]:
        checks: List[CheckItem] = []

        voter_id: str = extracted_data.get("voter_id", "")
        curp: str = extracted_data.get("curp", "")
        full_name: str = extracted_data.get("full_name", "")
        expiration_date: str = extracted_data.get("expiration_date", "")

        # 1. Formato de clave de elector
        checks.append(self._check_voter_id_format(voter_id))

        # 2. Formato de CURP
        checks.append(self._check_curp_format(curp))

        # 3. Cross-check CURP ↔ nombre (primeras letras)
        if curp and full_name:
            checks.append(self._check_curp_name_crosscheck(curp, full_name))
        else:
            checks.append(self._skipped("cross_check_curp_nombre", "Nombre o CURP no disponible para cross-check"))

        # 4. Vigencia
        checks.append(self._check_expiry(expiration_date))

        # 5. Consulta padrón INE (scraper)
        if voter_id and len(voter_id) == 18:
            scraper_check = await self._query_ine_portal(voter_id)
            checks.append(scraper_check)
        else:
            checks.append(self._skipped("padron_ine", "Clave de elector no disponible o mal formateada para consultar el padrón"))

        # 6. Verificar que vengan los dos lados de la credencial
        checks.append(await self._check_both_sides(file_path))

        # 7. Integridad de la MRZ (check digits ICAO 9303)
        checks.append(self._check_mrz_integrity(extracted_data))

        # 8. Cross-check fechas de nacimiento entre todas las fuentes
        checks.append(self._check_dob_consistency(extracted_data))

        # 9. Cross-check nombre MRZ vs frente
        checks.append(self._check_mrz_name_vs_front(extracted_data))

        # 10. Análisis de fraude visual + verificación de QR (usa QR pre-escaneados si disponibles)
        checks.extend(await self._run_fraud_analysis(
            file_path, "ine", extracted_data, preloaded_qr_codes=preloaded_qr_codes
        ))

        return checks

    # ── checks internos ───────────────────────────────────────────────────────

    def _check_mrz_integrity(self, extracted_data: Dict) -> CheckItem:
        """
        Valida los dígitos verificadores de la MRZ (ICAO 9303).
        Un check digit incorrecto indica manipulación de la zona MRZ.
        """
        mrz = extracted_data.get("mrz")
        if not mrz:
            return self._skipped("mrz_integridad", "Zona MRZ no detectada en el documento (se requiere el reverso)")

        results = []
        all_ok = True

        checks_map = [
            ("dob_check_ok",       "DOB",        f"Fuente: MRZ línea 2, posiciones 1-7 (fecha {mrz.get('dob_raw', '?')})"),
            ("expiry_check_ok",    "Vencimiento", f"Fuente: MRZ línea 2, posiciones 9-15 ({mrz.get('expiry_raw', '?')})"),
            ("composite_check_ok", "Compuesto",  "Fuente: MRZ línea 2, posición 30 (valida toda la MRZ)"),
        ]
        for key, label, source in checks_map:
            val = mrz.get(key)
            if val is None:
                results.append(f"{label}: no evaluable")
            elif val:
                results.append(f"{label}: ✓")
            else:
                results.append(f"{label}: ✗ INVÁLIDO — {source}")
                all_ok = False

        detail = " | ".join(results)
        if all_ok:
            return self._passed("mrz_integridad", f"Todos los dígitos verificadores MRZ son correctos. {detail}")

        return self._failed(
            "mrz_integridad",
            f"Dígito(s) verificador(es) MRZ inválidos — posible manipulación del reverso. {detail}",
        )

    def _check_dob_consistency(self, extracted_data: Dict) -> CheckItem:
        """
        Compara la fecha de nacimiento entre TODAS las fuentes disponibles:
        - Campo FECHA DE NACIMIENTO del frente (birth_date)
        - Zona MRZ del reverso (dob_mrz)
        - Fecha codificada en la clave de elector posiciones 7-12 (dob_clave_elector)
        Las tres deben coincidir en una INE auténtica.
        """
        sources: Dict[str, str] = {}
        if extracted_data.get("birth_date"):
            sources["Frente (campo FECHA DE NACIMIENTO)"] = extracted_data["birth_date"]
        if extracted_data.get("dob_mrz"):
            sources["Reverso (MRZ línea 2, pos. 1-6)"] = extracted_data["dob_mrz"]
        if extracted_data.get("dob_clave_elector"):
            sources["Clave de elector (pos. 7-12)"] = extracted_data["dob_clave_elector"]

        if len(sources) < 2:
            return self._skipped(
                "cross_check_fecha_nacimiento",
                f"Solo se encontró {len(sources)} fuente(s) de fecha de nacimiento; se necesitan al menos 2 para comparar. "
                f"Disponibles: {', '.join(sources.keys()) or 'ninguna'}",
            )

        # Normalizar a DD/MM/YYYY para comparar
        def _normalize(d: str) -> str:
            d = d.strip().replace("-", "/")
            parts = d.split("/")
            if len(parts) == 3 and len(parts[2]) == 4:
                return f"{parts[0].zfill(2)}/{parts[1].zfill(2)}/{parts[2]}"
            return d

        normalized = {src: _normalize(val) for src, val in sources.items()}
        unique_values = set(normalized.values())

        source_detail = " | ".join(f"{src}: '{val}'" for src, val in normalized.items())

        if len(unique_values) == 1:
            return self._passed(
                "cross_check_fecha_nacimiento",
                f"Fecha de nacimiento consistente en {len(sources)} fuentes. {source_detail}",
            )

        return self._failed(
            "cross_check_fecha_nacimiento",
            f"CONFLICTO: fechas de nacimiento distintas entre fuentes — posible falsificación. {source_detail}",
        )

    def _check_mrz_name_vs_front(self, extracted_data: Dict) -> CheckItem:
        """
        Compara el nombre en la MRZ (reverso) con el nombre del frente del documento.
        Fuentes: 'name_mrz' (MRZ línea 3) vs 'full_name' (campo NOMBRE del frente).
        """
        name_mrz: str = extracted_data.get("name_mrz", "")
        name_front: str = extracted_data.get("full_name", "")

        if not name_mrz or not name_front:
            missing = []
            if not name_mrz:
                missing.append("nombre en MRZ")
            if not name_front:
                missing.append("nombre en frente")
            return self._skipped(
                "cross_check_nombre_mrz",
                f"No disponible: {', '.join(missing)}. No se puede comparar.",
            )

        def _tokens(s: str):
            return set(re.sub(r'[^A-ZÁÉÍÓÚÑ ]', '', s.upper()).split())

        tokens_mrz   = _tokens(name_mrz)
        tokens_front = _tokens(name_front)

        if not tokens_mrz or not tokens_front:
            return self._skipped("cross_check_nombre_mrz", "Tokens de nombre vacíos tras normalización")

        intersection = tokens_mrz & tokens_front
        overlap = len(intersection) / max(len(tokens_mrz), len(tokens_front))

        detail = (
            f"Frente (campo NOMBRE): '{name_front}' | "
            f"Reverso (MRZ línea 3): '{name_mrz}' | "
            f"Coincidencia: {overlap:.0%}"
        )

        if overlap >= 0.7:
            return self._passed("cross_check_nombre_mrz", f"Nombre consistente entre frente y MRZ. {detail}")
        if overlap >= 0.4:
            return self._warning("cross_check_nombre_mrz", f"Nombre parcialmente diferente entre frente y MRZ — verificar manualmente. {detail}")
        return self._failed(
            "cross_check_nombre_mrz",
            f"CONFLICTO: nombre en MRZ difiere significativamente del frente. {detail}",
        )

    def _check_voter_id_format(self, voter_id: str) -> CheckItem:
        if not voter_id:
            return self._skipped("formato_clave_elector", "No se pudo extraer la clave de elector (OCR insuficiente o imagen borrosa)")
        if _CLAVE_ELECTOR_RE.match(voter_id):
            return self._passed("formato_clave_elector", f"Clave de elector con formato válido: {voter_id}")
        # WARNING en lugar de FAILED: el OCR de escaneos produce lecturas corruptas frecuentemente.
        # Un formato inválido no confirma falsificación — puede ser error de captura.
        return self._warning("formato_clave_elector", f"Clave de elector no pudo leerse con claridad (posible error OCR en escaneo): {voter_id!r}")

    def _check_curp_format(self, curp: str) -> CheckItem:
        if not curp:
            return self._skipped("formato_curp", "No se pudo extraer el CURP (OCR insuficiente o imagen borrosa)")
        clean = curp.replace(" ", "").upper()
        if not _CURP_RE.match(clean):
            # WARNING: OCR en escaneos de baja calidad produce CURPs truncados o corruptos.
            # Formato inválido no confirma falsificación por sí solo.
            return self._warning("formato_curp", f"CURP no pudo leerse con claridad (posible error OCR en escaneo): {clean!r}")
        # Validar entidad federativa (posición 11-12, índice 11:13)
        entidad = clean[11:13]
        if entidad not in _ENTIDADES_CURP:
            return self._warning("formato_curp", f"Entidad federativa desconocida en CURP: {entidad}")
        return self._passed("formato_curp", f"CURP con formato válido: {clean}")

    def _check_curp_name_crosscheck(self, curp: str, full_name: str) -> CheckItem:
        """
        Los primeros 4 caracteres del CURP codifican:
        [0] Primera letra del primer apellido
        [1] Primera vocal interna del primer apellido
        [2] Primera letra del segundo apellido
        [3] Primera letra del nombre
        Validamos que al menos el primer carácter coincida con el nombre.
        """
        curp_clean = curp.replace(" ", "").upper()
        name_parts = full_name.upper().split()
        if not name_parts:
            return self._skipped("cross_check_curp_nombre", "Nombre vacío, no se puede validar")

        # La primer letra del primer apellido debe ser CURP[0]
        primer_apellido = name_parts[0] if len(name_parts) >= 1 else ""
        if primer_apellido and primer_apellido[0] == curp_clean[0]:
            return self._passed("cross_check_curp_nombre", f"Primera letra del apellido ({primer_apellido[0]}) coincide con CURP[0]")
        return self._warning(
            "cross_check_curp_nombre",
            f"Primera letra del apellido ({primer_apellido[:1]!r}) no coincide con CURP[0] ({curp_clean[0]!r}). Verificar manualmente.",
        )

    def _check_expiry(self, expiration_date: str) -> CheckItem:
        if not expiration_date:
            return self._skipped("vigencia", "No se encontró fecha de vigencia en el documento")
        current_year = date.today().year
        try:
            clean = expiration_date.strip().replace(" ", "")
            # Formato rango "2020-2030" o "2020/2030" — tomar el ÚLTIMO año
            range_match = re.search(r'(\d{4})[/\-](\d{4})', clean)
            if range_match:
                expiry_year = int(range_match.group(2))
            elif len(clean) == 4 and clean.isdigit():
                expiry_year = int(clean)
            else:
                # dd/mm/yyyy — tomar el año (último segmento)
                parts = re.split(r'[/\-]', clean)
                year_candidates = [p for p in parts if len(p) == 4 and p.isdigit()]
                if not year_candidates:
                    raise ValueError("sin año")
                expiry_year = int(year_candidates[-1])

            if expiry_year < current_year:
                return self._failed("vigencia", f"INE vencida: vigencia hasta {expiry_year}, año actual {current_year}")
            return self._passed("vigencia", f"INE vigente hasta {expiry_year}")
        except (ValueError, IndexError, AttributeError):
            return self._skipped("vigencia", f"No se pudo interpretar la fecha de vigencia: {expiration_date!r}")

    async def _check_both_sides(self, file_path: str) -> CheckItem:
        """Verifica con Claude Vision que el documento incluya ambos lados de la credencial."""
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            return self._skipped("ambos_lados_ine", "ANTHROPIC_API_KEY no configurado")
        try:
            import asyncio, anthropic, base64
            from pathlib import Path as _Path

            ext = _Path(file_path).suffix.lower()
            image_path = file_path

            if ext == ".pdf":
                try:
                    from pdf2image import convert_from_path
                    import tempfile
                    pages = convert_from_path(file_path, dpi=150, first_page=1, last_page=2)
                    if not pages:
                        return self._skipped("ambos_lados_ine", "No se pudo convertir el PDF para inspección visual")
                    # Unir las dos páginas en una imagen vertical si hay dos páginas
                    from PIL import Image
                    if len(pages) >= 2:
                        total_h = pages[0].height + pages[1].height
                        combined = Image.new("RGB", (max(pages[0].width, pages[1].width), total_h))
                        combined.paste(pages[0], (0, 0))
                        combined.paste(pages[1], (0, pages[0].height))
                    else:
                        combined = pages[0]
                    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as vf:
                        image_path = vf.name
                    combined.save(image_path, "PNG")
                    ext = ".png"
                except Exception as e:
                    logger.warning(f"pdf2image falló en check_both_sides: {e}")
                    return self._skipped("ambos_lados_ine", "No se pudo procesar el archivo para verificar ambos lados")

            from services.vision_extractor import _encode_image as _enc
            img_data, media_type = _enc(image_path)

            if image_path != file_path:
                try:
                    import os as _os
                    _os.unlink(image_path)
                except OSError:
                    pass

            client = anthropic.Anthropic(api_key=api_key)

            def _call():
                return client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=64,
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": img_data}},
                            {"type": "text", "text": (
                                "En esta imagen de una INE/Credencial para Votar mexicana, "
                                "¿se pueden ver AMBOS lados de la credencial (frente con foto y reverso con domicilio/firma)? "
                                "Responde SOLO: AMBOS, SOLO_FRENTE, SOLO_REVERSO, o NO_DETERMINABLE."
                            )},
                        ],
                    }],
                )

            msg = await asyncio.to_thread(_call)
            answer = msg.content[0].text.strip().upper().split()[0]

            if "AMBOS" in answer:
                return self._passed("ambos_lados_ine", "Se verificaron ambos lados de la credencial (frente y reverso)")
            if "SOLO_FRENTE" in answer or "FRENTE" in answer:
                return self._failed("ambos_lados_ine", "Solo se detectó el frente de la INE — se requiere también el reverso para verificación completa")
            if "SOLO_REVERSO" in answer or "REVERSO" in answer:
                return self._failed("ambos_lados_ine", "Solo se detectó el reverso de la INE — se requiere también el frente con fotografía")
            return self._warning("ambos_lados_ine", f"No se pudo determinar si ambos lados están presentes: {answer}")

        except Exception as e:
            logger.warning(f"Check ambos lados INE falló: {e}")
            return self._skipped("ambos_lados_ine", f"Error al verificar ambos lados: {str(e)[:80]}")

    async def _query_ine_portal(self, clave_elector: str) -> CheckItem:
        """
        Consulta el portal de Lista Nominal del INE para verificar si la clave
        de elector existe y está activa en el padrón.
        """
        try:
            async with httpx.AsyncClient(timeout=SCRAPER_TIMEOUT, follow_redirects=True) as client:
                # Paso 1: GET para obtener CSRF token / cookies
                resp_get = await client.get(INE_PORTAL_URL, headers={"User-Agent": "Mozilla/5.0"})
                if resp_get.status_code in (403, 429):
                    return self._skipped("padron_ine", f"El portal del INE no permite consultas automáticas (HTTP {resp_get.status_code}) — verificar manualmente en listanominal.ine.mx")
                resp_get.raise_for_status()

                soup = BeautifulSoup(resp_get.text, "lxml")
                csrf_input = soup.find("input", {"name": "_token"}) or soup.find("input", {"name": "csrf_token"})
                csrf_token = csrf_input["value"] if csrf_input else ""

                # Paso 2: POST con la clave de elector
                payload = {
                    "claveElector": clave_elector,
                    "_token": csrf_token,
                }
                resp_post = await client.post(INE_PORTAL_URL, data=payload)
                resp_post.raise_for_status()

                soup_resp = BeautifulSoup(resp_post.text, "lxml")
                text_lower = soup_resp.get_text().lower()

                if "no encontrado" in text_lower or "no existe" in text_lower:
                    return self._failed("padron_ine", "Clave de elector NO encontrada en el padrón del INE")
                if "encontrado" in text_lower or "activo" in text_lower or "vigente" in text_lower:
                    return self._passed("padron_ine", "Clave de elector encontrada y activa en el padrón del INE")

                # Respuesta ambigua
                return self._warning("padron_ine", "Respuesta del portal INE no concluyente; verificar manualmente")

        except httpx.TimeoutException:
            logger.warning("Timeout consultando portal INE")
            return self._skipped("padron_ine", "Timeout al consultar el padrón del INE — verificar manualmente en listanominal.ine.mx")
        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            if code in (403, 429):
                logger.warning(f"Portal INE bloqueó la consulta automática (HTTP {code})")
                return self._skipped("padron_ine", f"El portal del INE no permite consultas automáticas (HTTP {code}) — verificar manualmente en listanominal.ine.mx")
            logger.warning(f"Error HTTP consultando portal INE: {e}")
            return self._skipped("padron_ine", f"Portal INE devolvió HTTP {code} — verificar manualmente")
        except Exception as e:
            logger.warning(f"Error consultando portal INE: {e}")
            return self._skipped("padron_ine", "No se pudo consultar el padrón del INE — verificar manualmente en listanominal.ine.mx")
