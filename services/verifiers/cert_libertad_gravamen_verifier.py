"""
Verificador de Certificado de Libertad de Gravamen (RPP)
Checks: layout RPP, folio real, titular, inmueble sin gravámenes, vigencia 30 días, notario/autoridad
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
_FOLIO_RE = re.compile(r'(?:folio|folio\s+real|fol\.?|folio\s+electr[oó]nico)[:\s]+([A-Z0-9\-/]{4,25})', re.I)

_MONTHS_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}

_GRAVAMEN_KEYWORDS = [
    "hipoteca", "embargo", "gravamen", "carga", "restricción", "anotación preventiva",
    "usufructo", "servidumbre", "afectación", "prohibición de enajenar",
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


class CertLibertadGravamenVerifier(BaseVerifier):
    """Verifica autenticidad de un Certificado de Libertad de Gravamen del RPP."""

    async def verify(self, file_path: str, extracted_data: Dict, preloaded_qr_codes: Optional[List] = None) -> List[CheckItem]:
        checks: List[CheckItem] = []
        raw_text: str = extracted_data.get("_raw_text", "")

        # 1. Layout RPP
        checks.append(self._check_layout(raw_text))

        # 2. Folio Real presente
        folio = extracted_data.get("folio_real", "")
        checks.append(self._check_folio_real(folio, raw_text))

        # 3. Vigencia del certificado (máx 30 días para traslativas)
        checks.append(self._check_vigencia(raw_text))

        # 4. Declaración de libertad de gravamen (ausencia de cargas)
        checks.append(self._check_libre_gravamen(raw_text))

        # 5. Titular registral presente
        titular = extracted_data.get("titular", "") or extracted_data.get("full_name", "")
        checks.append(self._check_titular(titular, raw_text))

        # 6. Datos del inmueble
        checks.append(self._check_datos_inmueble(raw_text))

        # 7. Autoridad emisora (RPP estatal)
        checks.append(self._check_autoridad(raw_text))

        # 8. Sello y firma de autoridad
        checks.append(self._check_sello_firma(raw_text))

        # 9. Análisis de fraude visual
        checks.extend(await self._run_fraud_analysis(file_path, "cert_libertad_gravamen", extracted_data, preloaded_qr_codes))

        return checks

    def _check_layout(self, text: str) -> CheckItem:
        t = text.lower()
        signals = [
            any(w in t for w in ["certificado de libertad", "libertad de gravamen", "libre de gravamen"]),
            any(w in t for w in ["registro público de la propiedad", "rpp", "registro público"]),
            any(w in t for w in ["folio real", "folio electrónico", "folio registral"]),
            any(w in t for w in ["director", "registrador", "titular del registro"]),
        ]
        score = sum(signals)
        if score >= 3:
            return self._passed("layout_cert_libertad", "Documento identificado como Certificado de Libertad de Gravamen (RPP)")
        if score >= 2:
            return self._warning("layout_cert_libertad", "Documento parcialmente identificado como certificado del RPP")
        return self._warning("layout_cert_libertad", "No se confirmó que el documento sea un Certificado de Libertad de Gravamen")

    def _check_folio_real(self, folio: str, raw_text: str) -> CheckItem:
        candidate = folio
        if not candidate:
            m = _FOLIO_RE.search(raw_text)
            candidate = m.group(1).strip() if m else ""
        if candidate:
            return self._passed("folio_real_cert", f"Folio Real presente: {candidate}")
        return self._failed("folio_real_cert", "Folio Real no encontrado — identificador obligatorio del RPP")

    def _check_vigencia(self, raw_text: str) -> CheckItem:
        cert_date = _parse_date(raw_text)
        if not cert_date:
            return self._warning("vigencia_cert_libertad", "No se encontró fecha de expedición del certificado")
        today = date.today()
        days_old = (today - cert_date).days
        if days_old < 0:
            return self._warning("vigencia_cert_libertad", f"Fecha futura en el certificado: {cert_date}")
        if days_old <= 30:
            return self._passed("vigencia_cert_libertad", f"Certificado vigente: expedido el {cert_date} ({days_old} días). Las notarías exigen máx. 30 días.")
        if days_old <= 90:
            return self._warning(
                "vigencia_cert_libertad",
                f"Certificado con {days_old} días de antigüedad — puede estar vencido. Las notarías exigen emisión máximo 30 días antes de la firma.",
            )
        return self._failed(
            "vigencia_cert_libertad",
            f"Certificado con {days_old} días de antigüedad — VENCIDO para efectos notariales (máx. 30 días).",
        )

    def _check_libre_gravamen(self, raw_text: str) -> CheckItem:
        t = raw_text.lower()
        # Buscar declaración explícita de libertad
        libre_signals = [
            "libre de gravamen" in t,
            "no registra gravamen" in t,
            "sin gravámenes" in t,
            "sin cargas" in t,
            "no tiene gravamen" in t,
            "no existen anotaciones" in t,
            "no aparecen gravámenes" in t,
        ]
        if any(libre_signals):
            return self._passed("libre_gravamen", "Certificado declara inmueble LIBRE DE GRAVAMEN")

        # Buscar gravámenes registrados
        gravamenes_encontrados = [kw for kw in _GRAVAMEN_KEYWORDS if kw in t]
        if gravamenes_encontrados:
            return self._failed(
                "libre_gravamen",
                f"GRAVAMEN(ES) DETECTADO(S): {', '.join(gravamenes_encontrados)} — el inmueble no está libre de cargas",
            )

        return self._warning("libre_gravamen", "No se pudo determinar el estado de gravamen — verificar el texto del certificado manualmente")

    def _check_titular(self, titular: str, raw_text: str) -> CheckItem:
        if titular and len(titular.strip()) >= 4:
            return self._passed("titular_cert_libertad", f"Titular registral presente: {titular}")
        for label in ["propietario registral", "titular registral", "nombre del titular", "a nombre de", "propietario"]:
            m = re.search(rf'{label}[:\s]+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s]{{4,50}})', raw_text, re.I)
            if m:
                return self._passed("titular_cert_libertad", f"Titular encontrado: {m.group(1).strip()}")
        return self._warning("titular_cert_libertad", "Nombre del titular registral no identificado en el certificado")

    def _check_datos_inmueble(self, raw_text: str) -> CheckItem:
        t = raw_text.lower()
        has_address = any(w in t for w in ["calle", "avenida", "blvd", "colonia", "fraccionamiento"])
        has_municipio = "municipio" in t or "ciudad" in t
        has_superficie = bool(re.search(r'\d+[\.,]\d*\s*m[²2]', raw_text, re.I))
        score = sum([has_address, has_municipio, has_superficie])
        if score >= 2:
            return self._passed("datos_inmueble_cert", "Datos del inmueble presentes en el certificado")
        return self._warning("datos_inmueble_cert", "Datos del inmueble incompletos en el certificado")

    def _check_autoridad(self, raw_text: str) -> CheckItem:
        t = raw_text.lower()
        has_rpp = any(w in t for w in ["registro público de la propiedad", "director del registro", "registrador público"])
        has_estado = any(w in t for w in [
            "querétaro", "jalisco", "ciudad de méxico", "nuevo león", "estado de méxico",
            "guanajuato", "puebla", "veracruz", "baja california",
        ])
        if has_rpp:
            return self._passed("autoridad_rpp", "Autoridad emisora (RPP) identificada en el certificado")
        if has_estado:
            return self._warning("autoridad_rpp", "Entidad federativa identificada pero no el RPP específico")
        return self._warning("autoridad_rpp", "Autoridad emisora del RPP no identificada claramente")

    def _check_sello_firma(self, raw_text: str) -> CheckItem:
        t = raw_text.lower()
        has_sello = "sello" in t or "firma" in t or "rúbrica" in t
        has_digital = "firma digital" in t or "sello digital" in t or "firma electrónica" in t or "cadena original" in t
        if has_digital:
            return self._passed("sello_firma_cert", "Sello/firma digital certificada presente — certificado electrónico")
        if has_sello:
            return self._passed("sello_firma_cert", "Sello y/o firma del RPP presentes en el certificado")
        return self._warning("sello_firma_cert", "No se identificó sello ni firma del RPP — verificar documento original")
