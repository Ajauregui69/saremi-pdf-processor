"""
Verificador de Avalúo (bancario o pericial)
Checks: layout, perito valuador, vigencia 6 meses, valor de mercado, superficie, dirección
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
_M2_RE = re.compile(r'([\d,]+\.?\d*)\s*m[²2]', re.I)
_RFC_RE = re.compile(r'\b([A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3})\b')

_MONTHS_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}

_TIPOS_AVALUO = [
    "avalúo comercial", "avalúo de mercado", "valor de mercado", "valor comercial",
    "avalúo fiscal", "dictamen valuatorio", "avalúo bancario", "avalúo pericial",
    "valor físico", "valor de reposición",
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


def _parse_amount(text: str) -> Optional[float]:
    matches = _AMOUNT_RE.findall(text)
    for m in matches:
        try:
            val = float(m.replace(",", ""))
            if val >= 100_000:
                return val
        except ValueError:
            continue
    return None


class AvaluoVerifier(BaseVerifier):
    """Verifica autenticidad de un Avalúo inmobiliario."""

    async def verify(self, file_path: str, extracted_data: Dict, preloaded_qr_codes: Optional[List] = None) -> List[CheckItem]:
        checks: List[CheckItem] = []
        raw_text: str = extracted_data.get("_raw_text", "")

        checks.append(self._check_layout(raw_text))
        checks.append(self._check_vigencia(raw_text))
        checks.append(self._check_perito(raw_text, extracted_data))
        checks.append(self._check_valor(raw_text, extracted_data))
        checks.append(self._check_superficie(raw_text))
        checks.append(self._check_direccion(raw_text))
        checks.append(self._check_tipo_avaluo(raw_text))
        checks.extend(await self._run_fraud_analysis(file_path, "avaluo", extracted_data, preloaded_qr_codes))

        return checks

    def _check_layout(self, text: str) -> CheckItem:
        t = text.lower()
        signals = [
            any(w in t for w in ["avalúo", "dictamen valuatorio", "valuación", "valuador"]),
            any(w in t for w in ["valor de mercado", "valor comercial", "valor físico", "valor de reposición"]),
            any(w in t for w in ["perito valuador", "valuador certificado", "colegio de valuadores"]),
            any(w in t for w in ["terreno", "construcción", "superficie habitable", "m²"]),
        ]
        score = sum(signals)
        if score >= 3:
            return self._passed("layout_avaluo", "Documento identificado como Avalúo Inmobiliario")
        if score >= 2:
            return self._warning("layout_avaluo", "Documento parcialmente identificado como avalúo")
        return self._warning("layout_avaluo", "No se confirmó que el documento sea un Avalúo")

    def _check_vigencia(self, raw_text: str) -> CheckItem:
        avaluo_date = _parse_date(raw_text)
        if not avaluo_date:
            return self._warning("vigencia_avaluo", "No se encontró fecha de elaboración del avalúo")
        today = date.today()
        days_old = (today - avaluo_date).days
        if days_old < 0:
            return self._warning("vigencia_avaluo", f"Fecha futura en el avalúo: {avaluo_date}")
        # Avalúos bancarios: vigencia típica 6 meses (180 días)
        if days_old <= 180:
            return self._passed("vigencia_avaluo", f"Avalúo vigente: elaborado el {avaluo_date} ({days_old} días de antigüedad, máx. 180 días)")
        if days_old <= 365:
            return self._warning(
                "vigencia_avaluo",
                f"Avalúo con {days_old} días — puede estar vencido. Los avalúos bancarios tienen vigencia de 6 meses.",
            )
        return self._failed(
            "vigencia_avaluo",
            f"Avalúo con {days_old} días de antigüedad — VENCIDO para efectos bancarios (máx. 180 días).",
        )

    def _check_perito(self, raw_text: str, extracted_data: Dict) -> CheckItem:
        t = raw_text.lower()
        has_perito = any(w in t for w in ["perito valuador", "valuador certificado", "c.p.v.", "valuador autorizado"])
        has_registro = bool(re.search(r'(?:registro|cédula|carnet|lic\.)\s*(?:de\s*valuador)?\s*(?:n[oú]m(?:ero)?\.?\s*)?(\d{4,10})', t, re.I))
        rfc = _RFC_RE.search(raw_text.upper())

        if has_perito and (has_registro or rfc):
            detail = f"Perito valuador identificado{', RFC: ' + rfc.group(1) if rfc else ''}"
            return self._passed("perito_avaluo", detail)
        if has_perito:
            return self._warning("perito_avaluo", "Perito valuador mencionado pero sin número de registro/RFC identificado")
        return self._warning("perito_avaluo", "Perito valuador no identificado claramente — verificar credenciales del valuador")

    def _check_valor(self, raw_text: str, extracted_data: Dict) -> CheckItem:
        valor = extracted_data.get("valor_mercado") or extracted_data.get("precio") or _parse_amount(raw_text)
        if valor and float(valor) >= 100_000:
            return self._passed("valor_avaluo", f"Valor de mercado presente: ${float(valor):,.2f} MXN")
        if valor:
            return self._warning("valor_avaluo", f"Valor detectado pero inusualmente bajo: ${float(valor):,.2f} — verificar")
        return self._warning("valor_avaluo", "Valor de mercado no encontrado en el avalúo")

    def _check_superficie(self, raw_text: str) -> CheckItem:
        m2_matches = _M2_RE.findall(raw_text)
        if m2_matches:
            surfaces = [m.replace(",", "") for m in m2_matches[:3]]
            return self._passed("superficie_avaluo", f"Superficie(s) reportada(s): {', '.join(surfaces)} m²")
        return self._warning("superficie_avaluo", "Superficie del inmueble no encontrada en el avalúo")

    def _check_direccion(self, raw_text: str) -> CheckItem:
        t = raw_text.lower()
        has_calle = any(w in t for w in ["calle", "avenida", "blvd", "calzada", "privada"])
        has_colonia = "colonia" in t or "fraccionamiento" in t or "col." in t
        has_cp = bool(re.search(r'\b\d{5}\b', raw_text))
        score = sum([has_calle, has_colonia, has_cp])
        if score >= 2:
            return self._passed("direccion_avaluo", "Dirección del inmueble presente en el avalúo")
        return self._warning("direccion_avaluo", "Dirección del inmueble incompleta en el avalúo")

    def _check_tipo_avaluo(self, raw_text: str) -> CheckItem:
        t = raw_text.lower()
        tipo = next((tp for tp in _TIPOS_AVALUO if tp in t), None)
        if tipo:
            return self._passed("tipo_avaluo", f"Tipo de avalúo identificado: {tipo.title()}")
        return self._warning("tipo_avaluo", "Tipo de avalúo no identificado explícitamente")
