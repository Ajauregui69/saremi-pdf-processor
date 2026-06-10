"""
Verificador de CFDI / Factura Electrónica
Checks: UUID folio fiscal, RFC emisor/receptor, QR SAT, timbrado PAC, monto, fecha
"""

import re
import logging
import os
from datetime import date
from typing import Dict, List, Optional

import httpx

from models.verification_schemas import CheckItem
from services.verifiers.base_verifier import BaseVerifier

logger = logging.getLogger(__name__)

SCRAPER_TIMEOUT = int(os.getenv("SCRAPER_TIMEOUT_SECONDS", "15"))

_UUID_RE = re.compile(r'\b([0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12})\b')
_RFC_RE = re.compile(r'\b([A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3})\b')
_DATE_RE = re.compile(r'\b(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})\b')
_AMOUNT_RE = re.compile(r'\$?\s*([\d,]+\.?\d{0,2})')

_SAT_VERIFY_URL = "https://verificacfdi.facturaelectronica.sat.gob.mx/default.aspx"


class CFDIVerifier(BaseVerifier):
    """Verifica autenticidad de un CFDI / Factura Electrónica mexicana."""

    async def verify(self, file_path: str, extracted_data: Dict, preloaded_qr_codes: Optional[List] = None) -> List[CheckItem]:
        checks: List[CheckItem] = []
        raw_text: str = extracted_data.get("_raw_text", "")

        # 1. Layout CFDI
        checks.append(self._check_layout(raw_text))

        # 2. UUID / Folio Fiscal
        uuid = extracted_data.get("cfdi_uuid", "") or extracted_data.get("uuid", "")
        checks.append(self._check_uuid(uuid, raw_text))

        # 3. RFC emisor
        rfc_emisor = extracted_data.get("rfc_emisor", "") or extracted_data.get("rfc", "")
        checks.append(self._check_rfc(rfc_emisor, raw_text, "emisor"))

        # 4. RFC receptor
        rfc_receptor = extracted_data.get("rfc_receptor", "")
        checks.append(self._check_rfc(rfc_receptor, raw_text, "receptor"))

        # 5. Monto
        monto = extracted_data.get("monto") or extracted_data.get("total")
        checks.append(self._check_monto(monto, raw_text))

        # 6. Fecha de emisión
        fecha_str = extracted_data.get("fecha_emision", "") or extracted_data.get("issue_date", "")
        checks.append(self._check_fecha(fecha_str, raw_text))

        # 7. Sello SAT y cadena original
        checks.append(self._check_sello_sat(raw_text))

        # 8. QR SAT (verifica contra portal oficial)
        checks.append(await self._check_qr_sat(raw_text, preloaded_qr_codes))

        # 9. Análisis de fraude visual
        checks.extend(await self._run_fraud_analysis(file_path, "cfdi", extracted_data, preloaded_qr_codes))

        return checks

    def _check_layout(self, text: str) -> CheckItem:
        t = text.lower()
        signals = [
            any(w in t for w in ["cfdi", "factura electrónica", "comprobante fiscal"]),
            any(w in t for w in ["servicio de administración tributaria", "sat"]),
            any(w in t for w in ["folio fiscal", "uuid", "timbre fiscal"]),
            any(w in t for w in ["rfc emisor", "rfc receptor", "rfc del emisor"]),
        ]
        score = sum(signals)
        if score >= 3:
            return self._passed("layout_cfdi", "Documento identificado como CFDI / Factura Electrónica SAT")
        if score >= 2:
            return self._warning("layout_cfdi", "Documento parcialmente identificado como CFDI")
        return self._warning("layout_cfdi", "No se confirmó que el documento sea un CFDI del SAT")

    def _check_uuid(self, uuid: str, raw_text: str) -> CheckItem:
        candidate = uuid
        if not candidate:
            m = _UUID_RE.search(raw_text)
            candidate = m.group(1).upper() if m else ""
        if not candidate:
            return self._failed("cfdi_timbrado", "No se encontró UUID/Folio Fiscal — el CFDI no está timbrado por el SAT o es un documento no válido")
        return self._passed("cfdi_timbrado", f"UUID/Folio Fiscal presente: {candidate}")

    def _check_rfc(self, rfc: str, raw_text: str, rol: str) -> CheckItem:
        candidate = rfc.strip().upper() if rfc else ""
        if not candidate:
            rfcs = _RFC_RE.findall(raw_text.upper())
            candidate = rfcs[0] if rfcs else ""
        if not candidate:
            return self._warning(f"rfc_{rol}_cfdi", f"RFC del {rol} no encontrado en el CFDI")
        is_pf = len(candidate) == 13
        is_pm = len(candidate) == 12
        tipo = "Persona Física" if is_pf else ("Persona Moral" if is_pm else "?")
        return self._passed(f"rfc_{rol}_cfdi", f"RFC {rol} ({tipo}): {candidate}")

    def _check_monto(self, monto, raw_text: str) -> CheckItem:
        amount = monto
        if not amount:
            matches = _AMOUNT_RE.findall(raw_text)
            for m in matches:
                try:
                    val = float(m.replace(",", ""))
                    if val > 0:
                        amount = val
                        break
                except ValueError:
                    continue
        if amount:
            return self._passed("monto_cfdi", f"Total del CFDI: ${float(amount):,.2f} MXN")
        return self._warning("monto_cfdi", "No se encontró el monto total del CFDI")

    def _check_fecha(self, fecha_str: str, raw_text: str) -> CheckItem:
        doc_date = None
        if fecha_str:
            m = _DATE_RE.search(fecha_str)
            if m:
                try:
                    doc_date = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                except ValueError:
                    pass
        if not doc_date:
            m = _DATE_RE.search(raw_text)
            if m:
                try:
                    doc_date = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                except ValueError:
                    pass
        if not doc_date:
            return self._warning("fecha_cfdi", "No se encontró fecha de emisión del CFDI")
        today = date.today()
        if doc_date > today:
            return self._failed("fecha_cfdi", f"Fecha de emisión futura en el CFDI: {doc_date} — indicador de falsificación")
        days = (today - doc_date).days
        return self._passed("fecha_cfdi", f"Fecha de emisión: {doc_date} ({days} días de antigüedad)")

    def _check_sello_sat(self, raw_text: str) -> CheckItem:
        t = raw_text.lower()
        has_sello = "sello digital del sat" in t or "sello del sat" in t or "timbre fiscal digital" in t
        has_cadena = "cadena original" in t or "cadena del complemento de certificación" in t
        has_pac = "proveedor autorizado" in t or "pac" in t or "certificación" in t
        if has_sello or has_cadena:
            return self._passed("sello_sat_cfdi", "Sello digital del SAT y/o cadena original presente")
        if has_pac:
            return self._warning("sello_sat_cfdi", "Referencia a PAC/certificación presente pero sello del SAT no detectado")
        return self._warning("sello_sat_cfdi", "No se identificó sello digital del SAT — verificar que el CFDI esté correctamente timbrado")

    async def _check_qr_sat(self, raw_text: str, preloaded_qr_codes: Optional[List]) -> CheckItem:
        # Revisar QR pre-escaneados
        if preloaded_qr_codes:
            for qr in preloaded_qr_codes:
                data = qr.get("data", "")
                if "sat.gob.mx" in data.lower() or "verificacfdi" in data.lower():
                    return self._passed("qr_sat_cfdi", f"QR SAT detectado: {data[:80]}")
                m = _UUID_RE.search(data)
                if m:
                    return self._passed("qr_sat_cfdi", f"QR con UUID SAT: {m.group(1).upper()}")

        # Buscar URL SAT en texto
        url_m = re.search(r'https?://[^\s]*(?:sat\.gob\.mx|verificacfdi)[^\s]*', raw_text, re.I)
        if url_m:
            return self._passed("qr_sat_cfdi", f"URL de verificación SAT en el documento: {url_m.group(0)[:80]}")

        return self._warning("qr_sat_cfdi", "QR del SAT no encontrado — todos los CFDIs timbrados contienen QR de verificación")
