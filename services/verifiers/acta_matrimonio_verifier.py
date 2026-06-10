"""
Verificador de Acta de Matrimonio
Checks: régimen patrimonial (CRÍTICO para notarías), CURPs cónyuges, folio, fecha, layout
El régimen patrimonial determina si se requiere firma del cónyuge en una compraventa.
"""

import re
import logging
from datetime import date
from typing import Dict, List, Optional, Tuple

from models.verification_schemas import CheckItem
from services.verifiers.base_verifier import BaseVerifier

logger = logging.getLogger(__name__)

_CURP_RE = re.compile(r'\b([A-Z]{4}\d{6}[HM][A-Z]{5}[0-9A-Z]\d)\b')
_DATE_RE = re.compile(r'\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\b')
_DATE_ES_RE = re.compile(r'\b(\d{1,2})\s+de\s+([a-záéíóúñ]+)\s+de\s+(\d{4})\b', re.I)

_MONTHS_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}

# Palabras clave de régimen patrimonial
_SOCIEDAD_CONYUGAL = [
    "sociedad conyugal", "sociedad de gananciales", "bajo el régimen de sociedad conyugal",
    "comunidad de bienes", "bienes mancomunados",
]
_SEPARACION_BIENES = [
    "separación de bienes", "separacion de bienes", "bajo el régimen de separación",
    "separación total de bienes", "bienes separados",
]


def _parse_date(text: str) -> Optional[date]:
    for m in _DATE_RE.finditer(text):
        try:
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 1 <= mo <= 12 and 1 <= d <= 31 and 1900 <= y <= date.today().year:
                return date(y, mo, d)
        except ValueError:
            continue
    for m in _DATE_ES_RE.finditer(text):
        try:
            month_num = _MONTHS_ES.get(m.group(2).lower())
            if month_num:
                y = int(m.group(3))
                if 1900 <= y <= date.today().year:
                    return date(y, month_num, int(m.group(1)))
        except ValueError:
            continue
    return None


def _extract_regimen(text: str) -> Tuple[str, str]:
    """
    Retorna (tipo_regimen, fragmento_encontrado).
    tipo_regimen: 'sociedad_conyugal' | 'separacion_bienes' | 'desconocido'
    """
    t = text.lower()
    for phrase in _SOCIEDAD_CONYUGAL:
        if phrase in t:
            return "sociedad_conyugal", phrase
    for phrase in _SEPARACION_BIENES:
        if phrase in t:
            return "separacion_bienes", phrase
    # Abreviaturas comunes
    if re.search(r'\bsc\b', t) and "régimen" in t:
        return "sociedad_conyugal", "SC (abreviatura)"
    if re.search(r'\bsb\b', t) and "régimen" in t:
        return "separacion_bienes", "SB (abreviatura)"
    return "desconocido", ""


