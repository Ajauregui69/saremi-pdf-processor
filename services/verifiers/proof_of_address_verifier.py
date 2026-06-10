"""
Verificador de Comprobante de Domicilio
Checks: proveedor reconocido, frescura de fecha, completitud de dirección, titular presente
"""

import re
import logging
from datetime import date
from typing import Dict, List, Optional

from models.verification_schemas import CheckItem
from services.verifiers.base_verifier import BaseVerifier

logger = logging.getLogger(__name__)

KNOWN_PROVIDERS = {
    "CFE", "Telmex", "Telcel", "Izzi", "Totalplay", "Megacable",
    "Gas Natural", "Naturgy", "Gas LP", "Agua", "CONAGUA", "SACMEX",
    "Axtel", "AT&T", "Movistar", "Sky",
}

_DATE_RE = re.compile(r"\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\b")
_DATE_ES_RE = re.compile(r"\b(\d{1,2})\s+de\s+([a-záéíóúñ]+)\s+de\s+(\d{4})\b", re.IGNORECASE)
_CP_RE = re.compile(r"\b\d{5}\b")
_MONTHS_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}

_ADDRESS_KEYWORDS = ["calle", "av.", "avenida", "blvd", "boulevard", "colonia", "col.", "municipio", "estado", "c.p."]


def _parse_date(text: str) -> Optional[date]:
    for m in _DATE_RE.finditer(text):
        try:
            day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 1 <= month <= 12 and 1 <= day <= 31:
                return date(year, month, day)
        except ValueError:
            continue
    for m in _DATE_ES_RE.finditer(text):
        day, month_name, year = m.group(1), m.group(2), m.group(3)
        month = _MONTHS_ES.get(month_name.lower())
        if month:
            try:
                return date(int(year), month, int(day))
            except ValueError:
                continue
    return None


class ProofOfAddressVerifier(BaseVerifier):
    """Verifica autenticidad de un comprobante de domicilio."""

    async def verify(self, file_path: str, extracted_data: Dict) -> List[CheckItem]:
        checks: List[CheckItem] = []

        service_type: str = extracted_data.get("service_type", "")
        address: str = extracted_data.get("address", "")
        account_holder: str = extracted_data.get("account_holder", "")
        raw_text: str = extracted_data.get("_raw_text", "")

        # 1. Proveedor reconocido
        checks.append(self._check_provider(service_type, raw_text))

        # 2. Frescura de fecha (≤ 3 meses)
        checks.append(self._check_date_freshness(raw_text))

        # 3. Completitud de dirección
        checks.append(self._check_address_completeness(address, raw_text))

        # 4. Titular presente
        checks.append(self._check_titular(account_holder))

        # 5. Análisis de fraude visual + verificación de QR
        checks.extend(await self._run_fraud_analysis(file_path, "proof_of_address", extracted_data))

        return checks

    # ── checks internos ───────────────────────────────────────────────────────

    def _check_provider(self, service_type: str, raw_text: str) -> CheckItem:
        # Primero usar el dato extraído
        if service_type:
            for p in KNOWN_PROVIDERS:
                if p.lower() in service_type.lower():
                    return self._passed("proveedor_reconocido", f"Proveedor de servicio reconocido: {p}")

        # Si no hay service_type, buscar en el texto
        text_lower = raw_text.lower()
        for provider in KNOWN_PROVIDERS:
            if provider.lower() in text_lower:
                return self._passed("proveedor_reconocido", f"Proveedor reconocido en texto: {provider}")

        return self._warning("proveedor_reconocido", "No se identificó proveedor de servicio conocido (CFE, Telmex, etc.)")

    def _check_date_freshness(self, raw_text: str) -> CheckItem:
        if not raw_text:
            return self._skipped("frescura_fecha", "Texto del documento no disponible")
        doc_date = _parse_date(raw_text)
        if not doc_date:
            return self._warning("frescura_fecha", "No se encontró fecha de emisión en el comprobante")
        today = date.today()
        delta_days = (today - doc_date).days
        if delta_days < 0:
            return self._warning("frescura_fecha", f"Fecha futura en el documento: {doc_date}")
        if delta_days <= 92:
            return self._passed("frescura_fecha", f"Comprobante reciente: {doc_date} ({delta_days} días)")
        return self._failed(
            "frescura_fecha",
            f"Comprobante con más de 3 meses de antigüedad: {doc_date} ({delta_days} días)",
        )

    def _check_address_completeness(self, address: str, raw_text: str) -> CheckItem:
        search_text = (address + " " + raw_text).lower()
        found = [kw for kw in _ADDRESS_KEYWORDS if kw in search_text]
        has_cp = bool(_CP_RE.search(raw_text))

        if len(found) >= 3 and has_cp:
            return self._passed("completitud_direccion", f"Dirección completa: elementos encontrados ({', '.join(found[:4])}), CP presente")
        elif len(found) >= 2 or has_cp:
            return self._warning("completitud_direccion", f"Dirección parcial: {', '.join(found)} {'+ CP' if has_cp else ''}")
        return self._warning("completitud_direccion", "Dirección incompleta o no encontrada")

    def _check_titular(self, account_holder: str) -> CheckItem:
        if account_holder and len(account_holder.strip()) >= 3:
            return self._passed("titular_presente", f"Nombre del titular encontrado: {account_holder}")
        return self._warning("titular_presente", "No se encontró nombre del titular en el comprobante")
