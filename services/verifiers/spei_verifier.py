"""
Verificador de Comprobante SPEI
Checks: CLABE checksum Banxico, clave de rastreo formato, banco válido, monto, CEP Banxico
El SPEI es el documento más falsificado en notarías — tratamiento prioritario.
"""

import re
import logging
import os
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

import httpx

from models.verification_schemas import CheckItem
from services.verifiers.base_verifier import BaseVerifier

logger = logging.getLogger(__name__)

SCRAPER_TIMEOUT = int(os.getenv("SCRAPER_TIMEOUT_SECONDS", "20"))
CEP_BANXICO_URL = "https://www.banxico.org.mx/cep/"

# Catálogo de bancos Banxico (código 3 dígitos → nombre)
_BANCOS_MX = {
    "002": "BBVA Bancomer", "006": "Bancomext", "009": "Banobras", "012": "HSBC",
    "014": "Santander", "021": "HSBC", "030": "Bajío", "032": "IXE",
    "036": "Inbursa", "037": "Multiva", "042": "Mifel", "044": "Scotiabank",
    "058": "Banregio", "059": "Invex", "060": "BanBajío", "062": "Afirme",
    "072": "Banorte", "102": "ABN AMRO", "103": "American Express", "106": "BAMSA",
    "108": "Tokyo", "110": "JP Morgan", "112": "Bansí", "113": "Walmart",
    "116": "ING", "124": "Deutsche", "126": "Credit Suisse", "127": "Azteca",
    "128": "Autofin", "129": "Barclays", "130": "Compartamos", "132": "Multiva Cbolsa",
    "133": "Actinver", "134": "Walmart", "135": "NAFIN", "136": "HDI Seguros",
    "137": "Order", "138": "Akala", "140": "Libertad", "141": "AgroFin",
    "143": "CiBanco", "145": "BBASE", "147": "Bankaool", "148": "PagaTodo",
    "149": "Inmobiliario", "155": "ICBC", "156": "Sabadell", "166": "BanBajío",
    "168": "Hipotecaria Federal", "600": "Monexcb", "601": "GBM", "602": "Bamsa",
    "605": "Valué", "606": "Fondos Fondos", "607": "Base", "608": "FinComún",
    "610": "HN", "611": "aCXion", "613": "Multiva Cbolsa", "616": "Finamex",
    "617": "VALORE", "618": "Único", "621": "CEBANCO", "622": "FAMSA",
    "623": "Actinver", "626": "CBDEUTSCHE", "627": "ZURICHVI", "628": "SU CASITA",
    "629": "CBI", "630": "HEXAGON", "631": "CI Bolsa", "632": "Bulltick CB",
    "633": "HDI Seguros", "634": "Order", "636": "HDI Seguros", "637": "Order",
    "638": "Akala", "640": "CB JP Morgan", "642": "Reforma", "646": "STP",
    "648": "EVERCORE", "649": "SKANDIA", "651": "Segmenta", "652": "Asea",
    "653": "Kuspit", "655": "Sofiexpress", "656": "Unagra", "659": "ASP Integra OPC",
    "670": "Arcus", "674": "ARC4", "677": "Caja Pop Mexicana", "679": "FdeEE",
    "684": "Transfer", "685": "Fondo (FIRA)", "686": "Invercap", "689": "FDEAM",
    "699": "CoDi Valida", "706": "Arcus", "710": "Telecomunicaciones", "722": "Mercado Pago",
    "723": "Cuenca", "728": "SPIN by OXXO", "730": "Nvio", "732": "Telecomunicaciones",
    "733": "Aspen", "734": "Esa", "736": "HDI Seguros", "737": "Order", "738": "Clipper",
    "742": "Opciones Empresariales", "743": "Teshkal", "744": "CoDi Valida",
    "745": "BanBajío", "746": "STP", "747": "Telecomunicaciones", "748": "Acacia RFC",
    "749": "GBMOAXACA", "750": "Ictineo Plataforma", "753": "Cuenca",
    "758": "Nvio", "760": "Forseti", "761": "Finpatria", "765": "Odalys",
    "766": "Bansefi", "814": "Fincomun", "846": "STP", "848": "Evercore",
    "849": "BBVA Bancomer2", "900": "CoDi", "901": "CL&E", "902": "Indeval",
}

