"""
Verificador de Acta de Defunción
Checks: layout, CURP del fallecido, fecha de defunción coherente, folio triple, lugar, causa
"""

import re
import logging
from datetime import date
from typing import Dict, List, Optional

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


def _parse_date(text: str) -> Optional[date]:
    for m in _DATE_ES_RE.finditer(text):
        try:
            month_num = _MONTHS_ES.get(m.group(2).lower())
            if month_num:
                y = int(m.group(3))
                if 1900 <= y <= date.today().year:
                    return date(y, month_num, int(m.group(1)))
        except ValueError:
            continue
    for m in _DATE_RE.finditer(text):
        try:
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 1 <= mo <= 12 and 1 <= d <= 31 and 1900 <= y <= date.today().year:
                return date(y, mo, d)
        except ValueError:
            continue
    return None


class ActaDefuncionVerifier(BaseVerifier):
    """Verifica autenticidad de un Acta de Defunción mexicana."""

    async def verify(self, file_path: str, extracted_data: Dict, preloaded_qr_codes: Optional[List] = None) -> List[CheckItem]:
        checks: List[CheckItem] = []
        raw_text: str = extracted_data.get("_raw_text", "")

        checks.append(self._check_layout(raw_text))
        checks.append(self._check_curp(extracted_data, raw_text))
        checks.append(self._check_nombre_fallecido(extracted_data, raw_text))
        checks.append(self._check_fecha_defuncion(raw_text))
        checks.append(self._check_folio_triple(raw_text))
        checks.append(self._check_lugar(raw_text))
        checks.append(self._check_causa(raw_text))
        checks.extend(await self._run_fraud_analysis(file_path, "acta_defuncion", extracted_data, preloaded_qr_codes))

        return checks

    def _check_layout(self, text: str) -> CheckItem:
        t = text.lower()
        signals = [
            "acta de defunción" in t or "acta de fallecimiento" in t,
            "registro civil" in t,
            any(w in t for w in ["falleció", "fallecimiento", "muerte", "defunción"]),
            any(w in t for w in ["juez", "oficialía", "juzgado del registro"]),
        ]
        score = sum(signals)
        if score >= 3:
            return self._passed("layout_acta_defuncion", "Documento identificado como Acta de Defunción")
        if score >= 2:
            return self._warning("layout_acta_defuncion", "Documento parcialmente identificado como Acta de Defunción")
        return self._warning("layout_acta_defuncion", "No se confirmó que el documento sea un Acta de Defunción")

    def _check_curp(self, extracted_data: Dict, raw_text: str) -> CheckItem:
        curp = extracted_data.get("curp", "")
        if not curp:
            m = _CURP_RE.search(raw_text.upper())
            curp = m.group(1) if m else ""
        if curp:
            return self._passed("curp_acta_defuncion", f"CURP del fallecido presente: {curp}")
        return self._warning("curp_acta_defuncion", "CURP no encontrado — puede ser acta antigua sin CURP registrado")

    def _check_nombre_fallecido(self, extracted_data: Dict, raw_text: str) -> CheckItem:
        name = extracted_data.get("full_name", "") or extracted_data.get("nombre_fallecido", "")
        if name and len(name.strip()) >= 4:
            return self._passed("nombre_fallecido", f"Nombre del fallecido presente: {name}")
        m = re.search(r'(?:nombre|fallecido|difunto)[:\s]+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s]{4,50})', raw_text, re.I)
        if m:
            return self._passed("nombre_fallecido", f"Nombre encontrado: {m.group(1).strip()}")
        return self._warning("nombre_fallecido", "No se encontró nombre del fallecido")

    def _check_fecha_defuncion(self, raw_text: str) -> CheckItem:
        death_date = _parse_date(raw_text)
        if not death_date:
            return self._warning("fecha_defuncion", "No se encontró fecha de defunción en el acta")
        today = date.today()
        if death_date > today:
            return self._failed("fecha_defuncion", f"Fecha de defunción en el futuro: {death_date} — imposible")
        age_at_death = (today - death_date).days / 365.25
        if age_at_death > 120:
            return self._warning("fecha_defuncion", f"Fecha de defunción muy antigua: {death_date}")
        return self._passed("fecha_defuncion", f"Fecha de defunción coherente: {death_date}")

    def _check_folio_triple(self, raw_text: str) -> CheckItem:
        t = raw_text.lower()
        has_ofic = "oficialía" in t or "juzgado" in t
        has_libro = "libro" in t or "tomo" in t
        has_acta = bool(re.search(r'acta\s+(?:n[uú]m(?:ero)?|#|no\.?)?\s*\d+', t))
        score = sum([has_ofic, has_libro, has_acta])
        if score == 3:
            return self._passed("folio_triple_defuncion", "Triple identificador: oficialía, libro y número de acta presentes")
        if score >= 2:
            return self._warning("folio_triple_defuncion", "Identificador parcial del acta de defunción")
        return self._warning("folio_triple_defuncion", "Folio triple del acta no identificado completamente")

    def _check_lugar(self, raw_text: str) -> CheckItem:
        t = raw_text.lower()
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
            return self._passed("lugar_defuncion", f"Lugar de defunción identificado: {found[0].title()}")
        if "municipio" in t or "hospital" in t or "domicilio" in t:
            return self._passed("lugar_defuncion", "Datos de lugar de defunción presentes")
        return self._warning("lugar_defuncion", "Lugar de defunción no identificado claramente")

    def _check_causa(self, raw_text: str) -> CheckItem:
        t = raw_text.lower()
        has_causa = any(w in t for w in ["causa de muerte", "causa directa", "diagnóstico", "enfermedad", "traumatismo"])
        if has_causa:
            return self._passed("causa_defuncion", "Causa de muerte presente en el acta")
        return self._warning("causa_defuncion", "Causa de muerte no identificada — puede omitirse en actas certificadas")