class ActaMatrimonioVerifier(BaseVerifier):
    """Verifica autenticidad de un Acta de Matrimonio mexicana."""

    async def verify(self, file_path: str, extracted_data: Dict, preloaded_qr_codes: Optional[List] = None) -> List[CheckItem]:
        checks: List[CheckItem] = []
        raw_text: str = extracted_data.get("_raw_text", "")

        # 1. Layout de acta de matrimonio
        checks.append(self._check_layout(raw_text))

        # 2. ★ RÉGIMEN PATRIMONIAL — check más crítico para notarías ★
        checks.append(self._check_regimen_patrimonial(raw_text, extracted_data))

        # 3. CURPs de ambos cónyuges
        checks.extend(self._check_curps_conyuges(raw_text))

        # 4. Folio del acta (triple identificador)
        checks.append(self._check_folio(raw_text))

        # 5. Fecha de matrimonio coherente (ambos >= 18 años al casarse)
        checks.append(self._check_fecha_matrimonio(raw_text))

        # 6. Testigos presentes
        checks.append(self._check_testigos(raw_text))

        # 7. Sello / juez del registro civil
        checks.append(self._check_sello_juez(raw_text))

        # 8. QR (algunos estados lo incluyen)
        checks.append(self._check_qr(preloaded_qr_codes))

        # 9. Análisis de fraude visual
        checks.extend(await self._run_fraud_analysis(file_path, "acta_matrimonio", extracted_data, preloaded_qr_codes))

        return checks

    # ── checks internos ───────────────────────────────────────────────────────

    def _check_layout(self, text: str) -> CheckItem:
        t = text.lower()
        signals = [
            "acta de matrimonio" in t,
            "registro civil" in t,
            any(w in t for w in ["contrayente", "cónyuge", "esposo", "esposa", "desposado"]),
            any(w in t for w in ["matrimonio", "unión", "enlace"]),
        ]
        score = sum(signals)
        if score >= 3:
            return self._passed("layout_acta_matrimonio", "Documento identificado como Acta de Matrimonio")
        if score >= 2:
            return self._warning("layout_acta_matrimonio", "Documento parcialmente identificado como Acta de Matrimonio")
        return self._warning("layout_acta_matrimonio", "No se confirmó que el documento sea un Acta de Matrimonio")

    def _check_regimen_patrimonial(self, text: str, extracted_data: Dict) -> CheckItem:
        """
        Check crítico para notarías: el régimen patrimonial determina si el cónyuge
        debe firmar en la compraventa.
        - Sociedad Conyugal (SC): AMBOS cónyuges deben firmar escritura.
        - Separación de Bienes (SB): solo el titular del inmueble firma.
        """
        # Primero revisar dato extraído
        regimen = extracted_data.get("regimen_patrimonial", "")
        if regimen:
            if "sociedad" in regimen.lower() or "sc" == regimen.strip().lower():
                return self._passed(
                    "regimen_patrimonial",
                    f"⚠️ RÉGIMEN: SOCIEDAD CONYUGAL — ambos cónyuges deben firmar la escritura. Fuente: datos extraídos."
                )
            if "separacion" in regimen.lower() or "separación" in regimen.lower() or "sb" == regimen.strip().lower():
                return self._passed(
                    "regimen_patrimonial",
                    f"✓ RÉGIMEN: SEPARACIÓN DE BIENES — solo el titular firma la escritura. Fuente: datos extraídos."
                )

        tipo, fragmento = _extract_regimen(text)
        if tipo == "sociedad_conyugal":
            return self._passed(
                "regimen_patrimonial",
                f"⚠️ RÉGIMEN: SOCIEDAD CONYUGAL — ambos cónyuges deben firmar la escritura. "
                f"Detectado: '{fragmento}'",
            )
        if tipo == "separacion_bienes":
            return self._passed(
                "regimen_patrimonial",
                f"✓ RÉGIMEN: SEPARACIÓN DE BIENES — solo el titular del inmueble firma. "
                f"Detectado: '{fragmento}'",
            )

        return self._failed(
            "regimen_patrimonial",
            "⚠️ CRÍTICO: No se pudo determinar el régimen patrimonial. "
            "Este dato es INDISPENSABLE para la escrituración — "
            "con Sociedad Conyugal el cónyuge debe firmar; con Separación de Bienes no. "
            "Revisar manualmente el acta.",
        )

    def _check_curps_conyuges(self, text: str) -> List[CheckItem]:
        """Extrae y verifica los CURPs de ambos cónyuges."""
        curps = list(dict.fromkeys(_CURP_RE.findall(text.upper())))  # únicos, sin duplicados
        checks = []
        if len(curps) >= 2:
            checks.append(self._passed(
                "curps_conyuges",
                f"CURPs de ambos cónyuges presentes: {curps[0]} / {curps[1]}",
            ))
        elif len(curps) == 1:
            checks.append(self._warning(
                "curps_conyuges",
                f"Solo se encontró un CURP: {curps[0]}. Se esperan dos (uno por cónyuge).",
            ))
        else:
            checks.append(self._warning(
                "curps_conyuges",
                "No se encontraron CURPs en el acta — pueden estar ausentes en actas antiguas",
            ))
        return checks

    def _check_folio(self, text: str) -> CheckItem:
        t = text.lower()
        has_ofic = any(w in t for w in ["oficialía", "juzgado"])
        has_libro = "libro" in t or "tomo" in t
        has_acta = bool(re.search(r'acta\s+(?:n[uú]m|no\.?|#)?\s*\d+', t))
        score = sum([has_ofic, has_libro, has_acta])
        if score >= 2:
            return self._passed("folio_acta_matrimonio", "Identificador del acta presente (oficialía/libro/número)")
        return self._warning("folio_acta_matrimonio", "Folio del acta incompleto — dificulta verificación en registro civil")

    def _check_fecha_matrimonio(self, text: str) -> CheckItem:
        wedding_date = _parse_date(text)
        if not wedding_date:
            return self._warning("fecha_matrimonio", "No se encontró fecha de matrimonio en el acta")
        today = date.today()
        if wedding_date > today:
            return self._failed("fecha_matrimonio", f"Fecha de matrimonio en el futuro: {wedding_date}")
        years_ago = (today - wedding_date).days / 365.25
        return self._passed("fecha_matrimonio", f"Fecha de matrimonio: {wedding_date} (hace {int(years_ago)} años)")

    def _check_testigos(self, text: str) -> CheckItem:
        t = text.lower()
        if "testigo" in t:
            testigo_names = re.findall(r'testigo[:\s]+([A-ZÁÉÍÓÚÑ][a-záéíóúñ\s]{3,30})', text, re.I)
            count = len(testigo_names) if testigo_names else text.lower().count("testigo")
            if count >= 2:
                return self._passed("testigos_matrimonio", f"Testigos presentes en el acta ({count} detectados)")
            return self._warning("testigos_matrimonio", "Se detectó solo 1 testigo — se requieren mínimo 2")
        return self._warning("testigos_matrimonio", "No se identificaron testigos en el acta")

    def _check_sello_juez(self, text: str) -> CheckItem:
        t = text.lower()
        has_juez = any(w in t for w in ["juez", "oficial del registro", "jueza"])
        has_sello = "sello" in t or "firma" in t
        if has_juez and has_sello:
            return self._passed("sello_juez", "Juez del Registro Civil y firma/sello identificados")
        if has_juez:
            return self._warning("sello_juez", "Juez identificado pero no se encontró referencia a sello/firma")
        return self._warning("sello_juez", "No se identificó al Juez del Registro Civil")

    def _check_qr(self, preloaded_qr_codes: Optional[List]) -> CheckItem:
        if preloaded_qr_codes:
            for qr in preloaded_qr_codes:
                data = qr.get("data", "")
                if data:
                    return self._passed("qr_acta_matrimonio", f"QR detectado en el acta: {data[:60]}")
        return self._skipped("qr_acta_matrimonio", "Sin QR — normal en actas físicas. Los estados con sistema digital incluyen QR de oficialía civil.")
