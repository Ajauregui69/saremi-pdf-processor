"""
Verificador de Tarjeta de Residencia / FM (Forma Migratoria)
Checks: layout INM, número de documento, nacionalidad, tipo de residencia, vigencia, CURP
"""

import re
import logging
from datetime import date
from typing import Dict, List, Optional

from models.verification_schemas import CheckItem
from services.verifiers.base_verifier import BaseVerifier

logger = logging.getLogger(__name__)

_DATE_RE = re.compile(r'\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\b')
_CURP_RE = re.compile(r'\b([A-Z]{4}\d{6}[HM][A-Z]{5}[0-9A-Z]\d)\b')

_TIPOS_RESIDENCIA = [
    "residente permanente", "residente temporal", "visitante",
    "residente permanente retiro", "trabajador fronterizo",
    "fm2", "fm3", "forma migratoria",
]


class FMResidenciaVerifier(BaseVerifier):
    """Verifica autenticidad de una Tarjeta de Residencia / Forma Migratoria (INM México)."""

    async def verify(self, file_path: str, extracted_data: Dict, preloaded_qr_codes: Optional[List] = None) -> List[CheckItem]:
        checks: List[CheckItem] = []
        raw_text: str = extracted_data.get("_raw_text", "")

        checks.append(self._check_layout(raw_text))
        checks.append(self._check_numero_documento(extracted_data, raw_text))
        checks.append(self._check_tipo_residencia(raw_text))
        checks.append(self._check_nacionalidad(extracted_data, raw_text))
        checks.append(self._check_nombre(extracted_data, raw_text))
        checks.append(self._check_vigencia(extracted_data, raw_text))
        checks.append(self._check_curp(extracted_data, raw_text))
        checks.extend(await self._run_fraud_analysis(file_path, "fm_residencia", extracted_data, preloaded_qr_codes))

        return checks

    def _check_layout(self, text: str) -> CheckItem:
        t = text.lower()
        signals = [
            any(w in t for w in ["instituto nacional de migración", "inm", "tarjeta de residencia"]),
            any(w in t for w in ["secretaría de gobernación", "segob", "forma migratoria"]),
            any(w in t for w in ["nacionalidad", "país de nacimiento", "lugar de nacimiento"]),
            any(w in t for w in ["residente", "visitante", "calidad migratoria", "condición de estancia"]),
        ]
        score = sum(signals)
        if score >= 3:
            return self._passed("layout_fm_residencia", "Documento identificado como Tarjeta de Residencia/FM del INM")
        if score >= 2:
            return self._warning("layout_fm_residencia", "Documento parcialmente identificado como tarjeta migratoria")
        return self._warning("layout_fm_residencia", "No se confirmó que el documento sea una Tarjeta de Residencia del INM")

    def _check_numero_documento(self, extracted_data: Dict, raw_text: str) -> CheckItem:
        num = extracted_data.get("document_number", "") or extracted_data.get("numero_documento", "")
        if not num:
            m = re.search(r'(?:n[uú]mero|no\.?|#)[:\s]+([A-Z0-9]{6,15})', raw_text, re.I)
            num = m.group(1) if m else ""
        if num:
            return self._passed("numero_fm_residencia", f"Número de documento presente: {num}")
        return self._warning("numero_fm_residencia", "Número de documento no encontrado en la tarjeta")

    def _check_tipo_residencia(self, raw_text: str) -> CheckItem:
        t = raw_text.lower()
        found = next((tipo for tipo in _TIPOS_RESIDENCIA if tipo in t), None)
        if found:
            return self._passed("tipo_residencia", f"Tipo de residencia: {found.title()}")
        return self._warning("tipo_residencia", "Tipo/condición de residencia no identificado claramente")

    def _check_nacionalidad(self, extracted_data: Dict, raw_text: str) -> CheckItem:
        nacionalidad = extracted_data.get("nationality", "") or extracted_data.get("nacionalidad", "")
        if nacionalidad:
            return self._passed("nacionalidad_fm", f"Nacionalidad presente: {nacionalidad}")
        m = re.search(r'nacionalidad[:\s]+([A-ZÁÉÍÓÚÑ][a-záéíóúñ\s]{2,30})', raw_text, re.I)
        if m:
            return self._passed("nacionalidad_fm", f"Nacionalidad: {m.group(1).strip()}")
        return self._warning("nacionalidad_fm", "Nacionalidad no encontrada en el documento")

    def _check_nombre(self, extracted_data: Dict, raw_text: str) -> CheckItem:
        name = extracted_data.get("full_name", "")
        if name and len(name.strip()) >= 4:
            return self._passed("nombre_fm_residencia", f"Nombre del titular presente: {name}")
        m = re.search(r'nombre[:\s]+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s]{4,60})', raw_text, re.I)
        if m:
            return self._passed("nombre_fm_residencia", f"Nombre encontrado: {m.group(1).strip()}")
        return self._warning("nombre_fm_residencia", "Nombre del titular no encontrado")

    def _check_vigencia(self, extracted_data: Dict, raw_text: str) -> CheckItem:
        expiry = extracted_data.get("expiration_date", "")
        t = expiry if expiry else raw_text
        m = _DATE_RE.search(t)
        if not m:
            return self._warning("vigencia_fm_residencia", "Fecha de vigencia no encontrada")
        try:
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if y < 2000:
                y, mo, d = d, mo, y
            expiry_date = date(y, mo, d)
            today = date.today()
            if expiry_date < today:
                return self._failed("vigencia_fm_residencia", f"Tarjeta VENCIDA: vigencia hasta {expiry_date}")
            return self._passed("vigencia_fm_residencia", f"Tarjeta vigente hasta: {expiry_date}")
        except (ValueError, IndexError):
            return self._warning("vigencia_fm_residencia", "No se pudo interpretar la fecha de vigencia")

    def _check_curp(self, extracted_data: Dict, raw_text: str) -> CheckItem:
        curp = extracted_data.get("curp", "")
        if not curp:
            m = _CURP_RE.search(raw_text.upper())
            curp = m.group(1) if m else ""
        if curp:
            return self._passed("curp_fm_residencia", f"CURP presente en la tarjeta: {curp}")
        return self._skipped("curp_fm_residencia", "CURP no encontrado — extranjeros pueden no tener CURP hasta obtener residencia")
