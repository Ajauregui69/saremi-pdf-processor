"""
Verificador de Escritura Pública
Checks: número escritura, notario público, folio real, tipo acto, partes, inmueble, precio
"""

import re
import logging
from datetime import date
from typing import Dict, List, Optional

from models.verification_schemas import CheckItem
from services.verifiers.base_verifier import BaseVerifier

logger = logging.getLogger(__name__)

_CURP_RE = re.compile(r'\b([A-Z]{4}\d{6}[HM][A-Z]{5}[0-9A-Z]\d)\b')
_RFC_RE = re.compile(r'\b([A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3})\b')
_DATE_RE = re.compile(r'\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\b')
_DATE_ES_RE = re.compile(r'\b(\d{1,2})\s+de\s+([a-záéíóúñ]+)\s+de\s+(\d{4})\b', re.I)
_M2_RE = re.compile(r'([\d,]+\.?\d*)\s*m[²2]', re.I)
_AMOUNT_RE = re.compile(r'\$?\s*([\d,]+\.?\d{0,2})')
_FOLIO_REAL_RE = re.compile(r'(?:folio|folio\s+real|fol\.?|folio\s+electr[oó]nico)[:\s]+([A-Z0-9\-/]{4,20})', re.I)
_ESCRITURA_NUM_RE = re.compile(r'(?:escritura|instrumento|n[uú]mero\s+de\s+escritura)[:\s#]*(\d+)', re.I)
_NOTARIO_NUM_RE = re.compile(r'(?:notario|notaria|notar[ií]a)[:\s]*(?:p[uú]blico|p[uú]blica)?[:\s]*(?:n[uú]mero|no\.?|#)?[:\s]*(\d+)', re.I)

_MONTHS_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}

_TIPOS_ACTO = [
    "compraventa", "donación", "herencia", "testamento", "hipoteca", "poder notarial",
    "constitución de sociedad", "cancelación de hipoteca", "dación en pago",
    "permuta", "arrendamiento", "fideicomiso", "aportación",
]


def _parse_date(text: str) -> Optional[date]:
    for m in _DATE_ES_RE.finditer(text):
        try:
            month_num = _MONTHS_ES.get(m.group(2).lower())
            if month_num:
                y = int(m.group(3))
                if 1900 <= y <= date.today().year + 1:
                    return date(y, month_num, int(m.group(1)))
        except ValueError:
            continue
    for m in _DATE_RE.finditer(text):
        try:
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 1 <= mo <= 12 and 1 <= d <= 31 and 1900 <= y <= date.today().year + 1:
                return date(y, mo, d)
        except ValueError:
            continue
    return None


