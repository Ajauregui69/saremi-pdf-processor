"""
Verificador de Constancia de Situación Fiscal (CSF)
Checks: QR SAT, vigencia <90 días, RFC formato, CURP, estatus padrón activo
"""

import re
import logging
import os
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

import httpx

from models.verification_schemas import CheckItem
from services.verifiers.base_verifier import BaseVerifier

logger = logging.getLogger(__name__)

SCRAPER_TIMEOUT = int(os.getenv("SCRAPER_TIMEOUT_SECONDS", "15"))

_RFC_RE = re.compile(r'\b([A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3})\b')
_CURP_RE = re.compile(r'\b([A-Z]{4}\d{6}[HM][A-Z]{5}[0-9A-Z]\d)\b')
_DATE_RE = re.compile(r'\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\b')
_DATE_ES_RE = re.compile(r'\b(\d{1,2})\s+de\s+([a-záéíóúñ]+)\s+de\s+(\d{4})\b', re.I)
_CP_RE = re.compile(r'\b(\d{5})\b')

_MONTHS_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}

# Regímenes fiscales SAT válidos (muestra representativa)
_REGIMENES_SAT = {
    "601", "603", "605", "606", "607", "608", "609", "610", "611", "612",
    "614", "615", "616", "620", "621", "622", "623", "624", "625", "626",
}


def _parse_date(text: str) -> Optional[date]:
    for m in _DATE_RE.finditer(text):
        try:
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 1 <= mo <= 12 and 1 <= d <= 31:
                return date(y, mo, d)
        except ValueError:
            continue
    for m in _DATE_ES_RE.finditer(text):
        try:
            month_num = _MONTHS_ES.get(m.group(2).lower())
            if month_num:
                return date(int(m.group(3)), month_num, int(m.group(1)))
        except ValueError:
            continue
    return None


