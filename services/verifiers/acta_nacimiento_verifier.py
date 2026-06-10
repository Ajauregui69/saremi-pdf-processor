"""
Verificador de Acta de Nacimiento
Checks: QR RENAPO/SIDEA, CURP, folio triple (oficialía+libro+acta), fecha coherente, layout
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

SCRAPER_TIMEOUT = int(os.getenv("SCRAPER_TIMEOUT_SECONDS", "15"))

_CURP_RE = re.compile(r'\b([A-Z]{4}\d{6}[HM][A-Z]{5}[0-9A-Z]\d)\b')
_FOLIO_SIDEA_RE = re.compile(r'\b([A-Z]{2,4}\d{6,12})\b')
_DATE_RE = re.compile(r'\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\b')
_DATE_ES_RE = re.compile(r'\b(\d{1,2})\s+de\s+([a-záéíóúñ]+)\s+de\s+(\d{4})\b', re.I)

_MONTHS_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}


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


class ActaNacimientoVerifier(BaseVerifier):
    """Verifica autenticidad de un Acta de Nacimiento mexicana."""

    async def verify(self, file_path: str, extracted_data: Dict, preloaded_qr_codes: Optional[List] = None) -> List[CheckItem]:
        checks: List[CheckItem] = []
        raw_text: str = extracted_data.get("_raw_text", "")

        # 1. Layout de acta de nacimiento
        checks.append(self._check_layout(raw_text))

        # 2. CURP presente y formato válido
        curp = extracted_data.get("curp", "")
        checks.append(self._check_curp(curp, raw_text))

        # 3. Folio triple (oficialía / libro / acta)
        checks.append(self._check_folio_triple(raw_text))

        # 4. Fecha de registro coherente
        checks.append(self._check_fecha_registro(raw_text))

        # 5. Nombre del titular presente
        checks.append(self._check_nombre_titular(extracted_data, raw_text))

        # 6. Lugar de nacimiento (entidad) presente
        checks.append(self._check_lugar_nacimiento(raw_text))

        # 7. QR RENAPO/SIDEA (actas digitales post-2015)
        checks.append(await self._check_qr_renapo(raw_text, preloaded_qr_codes))

        # 8. Análisis de fraude visual
        checks.extend(await self._run_fraud_analysis(file_path, "acta_nacimiento", extracted_data, preloaded_qr_codes))

        return checks

    # ── checks internos ───────────────────────────────────────────────────────

    def _check_layout(self, text: str) -> CheckItem:
        t = text.lower()
        signals = [
            "acta de nacimiento" in t,
            "registro civil" in t or "registro de nacimiento" in t,
            "nació" in t or "nació el" in t or "nacimiento" in t,
            any(word in t for word in ["officialía", "oficialía", "juzgado", "juez"]),
        ]
        score = sum(signals)
        if score >= 3:
            return self._passed("layout_acta_nacimiento", "Documento identificado como Acta de Nacimiento")
        if score >= 2:
            return self._warning("layout_acta_nacimiento", "Documento parcialmente identificado como Acta de Nacimiento")
        return self._warning("layout_acta_nacimiento", "No se confirmó que el documento sea un Acta de Nacimiento")

    def _check_curp(self, curp: str, raw_text: str) -> CheckItem:
        candidate = curp
        if not candidate:
            m = _CURP_RE.search(raw_text.upper())
            candidate = m.group(1) if m else ""
        if not candidate:
            return self._warning("curp_acta", "CURP no encontrado en el acta — puede ser acta física antigua sin CURP")
        if len(candidate) != 18:
            return self._warning("curp_acta", f"CURP con longitud inesperada: {candidate!r}")
        return self._passed("curp_acta", f"CURP presente en el acta: {candidate}")

    def _check_folio_triple(self, text: str) -> CheckItem:
        t = text.lower()
        has_ofic = "oficialía" in t or "officialía" in t or "juzgado" in t
        has_libro = "libro" in t or "tomo" in t
        has_acta = "acta" in t and re.search(r'acta\s+(?:n[uú]m(?:ero)?|#|no\.?)?\s*\d+', t) is not None
        score = sum([has_ofic, has_libro, has_acta])
        if score == 3:
            return self._passed("folio_triple", "Triple identificador presente: oficialía, libro y número de acta")
        if score == 2:
            return self._warning("folio_triple", f"Identificador parcial del acta: {'oficialía' if has_ofic else ''} {'libro' if has_libro else ''} {'núm.acta' if has_acta else ''}".strip())
        return self._warning("folio_triple", "No se encontró el folio triple del acta (oficialía/libro/acta)")

    def _check_fecha_registro(self, text: str) -> CheckItem:
        birth_date = _parse_date(text)
        if not birth_date:
            return self._warning("fecha_nacimiento_acta", "No se encontró fecha de nacimiento en el acta")
        today = date.today()
        if birth_date > today:
            return self._failed("fecha_nacimiento_acta", f"Fecha de nacimiento en el futuro: {birth_date}")
        age_years = (today - birth_date).days / 365.25
        if age_years > 120:
            return self._warning("fecha_nacimiento_acta", f"Fecha de nacimiento inusualmente antigua: {birth_date} ({int(age_years)} años)")
        return self._passed("fecha_nacimiento_acta", f"Fecha de nacimiento coherente: {birth_date} ({int(age_years)} años)")

    def _check_nombre_titular(self, extracted_data: Dict, raw_text: str) -> CheckItem:
        name = extracted_data.get("full_name", "") or extracted_data.get("nombre", "")
        if name and len(name.strip()) >= 5:
            return self._passed("nombre_titular_acta", f"Nombre del titular presente: {name}")
        # Buscar patrón nombre en texto
        m = re.search(r'nombre[:\s]+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s]{4,40})', raw_text, re.I)
        if m:
            return self._passed("nombre_titular_acta", f"Nombre encontrado en texto: {m.group(1).strip()}")
        return self._warning("nombre_titular_acta", "No se encontró nombre del titular en el acta")

    def _check_lugar_nacimiento(self, text: str) -> CheckItem:
        t = text.lower()
        # Entidades federativas
        entidades = [
            "aguascalientes", "baja california", "campeche", "chiapas", "chihuahua",
            "ciudad de méxico", "coahuila", "colima", "durango", "guanajuato",
            "guerrero", "hidalgo", "jalisco", "estado de méxico", "michoacán",
            "morelos", "nayarit", "nuevo león", "oaxaca", "puebla", "querétaro",
            "quintana roo", "san luis potosí", "sinaloa", "sonora", "tabasco",
            "tamaulipas", "tlaxcala", "veracruz", "yucatán", "zacatecas",
        ]
        found = [e for e in entidades if e in t]
        if found:
            return self._passed("lugar_nacimiento", f"Entidad federativa identificada: {found[0].title()}")
        if "municipio" in t or "localidad" in t:
            return self._passed("lugar_nacimiento", "Datos de municipio/localidad presentes en el acta")
        return self._warning("lugar_nacimiento", "No se identificó lugar de nacimiento en el acta")

    async def _check_qr_renapo(self, raw_text: str, preloaded_qr_codes: Optional[List]) -> CheckItem:
        """Verifica QR del SIDEA/RENAPO en actas digitales."""
        if preloaded_qr_codes:
            for qr in preloaded_qr_codes:
                data = qr.get("data", "")
                if "renapo" in data.lower() or "curp.gob.mx" in data.lower() or "registrocivil" in data.lower():
                    return self._passed("qr_renapo_acta", f"QR RENAPO/SIDEA detectado: {data[:80]}")
                if data.startswith("http") and len(data) > 20:
                    return self._warning("qr_renapo_acta", f"QR presente pero no apunta a RENAPO — verificar: {data[:80]}")

        # Buscar señales de acta digital SIDEA en el texto
        t = raw_text.lower()
        if "sidea" in t or "acta en línea" in t or "acta digital" in t:
            return self._warning("qr_renapo_acta", "Acta digital SIDEA identificada pero QR no decodificado — verificar en portal RENAPO")
        if "cadena original" in t or "sello digital" in t or "firma electrónica" in t:
            return self._passed("qr_renapo_acta", "Acta con sello digital/cadena original — acta certificada digital")

        return self._skipped("qr_renapo_acta", "QR no encontrado — puede ser acta física. Si es digital SIDEA (post-2015), debe tener QR de RENAPO")