# Regex clave de rastreo SPEI (formato Banxico: banco(3) + fecha(8) + secuencia(18) = 29 chars)
_CLAVE_RASTREO_RE = re.compile(r'\b(\d{3}\d{8}[A-Z0-9]{18})\b')
# También formato con guiones o letras al inicio
_CLAVE_RASTREO_LOOSE = re.compile(r'\b([A-Z]{0,3}\d{3}\d{8}[A-Z0-9]{14,22})\b')

_CLABE_RE = re.compile(r'\b(\d{18})\b')
_AMOUNT_RE = re.compile(r'\$?\s*([\d,]+\.?\d{0,2})')
_DATE_RE = re.compile(r'\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\b')
_DATE_ES_RE = re.compile(r'\b(\d{1,2})\s+de\s+([a-záéíóúñ]+)\s+de\s+(\d{4})\b', re.I)
_MONTHS_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}


def _clabe_checksum(clabe: str) -> bool:
    """
    Valida el dígito verificador de una CLABE bancaria (18 dígitos).
    Algoritmo Banxico: pesos 3,7,1 para las primeras 17 posiciones, 18ª = dígito verificador.
    """
    if len(clabe) != 18 or not clabe.isdigit():
        return False
    weights = [3, 7, 1] * 6  # 18 pesos: 3,7,1,3,7,1,...
    total = sum(int(c) * w for c, w in zip(clabe[:17], weights[:17]))
    check = (10 - (total % 10)) % 10
    return check == int(clabe[17])


def _extract_bank_from_clabe(clabe: str) -> Tuple[str, str]:
    """Retorna (código_banco, nombre_banco) desde los primeros 3 dígitos de la CLABE."""
    if len(clabe) >= 3:
        code = clabe[:3]
        return code, _BANCOS_MX.get(code, f"Banco código {code}")
    return "", ""


def _parse_amount(text: str) -> Optional[float]:
    # Buscar montos grandes (transfers SPEI suelen ser > $1,000)
    matches = _AMOUNT_RE.findall(text)
    for m in matches:
        try:
            val = float(m.replace(",", ""))
            if val >= 100:
                return val
        except ValueError:
            continue
    return None


def _parse_date(text: str) -> Optional[date]:
    for m in _DATE_RE.finditer(text):
        try:
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 1 <= mo <= 12 and 1 <= d <= 31 and 2000 <= y <= date.today().year:
                return date(y, mo, d)
        except ValueError:
            continue
    for m in _DATE_ES_RE.finditer(text):
        try:
            month_num = _MONTHS_ES.get(m.group(2).lower())
            if month_num:
                y = int(m.group(3))
                if 2000 <= y <= date.today().year:
                    return date(y, month_num, int(m.group(1)))
        except ValueError:
            continue
    return None


