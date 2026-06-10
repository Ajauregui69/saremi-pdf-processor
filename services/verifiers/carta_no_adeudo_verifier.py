"""
Verificador de Carta de No Adeudo
Checks: layout, emisor (administración/condominio/banco), inmueble, periodo cubierto, vigencia, sello/firma
"""

import re
import logging
from datetime import date
from typing import Dict, List, Optional

from models.verification_schemas import CheckItem
from services.verifiers.base_verifier import BaseVerifier

logger = logging.getLogger(__name__)

_DATE_RE = re.compile(r'\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\b')
_DATE_ES_RE = re.compile(r'\b(\d{1,2})\s+de\s+([a-záéíóúñ]+)\s+de\s+(\d{4})\b', re.I)
_AMOUNT_RE = re.compile(r'\$?\s*([\d,]+\.?\d{0,2})')

_MONTHS_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}

_TIPOS_EMISOR = [
    # Condominio
    "administración del condominio", "administrador del condominio", "condominio",
    "comité de administración", "junta de condominos",
    # Banco / hipoteca
    "bbva", "santander", "banamex", "banorte", "hsbc", "scotiabank", "inbursa",
    "infonavit", "fovissste",
    # Servicios
    "cfe", "comisión federal de electricidad",
    "sacmex", "sistema de agua", "organismo operador",
    # Gobierno
    "tesorería", "hacienda municipal", "gobierno municipal",
]


def _parse_date(text: str) -> Optional[date]:
    for m in _DATE_ES_RE.finditer(text):
        try:
            month_num = _MONTHS_ES.get(m.group(2).lower())
            if month_num:
                y = int(m.group(3))
                if 2000 <= y <= date.today().year + 1:
                    return date(y, month_num, int(m.group(1)))
        except ValueError:
            continue
    for m in _DATE_RE.finditer(text):
        try:
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 1 <= mo <= 12 and 1 <= d <= 31 and 2000 <= y <= date.today().year + 1:
                return date(y, mo, d)
        except ValueError:
            continue
    return None