class EscrituraVerifier(BaseVerifier):
    """Verifica autenticidad de una Escritura Pública mexicana."""

    async def verify(self, file_path: str, extracted_data: Dict, preloaded_qr_codes: Optional[List] = None) -> List[CheckItem]:
        checks: List[CheckItem] = []
        raw_text: str = extracted_data.get("_raw_text", "")

        # 1. Layout escritura pública
        checks.append(self._check_layout(raw_text))

        # 2. Número de escritura / instrumento
        num_escritura = extracted_data.get("numero_escritura", "")
        checks.append(self._check_numero_escritura(num_escritura, raw_text))

        # 3. Notario público identificado y con número
        checks.append(self._check_notario(raw_text, extracted_data))

        # 4. Tipo de acto notarial
        tipo_acto = extracted_data.get("tipo_acto", "")
        checks.append(self._check_tipo_acto(tipo_acto, raw_text))

        # 5. Folio Real (RPP)
        folio_real = extracted_data.get("folio_real", "")
        checks.append(self._check_folio_real(folio_real, raw_text))

        # 6. Datos del inmueble (dirección, superficies)
        checks.append(self._check_datos_inmueble(raw_text))

        # 7. Partes: vendedor y comprador con CURP/RFC
        checks.extend(self._check_partes(raw_text, extracted_data))

        # 8. Precio declarado
        precio = extracted_data.get("precio")
        checks.append(self._check_precio(precio, raw_text))

        # 9. Fecha de escritura
        fecha_str = extracted_data.get("fecha_escritura", "")
        checks.append(self._check_fecha(fecha_str, raw_text))

        # 10. Antecedentes / cadena de propiedad (presencia)
        checks.append(self._check_antecedentes(raw_text))

        # 11. Análisis de fraude visual
        checks.extend(await self._run_fraud_analysis(file_path, "escritura", extracted_data, preloaded_qr_codes))

        return checks

    # ── checks internos ───────────────────────────────────────────────────────

    def _check_layout(self, text: str) -> CheckItem:
        t = text.lower()
        signals = [
            any(w in t for w in ["escritura pública", "instrumento notarial", "escritura número"]),
            any(w in t for w in ["notario público", "notaria pública", "fe pública"]),
            any(w in t for w in ["registro público de la propiedad", "rpp", "folio real"]),
            any(w in t for w in ["comparecen", "comparece", "el vendedor", "enajenante"]),
        ]
        score = sum(signals)
        if score >= 3:
            return self._passed("layout_escritura", "Documento identificado como Escritura Pública")
        if score >= 2:
            return self._warning("layout_escritura", "Documento parcialmente identificado como escritura pública")
        return self._warning("layout_escritura", "No se confirmó que el documento sea una Escritura Pública")

    def _check_numero_escritura(self, num: str, raw_text: str) -> CheckItem:
        candidate = num
        if not candidate:
            m = _ESCRITURA_NUM_RE.search(raw_text)
            candidate = m.group(1) if m else ""
        if not candidate:
            return self._warning("numero_escritura", "Número de escritura no encontrado — campo de trazabilidad importante")
        return self._passed("numero_escritura", f"Número de escritura/instrumento: {candidate}")

    def _check_notario(self, raw_text: str, extracted_data: Dict) -> CheckItem:
        notario_nombre = extracted_data.get("notario_nombre", "")
        notario_num = extracted_data.get("notario_numero", "")
        t = raw_text

        if not notario_num:
            m = _NOTARIO_NUM_RE.search(t)
            notario_num = m.group(1) if m else ""

        if notario_nombre and notario_num:
            return self._passed("notario_escritura", f"Notario Público No. {notario_num}: {notario_nombre}")
        if notario_num:
            return self._passed("notario_escritura", f"Notario Público No. {notario_num} identificado")
        if notario_nombre:
            return self._passed("notario_escritura", f"Notario identificado: {notario_nombre}")

        # Buscar por nombre en texto
        m = re.search(r'(?:lic\.|licenciado|doctor|dra\.|dr\.)?\s*([A-ZÁÉÍÓÚÑ][a-záéíóúñ\s]{8,40})\s*(?:notario|notaria)', raw_text, re.I)
        if m:
            return self._passed("notario_escritura", f"Notario identificado: {m.group(1).strip()}")

        return self._warning("notario_escritura", "No se identificó al Notario Público — verificar número y nombre del notario")

    def _check_tipo_acto(self, tipo_acto: str, raw_text: str) -> CheckItem:
        candidate = tipo_acto.lower() if tipo_acto else ""
        if not candidate:
            t = raw_text.lower()
            for tipo in _TIPOS_ACTO:
                if tipo in t:
                    candidate = tipo
                    break
        if candidate:
            return self._passed("tipo_acto_notarial", f"Tipo de acto notarial identificado: {candidate.title()}")
        return self._warning("tipo_acto_notarial", "No se identificó el tipo de acto notarial (compraventa, donación, etc.)")

    def _check_folio_real(self, folio: str, raw_text: str) -> CheckItem:
        candidate = folio
        if not candidate:
            m = _FOLIO_REAL_RE.search(raw_text)
            candidate = m.group(1).strip() if m else ""
        if candidate:
            return self._passed("folio_real_rpp", f"Folio Real (RPP) presente: {candidate}")
        t = raw_text.lower()
        if "registro público" in t or "rpp" in t:
            return self._warning("folio_real_rpp", "Se menciona RPP pero no se extrajo el Folio Real — verificar en RPP estatal")
        return self._warning("folio_real_rpp", "Folio Real (RPP) no encontrado — necesario para verificar cadena de propiedad")

    def _check_datos_inmueble(self, raw_text: str) -> CheckItem:
        t = raw_text.lower()
        has_address = any(w in t for w in ["calle", "avenida", "av.", "blvd"])
        has_surface = bool(_M2_RE.search(raw_text))
        has_colonia = "colonia" in t or "col." in t
        score = sum([has_address, has_surface, has_colonia])
        if score >= 2:
            m2 = _M2_RE.search(raw_text)
            detail = f"Dirección y {'superficie ' + m2.group(1) + ' m²' if m2 else 'colonia'} presentes"
            return self._passed("datos_inmueble_escritura", detail)
        return self._warning("datos_inmueble_escritura", "Datos del inmueble incompletos en la escritura")

    def _check_partes(self, raw_text: str, extracted_data: Dict) -> List[CheckItem]:
        checks = []
        t = raw_text.upper()

        # Vendedor
        vendedor_curp = extracted_data.get("vendedor_curp", "")
        if not vendedor_curp:
            curps = _CURP_RE.findall(t)
            vendedor_curp = curps[0] if curps else ""
        vendedor_nombre = extracted_data.get("vendedor_nombre", "")

        if vendedor_nombre or vendedor_curp:
            checks.append(self._passed(
                "vendedor_escritura",
                f"Vendedor/enajenante identificado: {vendedor_nombre or ''} {('CURP: ' + vendedor_curp) if vendedor_curp else ''}".strip()
            ))
        else:
            has_enajenante = any(w in raw_text.lower() for w in ["vendedor", "enajenante", "transmitente"])
            if has_enajenante:
                checks.append(self._warning("vendedor_escritura", "Vendedor/enajenante mencionado pero nombre/CURP no extraídos"))
            else:
                checks.append(self._warning("vendedor_escritura", "Vendedor/enajenante no identificado en la escritura"))

        # Comprador
        comprador_curp = extracted_data.get("comprador_curp", "")
        if not comprador_curp:
            curps = _CURP_RE.findall(t)
            comprador_curp = curps[1] if len(curps) >= 2 else ""
        comprador_nombre = extracted_data.get("comprador_nombre", "")

        if comprador_nombre or comprador_curp:
            checks.append(self._passed(
                "comprador_escritura",
                f"Comprador/adquirente identificado: {comprador_nombre or ''} {('CURP: ' + comprador_curp) if comprador_curp else ''}".strip()
            ))
        else:
            has_adquirente = any(w in raw_text.lower() for w in ["comprador", "adquirente", "adquiriente"])
            if has_adquirente:
                checks.append(self._warning("comprador_escritura", "Comprador/adquirente mencionado pero nombre/CURP no extraídos"))
            else:
                checks.append(self._warning("comprador_escritura", "Comprador/adquirente no identificado en la escritura"))

        return checks

    def _check_precio(self, precio: Optional[float], raw_text: str) -> CheckItem:
        amount = precio
        if not amount:
            matches = _AMOUNT_RE.findall(raw_text)
            for m in matches:
                try:
                    val = float(m.replace(",", ""))
                    if val >= 100_000:
                        amount = val
                        break
                except ValueError:
                    continue
        if amount:
            return self._passed("precio_escritura", f"Precio declarado: ${amount:,.2f} MXN")
        return self._warning("precio_escritura", "No se encontró precio de la operación en la escritura")

    def _check_fecha(self, fecha_str: str, raw_text: str) -> CheckItem:
        doc_date = _parse_date(fecha_str) if fecha_str else None
        if not doc_date:
            doc_date = _parse_date(raw_text)
        if not doc_date:
            return self._warning("fecha_escritura", "No se encontró fecha de la escritura")
        today = date.today()
        if doc_date > today:
            return self._warning("fecha_escritura", f"Fecha futura en la escritura: {doc_date}")
        return self._passed("fecha_escritura", f"Fecha de escritura: {doc_date}")

    def _check_antecedentes(self, raw_text: str) -> CheckItem:
        t = raw_text.lower()
        has_antecedentes = any(w in t for w in [
            "antecedentes", "escritura previa", "escritura anterior",
            "adquirió", "fue adquirido", "cadena de propiedad", "folio anterior",
        ])
        if has_antecedentes:
            return self._passed("antecedentes_escritura", "Antecedentes de propiedad presentes en la escritura — cadena de propiedad verificable")
        return self._warning("antecedentes_escritura", "No se encontraron antecedentes de propiedad — verificar cadena de transmisión en RPP")
