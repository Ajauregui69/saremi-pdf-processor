"""
Verificador de Boleta Predial
Checks: clave catastral, año fiscal corriente, estado de pago, dirección, QR municipal
"""

import re
import logging
from datetime import date
from typing import Dict, List, Optional

from models.verification_schemas import CheckItem
from services.verifiers.base_verifier import BaseVerifier

logger = logging.getLogger(__name__)

_DATE_RE = re.compile(r'\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\b')
_AMOUNT_RE = re.compile(r'\$?\s*([\d,]+\.?\d{0,2})')
_CP_RE = re.compile(r'\b(\d{5})\b')
_M2_RE = re.compile(r'([\d,]+\.?\d*)\s*m[²2]', re.I)

# Formatos de clave catastral conocidos por municipio/estado
# (simplificado — en producción usar catálogo completo por municipio)
_CLAVE_CATASTRAL_RE = re.compile(
    r'\b([0-9A-Z]{4,6}[0-9]{4,8}[0-9A-Z]{0,6})\b'
)


def _parse_year(text: str) -> Optional[int]:
    years = re.findall(r'\b(20\d{2})\b', text)
    if years:
        return max(int(y) for y in years)
    return None


class PredialVerifier(BaseVerifier):
    """Verifica autenticidad de una boleta predial municipal."""

    async def verify(self, file_path: str, extracted_data: Dict, preloaded_qr_codes: Optional[List] = None) -> List[CheckItem]:
        checks: List[CheckItem] = []
        raw_text: str = extracted_data.get("_raw_text", "")

        # 1. Layout predial
        checks.append(self._check_layout(raw_text))

        # 2. Clave catastral
        clave = extracted_data.get("clave_catastral", "")
        checks.append(self._check_clave_catastral(clave, raw_text))

        # 3. Año fiscal = año actual
        checks.append(self._check_anio_fiscal(raw_text))

        # 4. Estado de pago (pagado / con adeudo)
        checks.append(self._check_estado_pago(raw_text))

        # 5. Titular registral presente
        titular = extracted_data.get("titular", "") or extracted_data.get("account_holder", "")
        checks.append(self._check_titular(titular, raw_text))

        # 6. Dirección del inmueble presente
        checks.append(self._check_direccion(raw_text))

        # 7. Valor catastral y superficie (opcionales)
        checks.append(self._check_valor_superficie(raw_text))

        # 8. QR municipal (donde aplique)
        checks.append(self._check_qr(preloaded_qr_codes, raw_text))

        # 9. Análisis de fraude visual
        checks.extend(await self._run_fraud_analysis(file_path, "predial", extracted_data, preloaded_qr_codes))

        return checks

    # ── checks internos ───────────────────────────────────────────────────────

    def _check_layout(self, text: str) -> CheckItem:
        t = text.lower()
        signals = [
            any(w in t for w in ["predial", "impuesto predial", "boleta predial"]),
            any(w in t for w in ["tesorería", "hacienda municipal", "catastro"]),
            any(w in t for w in ["clave catastral", "clave única", "folio catastral"]),
            any(w in t for w in ["municipio", "municipio de", "ayuntamiento"]),
        ]
        score = sum(signals)
        if score >= 3:
            return self._passed("layout_predial", "Documento identificado como Boleta Predial")
        if score >= 2:
            return self._warning("layout_predial", "Documento parcialmente identificado como predial")
        return self._warning("layout_predial", "No se confirmó que el documento sea una boleta predial")

    def _check_clave_catastral(self, clave: str, raw_text: str) -> CheckItem:
        candidate = clave
        if not candidate:
            # Buscar patrón de clave catastral en el texto
            t = raw_text.upper()
            patterns = [
                r'(?:CLAVE\s+CATASTRAL|CLAVE\s+ÚNICA|FOLIO\s+CATASTRAL)[:\s]+([0-9A-Z]{6,20})',
                r'(?:CATASTRAL)[:\s]+([0-9A-Z\-]{6,20})',
            ]
            for pat in patterns:
                m = re.search(pat, t)
                if m:
                    candidate = m.group(1).strip()
                    break

        if not candidate:
            return self._failed("clave_catastral", "No se encontró clave catastral en la boleta — campo obligatorio")
        if len(candidate) < 4:
            return self._warning("clave_catastral", f"Clave catastral muy corta: {candidate!r}")
        return self._passed("clave_catastral", f"Clave catastral presente: {candidate}")

    def _check_anio_fiscal(self, raw_text: str) -> CheckItem:
        current_year = date.today().year
        anio = _parse_year(raw_text)
        if not anio:
            return self._warning("anio_fiscal_predial", "No se encontró año fiscal en la boleta")
        if anio == current_year:
            return self._passed("anio_fiscal_predial", f"Año fiscal correcto: {anio}")
        if anio == current_year - 1:
            return self._warning(
                "anio_fiscal_predial",
                f"Boleta del año anterior ({anio}) — las notarías requieren predial del año en curso ({current_year})",
            )
        return self._failed(
            "anio_fiscal_predial",
            f"Año fiscal {anio} no corresponde al año actual {current_year} — boleta desactualizada",
        )

    def _check_estado_pago(self, raw_text: str) -> CheckItem:
        t = raw_text.lower()
        if any(w in t for w in ["pagado", "sin adeudo", "al corriente", "liquidado", "cubierto"]):
            return self._passed("estado_pago_predial", "Estado de pago: PAGADO / SIN ADEUDO")
        if any(w in t for w in ["adeudo", "deuda", "pendiente de pago", "en mora", "atraso"]):
            return self._failed("estado_pago_predial", "ADEUDO detectado en la boleta predial — no se puede escriturar con predial adeudado")
        return self._warning("estado_pago_predial", "No se determinó el estado de pago — verificar si la boleta está pagada")

    def _check_titular(self, titular: str, raw_text: str) -> CheckItem:
        if titular and len(titular.strip()) >= 4:
            return self._passed("titular_predial", f"Titular registral presente: {titular}")
        t = raw_text
        for label in ["titular", "propietario", "nombre del propietario", "contribuyente"]:
            m = re.search(rf'{label}[:\s]+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s]{{4,40}})', t, re.I)
            if m:
                return self._passed("titular_predial", f"Titular encontrado: {m.group(1).strip()}")
        return self._warning("titular_predial", "No se encontró nombre del titular en la boleta")

    def _check_direccion(self, raw_text: str) -> CheckItem:
        t = raw_text.lower()
        has_calle = any(w in t for w in ["calle", "av.", "avenida", "blvd", "boulevard", "calzada"])
        has_cp = bool(_CP_RE.search(raw_text))
        has_municipio = "municipio" in t or "ciudad" in t or "colonia" in t
        score = sum([has_calle, has_cp, has_municipio])
        if score >= 2:
            return self._passed("direccion_predial", "Dirección del inmueble presente en la boleta")
        return self._warning("direccion_predial", "Dirección del inmueble incompleta — verificar que coincida con la escritura")

    def _check_valor_superficie(self, raw_text: str) -> CheckItem:
        m2 = _M2_RE.search(raw_text)
        amount = _AMOUNT_RE.search(raw_text)
        details = []
        if m2:
            details.append(f"Superficie: {m2.group(1)} m²")
        if amount:
            try:
                val = float(amount.group(1).replace(",", ""))
                if val > 1000:
                    details.append(f"Valor catastral: ${val:,.2f}")
            except ValueError:
                pass
        if details:
            return self._passed("valor_superficie_predial", " | ".join(details))
        return self._skipped("valor_superficie_predial", "Valor catastral y superficie no extraídos — datos útiles para cruzar con escritura/avalúo")

    def _check_qr(self, preloaded_qr_codes: Optional[List], raw_text: str) -> CheckItem:
        if preloaded_qr_codes:
            for qr in preloaded_qr_codes:
                data = qr.get("data", "")
                if data:
                    return self._passed("qr_predial", f"QR municipal detectado: {data[:80]}")
        t = raw_text.lower()
        if "código qr" in t or "código de barras" in t:
            return self._warning("qr_predial", "QR/código de barras mencionado pero no decodificado")
        return self._skipped("qr_predial", "Sin QR — cobertura de QR catastral es parcial por municipio. Verificar en portal municipal si está disponible.")