class CartaNoAdeudoVerifier(BaseVerifier):
    """Verifica autenticidad de una Carta de No Adeudo (condominio, banco, servicios)."""

    async def verify(self, file_path: str, extracted_data: Dict, preloaded_qr_codes: Optional[List] = None) -> List[CheckItem]:
        checks: List[CheckItem] = []
        raw_text: str = extracted_data.get("_raw_text", "")

        checks.append(self._check_layout(raw_text))
        checks.append(self._check_emisor(raw_text))
        checks.append(self._check_declaracion_no_adeudo(raw_text))
        checks.append(self._check_titular(extracted_data, raw_text))
        checks.append(self._check_inmueble_o_cuenta(raw_text))
        checks.append(self._check_vigencia(raw_text))
        checks.append(self._check_sello_firma(raw_text))
        checks.extend(await self._run_fraud_analysis(file_path, "carta_no_adeudo", extracted_data, preloaded_qr_codes))

        return checks

    def _check_layout(self, text: str) -> CheckItem:
        t = text.lower()
        signals = [
            any(w in t for w in ["carta de no adeudo", "constancia de no adeudo", "certificado de no adeudo", "no adeudo"]),
            any(w in t for w in ["condominio", "administración", "banco", "infonavit", "organismo"]),
            any(w in t for w in ["al corriente", "sin adeudo", "libre de adeudo", "no registra adeudo"]),
            any(w in t for w in ["a quien corresponda", "por medio de la presente", "se hace constar"]),
        ]
        score = sum(signals)
        if score >= 3:
            return self._passed("layout_carta_no_adeudo", "Documento identificado como Carta de No Adeudo")
        if score >= 2:
            return self._warning("layout_carta_no_adeudo", "Documento parcialmente identificado como carta de no adeudo")
        return self._warning("layout_carta_no_adeudo", "No se confirmó que el documento sea una Carta de No Adeudo")

    def _check_emisor(self, raw_text: str) -> CheckItem:
        t = raw_text.lower()
        found = next((e for e in _TIPOS_EMISOR if e in t), None)
        if found:
            return self._passed("emisor_carta_no_adeudo", f"Emisor identificado: {found.title()}")
        if any(w in t for w in ["a.c.", "s.c.", "s.a.", "administra"]):
            return self._warning("emisor_carta_no_adeudo", "Posible entidad emisora pero no identificada claramente")
        return self._warning("emisor_carta_no_adeudo", "Emisor de la carta no identificado — verificar quién emite la constancia")

    def _check_declaracion_no_adeudo(self, raw_text: str) -> CheckItem:
        t = raw_text.lower()
        positive = [
            "no registra adeudo", "sin adeudo", "al corriente", "libre de adeudo",
            "no tiene adeudo", "pagadas en su totalidad", "solvente", "sin deuda",
        ]
        negative = [
            "con adeudo", "adeudo pendiente", "deuda", "mora", "en atraso",
        ]
        if any(p in t for p in positive):
            return self._passed("declaracion_no_adeudo", "Declaración explícita de NO ADEUDO presente en el documento")
        if any(n in t for n in negative):
            return self._failed("declaracion_no_adeudo", "ADEUDO DETECTADO en el documento — el titular tiene deudas pendientes")
        return self._warning("declaracion_no_adeudo", "No se pudo confirmar la declaración de no adeudo — verificar el texto manualmente")

    def _check_titular(self, extracted_data: Dict, raw_text: str) -> CheckItem:
        name = extracted_data.get("full_name", "") or extracted_data.get("titular", "")
        if name and len(name.strip()) >= 4:
            return self._passed("titular_carta_no_adeudo", f"Titular presente: {name}")
        m = re.search(r'(?:nombre|titular|propietario|c\.|sr\.|sra\.)[:\s]+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s]{4,60})', raw_text, re.I)
        if m:
            return self._passed("titular_carta_no_adeudo", f"Titular encontrado: {m.group(1).strip()}")
        return self._warning("titular_carta_no_adeudo", "Nombre del titular no identificado en la carta")

    def _check_inmueble_o_cuenta(self, raw_text: str) -> CheckItem:
        t = raw_text.lower()
        has_inmueble = any(w in t for w in ["departamento", "casa", "unidad", "lote", "inmueble", "número interior", "número exterior"])
        has_cuenta = bool(re.search(r'(?:cuenta|crédito|préstamo)[:\s]*[\dA-Z\-]{6,20}', raw_text, re.I))
        has_address = any(w in t for w in ["calle", "avenida", "colonia", "fraccionamiento"])
        if has_inmueble or has_cuenta or has_address:
            return self._passed("inmueble_cuenta_carta", "Identificación del inmueble/cuenta presente en la carta")
        return self._warning("inmueble_cuenta_carta", "No se identificó el inmueble o cuenta al que aplica el no adeudo")

    def _check_vigencia(self, raw_text: str) -> CheckItem:
        carta_date = _parse_date(raw_text)
        if not carta_date:
            return self._warning("vigencia_carta_no_adeudo", "No se encontró fecha de emisión de la carta")
        today = date.today()
        days_old = (today - carta_date).days
        if days_old < 0:
            return self._warning("vigencia_carta_no_adeudo", f"Fecha futura en la carta: {carta_date}")
        # Las cartas de no adeudo típicamente tienen vigencia de 30-90 días
        if days_old <= 30:
            return self._passed("vigencia_carta_no_adeudo", f"Carta reciente: emitida el {carta_date} ({days_old} días de antigüedad)")
        if days_old <= 90:
            return self._warning(
                "vigencia_carta_no_adeudo",
                f"Carta con {days_old} días — puede estar vencida. Las notarías suelen exigir carta de no adeudo de máx. 30 días.",
            )
        return self._failed(
            "vigencia_carta_no_adeudo",
            f"Carta con {days_old} días de antigüedad — probablemente VENCIDA para efectos notariales.",
        )

    def _check_sello_firma(self, raw_text: str) -> CheckItem:
        t = raw_text.lower()
        has_firma = "firma" in t or "rúbrica" in t or "atentamente" in t
        has_sello = "sello" in t
        has_digital = "firma digital" in t or "sello digital" in t or "cadena original" in t
        if has_digital:
            return self._passed("sello_firma_carta_no_adeudo", "Sello/firma digital presente — documento certificado electrónicamente")
        if has_firma and has_sello:
            return self._passed("sello_firma_carta_no_adeudo", "Firma y sello del emisor presentes en la carta")
        if has_firma:
            return self._warning("sello_firma_carta_no_adeudo", "Firma presente pero sello no identificado")
        return self._warning("sello_firma_carta_no_adeudo", "Firma y sello del emisor no identificados — verificar documento original")