class SPEIVerifier(BaseVerifier):
    """Verifica autenticidad de un comprobante de transferencia SPEI."""

    async def verify(self, file_path: str, extracted_data: Dict, preloaded_qr_codes: Optional[List] = None) -> List[CheckItem]:
        checks: List[CheckItem] = []
        raw_text: str = extracted_data.get("_raw_text", "")

        # 1. Layout SPEI
        checks.append(self._check_spei_layout(raw_text))

        # 2. CLABE origen — checksum Banxico
        clabe_origen = extracted_data.get("clabe_origen", "")
        checks.extend(self._check_clabe(clabe_origen, raw_text, "origen"))

        # 3. CLABE destino — checksum Banxico
        clabe_destino = extracted_data.get("clabe_destino", "")
        checks.extend(self._check_clabe(clabe_destino, raw_text, "destino"))

        # 4. Clave de rastreo / folio Banxico
        clave_rastreo = extracted_data.get("clave_rastreo", "")
        checks.append(self._check_clave_rastreo(clave_rastreo, raw_text))

        # 5. Banco identificado
        checks.append(self._check_banco(raw_text, clabe_origen or clabe_destino))

        # 6. Monto presente y razonable
        monto = extracted_data.get("monto")
        checks.append(self._check_monto(monto, raw_text))

        # 7. Fecha coherente (no futura, no > 2 años)
        fecha_str = extracted_data.get("fecha_spei", "")
        checks.append(self._check_fecha(fecha_str, raw_text))

        # 8. Titular origen vs destino (no mismo titular en ambos lados)
        checks.append(self._check_titulares(extracted_data, raw_text))

        # 9. Consulta CEP Banxico para montos grandes
        clave_rastreo_found = clave_rastreo or self._find_clave_rastreo(raw_text)
        monto_val = monto or _parse_amount(raw_text) or 0
        if clave_rastreo_found and monto_val >= 50000:
            checks.append(await self._check_cep_banxico(clave_rastreo_found))
        elif monto_val >= 50000:
            checks.append(self._warning("cep_banxico", f"Monto ${monto_val:,.2f} ≥ $50,000 — se recomienda verificar en CEP Banxico pero no se encontró clave de rastreo"))

        # 10. Análisis de fraude visual
        checks.extend(await self._run_fraud_analysis(file_path, "spei", extracted_data, preloaded_qr_codes))

        return checks

    # ── helpers ───────────────────────────────────────────────────────────────

    def _find_clabe_candidates(self, text: str) -> List[str]:
        return list(dict.fromkeys(_CLABE_RE.findall(text)))

    def _find_clave_rastreo(self, text: str) -> str:
        m = _CLAVE_RASTREO_RE.search(text)
        if m:
            return m.group(1)
        m = _CLAVE_RASTREO_LOOSE.search(text)
        return m.group(1) if m else ""

    # ── checks internos ───────────────────────────────────────────────────────

    def _check_spei_layout(self, text: str) -> CheckItem:
        t = text.lower()
        signals = [
            "spei" in t,
            "transferencia" in t,
            any(kw in t for kw in ["clabe", "cuenta destino", "cuenta origen"]),
            any(kw in t for kw in ["clave de rastreo", "folio", "referencia"]),
            any(bank.lower() in t for bank in list(_BANCOS_MX.values())[:10]),
        ]
        score = sum(signals)
        if score >= 3:
            return self._passed("layout_spei", "Documento identificado como comprobante SPEI")
        if score >= 2:
            return self._warning("layout_spei", "Documento parcialmente identificado como SPEI")
        return self._warning("layout_spei", "No se confirmó que el documento sea un comprobante SPEI")

    def _check_clabe(self, clabe: str, raw_text: str, lado: str) -> List[CheckItem]:
        # Si no viene en datos extraídos, buscar en texto
        candidate = clabe.replace(" ", "").replace("-", "") if clabe else ""
        if not candidate:
            candidates = self._find_clabe_candidates(raw_text)
            # Tomar la primera que valide checksum
            for c in candidates:
                if _clabe_checksum(c):
                    candidate = c
                    break
            if not candidate and candidates:
                candidate = candidates[0]  # al menos tomar la primera para reportar

        if not candidate:
            return [self._skipped(f"clabe_{lado}", f"CLABE {lado} no encontrada en el documento")]

        if len(candidate) != 18:
            return [self._warning(f"clabe_{lado}", f"CLABE {lado} con longitud inesperada: {candidate!r} ({len(candidate)} dígitos)")]

        is_valid = _clabe_checksum(candidate)
        bank_code, bank_name = _extract_bank_from_clabe(candidate)
        bank_info = f"Banco: {bank_name} (código {bank_code})"

        if is_valid:
            return [self._passed(f"clabe_{lado}", f"CLABE {lado} válida: {candidate[:4]}...{candidate[-4:]} | {bank_info}")]
        return [self._failed(
            f"clabe_{lado}",
            f"CLABE {lado} con dígito verificador INVÁLIDO: {candidate} — posible falsificación. {bank_info}",
        )]

    def _check_clave_rastreo(self, clave: str, raw_text: str) -> CheckItem:
        candidate = clave or self._find_clave_rastreo(raw_text)
        if not candidate:
            return self._failed(
                "clave_rastreo_spei",
                "No se encontró clave de rastreo (folio Banxico) — TODOS los SPEI auténticos tienen clave de rastreo. Indicador fuerte de falsificación.",
            )
        # Validar longitud básica (Banxico: 29 chars típicamente)
        clean = candidate.replace("-", "").replace(" ", "")
        if len(clean) < 20 or len(clean) > 35:
            return self._warning("clave_rastreo_spei", f"Clave de rastreo con longitud inusual ({len(clean)} chars): {candidate}")
        return self._passed("clave_rastreo_spei", f"Clave de rastreo presente: {candidate}")

    def _check_banco(self, raw_text: str, clabe: str) -> CheckItem:
        t = raw_text.lower()
        # Banco desde CLABE
        if clabe and len(clabe) >= 3:
            code = clabe[:3]
            bank = _BANCOS_MX.get(code)
            if bank:
                return self._passed("banco_spei", f"Banco identificado por CLABE: {bank} (código {code})")
        # Banco por nombre en texto
        for code, name in _BANCOS_MX.items():
            if name.lower() in t:
                return self._passed("banco_spei", f"Banco identificado por nombre: {name}")
        return self._warning("banco_spei", "No se pudo identificar el banco emisor del SPEI")

    def _check_monto(self, monto: Optional[float], raw_text: str) -> CheckItem:
        amount = monto or _parse_amount(raw_text)
        if not amount:
            return self._failed("monto_spei", "No se encontró monto en el comprobante — campo obligatorio en SPEI auténtico")
        if amount <= 0:
            return self._failed("monto_spei", f"Monto inválido: ${amount:,.2f}")
        if amount > 640_000:
            return self._warning(
                "monto_spei",
                f"Monto ${amount:,.2f} supera $640,000 MXN — posible umbral de estructuración AML. Verificar con CEP Banxico.",
            )
        return self._passed("monto_spei", f"Monto presente: ${amount:,.2f} MXN")

    def _check_fecha(self, fecha_str: str, raw_text: str) -> CheckItem:
        doc_date = _parse_date(fecha_str) if fecha_str else None
        if not doc_date:
            doc_date = _parse_date(raw_text)
        if not doc_date:
            return self._warning("fecha_spei", "No se encontró fecha en el comprobante")
        today = date.today()
        if doc_date > today:
            return self._failed("fecha_spei", f"Fecha FUTURA en el comprobante: {doc_date} — indicador de falsificación")
        days_ago = (today - doc_date).days
        if days_ago > 730:
            return self._warning("fecha_spei", f"Comprobante con más de 2 años de antigüedad: {doc_date}")
        return self._passed("fecha_spei", f"Fecha coherente: {doc_date} (hace {days_ago} días)")

    def _check_titulares(self, extracted_data: Dict, raw_text: str) -> CheckItem:
        titular_origen = extracted_data.get("titular_origen", "")
        titular_destino = extracted_data.get("titular_destino", "")
        if titular_origen and titular_destino:
            if titular_origen.strip().upper() == titular_destino.strip().upper():
                return self._warning(
                    "titulares_spei",
                    f"Titular origen = titular destino ({titular_origen}) — transferencia entre cuentas propias. Verificar si corresponde al comprador/vendedor.",
                )
            return self._passed("titulares_spei", f"Titular origen: {titular_origen} | Titular destino: {titular_destino}")
        if titular_origen or titular_destino:
            present = titular_origen or titular_destino
            return self._warning("titulares_spei", f"Solo un titular identificado: {present}")
        return self._warning("titulares_spei", "No se pudieron extraer los nombres de los titulares — verificar manualmente que origen=comprador y destino=vendedor")

    async def _check_cep_banxico(self, clave_rastreo: str) -> CheckItem:
        """
        Consulta el CEP (Constancia Electrónica de Pago) de Banxico.
        Es la única fuente oficial para verificar que un SPEI realmente ocurrió.
        """
        try:
            clean = clave_rastreo.strip()
            async with httpx.AsyncClient(timeout=SCRAPER_TIMEOUT, follow_redirects=True) as client:
                # Intentar consulta directa CEP
                resp = await client.get(
                    f"https://www.banxico.org.mx/cep/valida.do",
                    params={"claveRastreo": clean, "criterio": "C"},
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                if resp.status_code == 200:
                    text_lower = resp.text.lower()
                    if "no encontrado" in text_lower or "no existe" in text_lower:
                        return self._failed(
                            "cep_banxico",
                            f"Clave de rastreo {clean} NO encontrada en CEP Banxico — SPEI posiblemente falso",
                        )
                    if "monto" in text_lower or "importe" in text_lower or "encontrado" in text_lower:
                        return self._passed("cep_banxico", f"Clave de rastreo verificada en CEP Banxico: {clean}")
                return self._warning(
                    "cep_banxico",
                    f"CEP Banxico consultado pero respuesta no concluyente. Verificar manualmente: {CEP_BANXICO_URL}?claveRastreo={clean}",
                )
        except httpx.TimeoutException:
            return self._skipped("cep_banxico", f"Timeout consultando CEP Banxico. Verificar manualmente: {CEP_BANXICO_URL}")
        except Exception as e:
            logger.warning(f"Error consultando CEP Banxico: {e}")
            return self._skipped("cep_banxico", f"Error al consultar CEP Banxico. Verificar manualmente en {CEP_BANXICO_URL}")