class CSFVerifier(BaseVerifier):
    """Verifica autenticidad de una Constancia de Situación Fiscal del SAT."""

    async def verify(self, file_path: str, extracted_data: Dict, preloaded_qr_codes: Optional[List] = None) -> List[CheckItem]:
        checks: List[CheckItem] = []
        raw_text: str = extracted_data.get("_raw_text", "")

        # 1. Identificar que es una CSF por su layout
        checks.append(self._check_csf_layout(raw_text))

        # 2. RFC formato y presencia
        rfc = extracted_data.get("rfc", "")
        checks.append(self._check_rfc_format(rfc, raw_text))

        # 3. CURP presente (personas físicas)
        curp = extracted_data.get("curp", "")
        checks.append(self._check_curp_present(curp, raw_text))

        # 4. Vigencia < 90 días (fecha de emisión)
        issue_date_str = extracted_data.get("issue_date", "")
        checks.append(self._check_vigencia(issue_date_str, raw_text))

        # 5. Estatus padrón activo
        checks.append(self._check_estatus_padron(raw_text))

        # 6. Régimen fiscal identificado
        checks.append(self._check_regimen_fiscal(raw_text))

        # 7. Domicilio fiscal con CP
        checks.append(self._check_domicilio_fiscal(raw_text))

        # 8. QR SAT (si disponible)
        checks.append(await self._check_qr_sat(raw_text, preloaded_qr_codes))

        # 9. Análisis de fraude visual
        checks.extend(await self._run_fraud_analysis(file_path, "csf", extracted_data, preloaded_qr_codes))

        return checks

    # ── checks internos ───────────────────────────────────────────────────────

    def _check_csf_layout(self, text: str) -> CheckItem:
        t = text.lower()
        signals = [
            "constancia de situación fiscal" in t,
            "servicio de administración tributaria" in t or "sat" in t,
            "régimen fiscal" in t or "regimen fiscal" in t,
            "rfc:" in t or "registro federal de contribuyentes" in t,
        ]
        score = sum(signals)
        if score >= 3:
            return self._passed("layout_csf", "Documento identificado como Constancia de Situación Fiscal del SAT")
        if score >= 2:
            return self._warning("layout_csf", "Documento parcialmente identificado como CSF — verificar manualmente")
        return self._failed("layout_csf", "El documento no parece ser una Constancia de Situación Fiscal del SAT")

    def _check_rfc_format(self, rfc: str, raw_text: str) -> CheckItem:
        # Buscar RFC en datos extraídos o en texto
        candidate = rfc
        if not candidate:
            m = _RFC_RE.search(raw_text.upper())
            candidate = m.group(1) if m else ""
        if not candidate:
            return self._failed("rfc_formato", "No se encontró RFC en la constancia")
        clean = candidate.strip().upper()
        if not _RFC_RE.match(clean):
            return self._warning("rfc_formato", f"RFC con formato no estándar: {clean!r}")
        persona_fisica = len(clean) == 13
        persona_moral = len(clean) == 12
        tipo = "Persona Física" if persona_fisica else ("Persona Moral" if persona_moral else "?")
        return self._passed("rfc_formato", f"RFC válido ({tipo}): {clean}")

    def _check_curp_present(self, curp: str, raw_text: str) -> CheckItem:
        candidate = curp
        if not candidate:
            m = _CURP_RE.search(raw_text.upper())
            candidate = m.group(1) if m else ""
        if not candidate:
            # Personas morales no tienen CURP — es aceptable
            t = raw_text.lower()
            if "persona moral" in t or "sociedad" in t or "s.a." in t or "s.r.l." in t:
                return self._skipped("curp_csf", "Persona moral — CURP no aplica")
            return self._warning("curp_csf", "No se encontró CURP en la constancia (esperado para persona física)")
        return self._passed("curp_csf", f"CURP presente en la constancia: {candidate}")

    def _check_vigencia(self, issue_date_str: str, raw_text: str) -> CheckItem:
        # Intentar parsear del dato extraído primero, luego del texto
        doc_date = None
        if issue_date_str:
            doc_date = _parse_date(issue_date_str)
        if not doc_date:
            doc_date = _parse_date(raw_text)
        if not doc_date:
            return self._warning("vigencia_csf", "No se encontró fecha de emisión en la constancia — verificar que sea del año en curso")
        today = date.today()
        delta = (today - doc_date).days
        if delta < 0:
            return self._warning("vigencia_csf", f"Fecha de emisión futura: {doc_date}")
        if delta <= 90:
            return self._passed("vigencia_csf", f"CSF vigente: emitida el {doc_date} ({delta} días de antigüedad, máx. 90)")
        return self._failed("vigencia_csf", f"CSF vencida: emitida el {doc_date} ({delta} días). La norma notarial exige CSF con menos de 3 meses de antigüedad.")

    def _check_estatus_padron(self, raw_text: str) -> CheckItem:
        t = raw_text.lower()
        if "activo" in t:
            return self._passed("estatus_padron", "Estatus de padrón: ACTIVO")
        if "suspendido" in t or "cancelado" in t or "no localizado" in t:
            return self._failed("estatus_padron", "Estatus de padrón NO activo (suspendido, cancelado o no localizado)")
        return self._warning("estatus_padron", "No se pudo determinar el estatus de padrón — verificar en el portal SAT")

    def _check_regimen_fiscal(self, raw_text: str) -> CheckItem:
        t = raw_text.lower()
        if "régimen" in t or "regimen" in t:
            # Buscar código de 3 dígitos cerca de "régimen"
            m = re.search(r'r[eé]gimen[^0-9]{0,30}(\d{3})', t)
            if m and m.group(1) in _REGIMENES_SAT:
                return self._passed("regimen_fiscal", f"Régimen fiscal con código SAT válido: {m.group(1)}")
            return self._passed("regimen_fiscal", "Régimen fiscal identificado en el documento")
        return self._warning("regimen_fiscal", "No se identificó régimen fiscal en el documento")

    def _check_domicilio_fiscal(self, raw_text: str) -> CheckItem:
        t = raw_text.lower()
        has_cp = bool(_CP_RE.search(raw_text))
        has_address = any(kw in t for kw in ["calle", "avenida", "colonia", "municipio", "c.p."])
        if has_address and has_cp:
            return self._passed("domicilio_fiscal", "Domicilio fiscal con calle y código postal presentes")
        if has_address or has_cp:
            return self._warning("domicilio_fiscal", "Domicilio fiscal incompleto — faltan elementos (calle o CP)")
        return self._warning("domicilio_fiscal", "No se encontró domicilio fiscal en el documento")

    async def _check_qr_sat(self, raw_text: str, preloaded_qr_codes: Optional[List]) -> CheckItem:
        """Verifica presencia y validez del QR del SAT en la CSF."""
        # Revisar QR pre-escaneados
        sat_url = None
        if preloaded_qr_codes:
            for qr in preloaded_qr_codes:
                data = qr.get("data", "")
                if "sat.gob.mx" in data.lower() or "rfc=" in data.lower():
                    sat_url = data
                    break

        if sat_url:
            return self._passed("qr_sat_csf", f"QR SAT detectado y apunta a portal oficial: {sat_url[:80]}")

        # Buscar URL SAT en texto (a veces el QR no se decodifica pero la URL está en el texto)
        url_m = re.search(r'https?://[^\s]+sat\.gob\.mx[^\s]*', raw_text, re.I)
        if url_m:
            return self._passed("qr_sat_csf", f"URL del SAT encontrada en el documento: {url_m.group(0)[:80]}")

        # Presencia de QR mencionada en texto
        if "código qr" in raw_text.lower() or "qr" in raw_text.lower():
            return self._warning("qr_sat_csf", "Se menciona QR en el documento pero no se pudo decodificar — verificar manualmente en el portal SAT")

        return self._warning("qr_sat_csf", "No se encontró QR del SAT — todas las CSFs auténticas contienen QR de verificación")
