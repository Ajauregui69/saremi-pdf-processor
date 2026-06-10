"""
Verificador de Estado de Cuenta Bancario
Checks: banco reconocido, QR válido, frescura de fecha, RFC, consistencia de saldo
"""

import re
import logging
from datetime import date, datetime
from typing import Dict, List, Optional

from models.verification_schemas import CheckItem
from services.verifiers.base_verifier import BaseVerifier

logger = logging.getLogger(__name__)

KNOWN_BANKS = {
    "BBVA", "Santander", "Banamex", "Citibanamex", "Banorte", "HSBC",
    "Scotiabank", "Inbursa", "Azteca", "BanBajío", "Afirme", "Mifel",
    "Multiva", "Bansí", "Intercam", "Ve por Más", "CoDi", "Nu", "Hey Banco",
}

_RFC_RE = re.compile(r"\b[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}\b")
_DATE_PATTERNS = [
    re.compile(r"\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\b"),
    re.compile(r"\b(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})\b"),
    re.compile(r"\b(\d{1,2})\s+de\s+([a-záéíóúñ]+)\s+de\s+(\d{4})\b", re.IGNORECASE),
]
_MONTHS_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}


def _parse_date_from_text(text: str) -> Optional[date]:
    """Intenta extraer la primera fecha encontrada en el texto."""
    for pattern in _DATE_PATTERNS[:2]:
        for m in pattern.finditer(text):
            try:
                g = m.groups()
                if len(g[0]) == 4:  # yyyy-mm-dd
                    return date(int(g[0]), int(g[1]), int(g[2]))
                else:  # dd-mm-yyyy
                    return date(int(g[2]), int(g[1]), int(g[0]))
            except ValueError:
                continue
    # Formato "15 de marzo de 2024"
    for m in _DATE_PATTERNS[2].finditer(text):
        day, month_name, year = m.groups()
        month = _MONTHS_ES.get(month_name.lower())
        if month:
            try:
                return date(int(year), month, int(day))
            except ValueError:
                continue
    return None


class BankStatementVerifier(BaseVerifier):
    """Verifica autenticidad de un estado de cuenta bancario."""

    def __init__(self, qr_codes: Optional[List[Dict]] = None):
        self._qr_codes = qr_codes or []

    async def verify(self, file_path: str, extracted_data: Dict) -> List[CheckItem]:
        checks: List[CheckItem] = []

        bank_name: str = extracted_data.get("bank_name", "")
        raw_text: str = extracted_data.get("_raw_text", "")

        # 1. Banco reconocido
        checks.append(self._check_bank_name(bank_name))

        # 2. Frescura de fecha (≤ 3 meses)
        checks.append(self._check_date_freshness(raw_text))

        # 3. RFC formato
        checks.append(self._check_rfc(raw_text))

        # 4. Consistencia saldo (si hay datos)
        checks.append(self._check_balance_consistency(extracted_data))

        # 5. Análisis de fraude visual + verificación de QR bancario
        checks.extend(await self._run_fraud_analysis(file_path, "bank_statement", extracted_data, self._qr_codes))

        return checks

    # ── checks internos ───────────────────────────────────────────────────────

    def _check_bank_name(self, bank_name: str) -> CheckItem:
        if not bank_name:
            return self._warning("banco_reconocido", "No se identificó el nombre del banco en el documento")
        for known in KNOWN_BANKS:
            if known.lower() in bank_name.lower():
                return self._passed("banco_reconocido", f"Banco reconocido: {bank_name}")
        return self._warning("banco_reconocido", f"Banco no en lista de instituciones conocidas: {bank_name!r}")

    def _check_date_freshness(self, text: str) -> CheckItem:
        if not text:
            return self._skipped("frescura_fecha", "Texto del documento no disponible para verificar fecha")
        doc_date = _parse_date_from_text(text)
        if not doc_date:
            return self._warning("frescura_fecha", "No se encontró fecha de emisión en el documento")
        today = date.today()
        delta_days = (today - doc_date).days
        if delta_days < 0:
            return self._warning("frescura_fecha", f"Fecha del documento es futura: {doc_date}")
        if delta_days <= 92:  # ~3 meses
            return self._passed("frescura_fecha", f"Documento reciente: emitido el {doc_date} ({delta_days} días)")
        return self._failed(
            "frescura_fecha",
            f"Documento con más de 3 meses de antigüedad: {doc_date} ({delta_days} días)",
        )

    def _check_rfc(self, text: str) -> CheckItem:
        if not text:
            return self._skipped("formato_rfc", "Texto no disponible")
        match = _RFC_RE.search(text)
        if match:
            return self._passed("formato_rfc", f"RFC con formato válido encontrado: {match.group(0)}")
        return self._skipped("formato_rfc", "No se encontró RFC en el documento")

    def _check_balance_consistency(self, data: Dict) -> CheckItem:
        balance = data.get("balance")
        income = data.get("monthly_income")
        expenses = data.get("monthly_expenses")
        if income is None or expenses is None:
            return self._skipped("consistencia_saldo", "Datos de depósitos/retiros no disponibles para validar consistencia")
        net = income - expenses
        if balance is not None:
            diff = abs(balance - net)
            if diff < 1.0:
                return self._passed("consistencia_saldo", f"Saldo consistente: {balance:,.2f}")
            elif diff < balance * 0.05:
                return self._warning("consistencia_saldo", f"Saldo con pequeña diferencia (±{diff:,.2f})")
            return self._warning("consistencia_saldo", f"Diferencia en saldo: esperado ~{net:,.2f}, encontrado {balance:,.2f}")
        return self._passed("consistencia_saldo", f"Flujo neto calculado: {net:,.2f}")
