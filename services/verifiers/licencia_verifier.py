"""
Verificador de Licencia de Conducir
Checks: layout, nombre, vigencia, CURP, clase/tipo, entidad emisora
"""

import re
import logging
from datetime import date
from typing import Dict, List, Optional

from models.verification_schemas import CheckItem
from services.verifiers.base_verifier import BaseVerifier

logger = logging.getLogger(__name__)

_CURP_RE = re.compile(r'\b([A-Z]{4}\d{6}[HM][A-Z]{5}[0-9A-Z]\d)\b')
_DATE_RE = re.compile(r'\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\b')

_CLASES_LICENCIA = ["a", "b", "c", "d", "e", "chofer", "automovilista", "motociclista", "camionero"]

_ENTIDADES = [
    "aguascalientes", "baja california", "campeche", "chiapas", "chihuahua",
    "cdmx", "ciudad de méxico", "coahuila", "colima", "durango", "guanajuato",
    "guerrero", "hidalgo", "jalisco", "estado de méxico", "edomex", "michoacán",
    "morelos", "nayarit", "nuevo león", "oaxaca", "puebla", "querétaro",
    "quintana roo", "san luis potosí", "sinaloa", "sonora", "tabasco",
    "tamaulipas", "tlaxcala", "veracruz", "yucatán", "zacatecas",
]


class LicenciaVerifier(BaseVerifier):
    """Verifica autenticidad de una Licencia de Conducir mexicana."""

    async def verify(self, file_path: str, extracted_data: Dict, preloaded_qr_codes: Optional[List] = None) -> List[CheckItem]:
        checks: List[CheckItem] = []
        raw_text: str = extracted_data.get("_raw_text", "")

        checks.append(self._check_layout(raw_text))
        checks.append(self._check_nombre(extracted_data, raw_text))
        checks.append(self._check_vigencia(extracted_data, raw_text))
        checks.append(self._check_curp(extracted_data, raw_text))
        checks.append(self._check_clase(raw_text))
        checks.append(self._check_entidad(raw_text))
        checks.extend(await self._run_fraud_analysis(file_path, "licencia", extracted_data, preloaded_qr_codes))

        return checks

    def _check_layout(self, text: str) -> CheckItem:
        t = text.lower()
        signals = [
            any(w in t for w in ["licencia de conducir", "licencia para conducir", "permiso de conducir"]),
            any(w in t for w in ["secretaría de movilidad", "secretaría de transporte", "dirección de tránsito", "municipio"]),
            any(w in t for w in ["clase", "tipo de licencia", "categoría"]),
            any(w in t for w in ["vigencia", "vence", "válida hasta", "fecha de vencimiento"]),
        ]
        score = sum(signals)
        if score >= 3:
            return self._passed("layout_licencia", "Documento identificado como Licencia de Conducir")
        if score >= 2:
            return self._warning("layout_licencia", "Documento parcialmente identificado como licencia de conducir")
        return self._warning("layout_licencia", "No se confirmó que el documento sea una Licencia de Conducir")

    def _check_nombre(self, extracted_data: Dict, raw_text: str) -> CheckItem:
        name = extracted_data.get("full_name", "")
        if name and len(name.strip()) >= 4:
            return self._passed("nombre_licencia", f"Nombre del titular presente: {name}")
        m = re.search(r'nombre[:\s]+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s]{4,50})', raw_text, re.I)
        if m:
            return self._passed("nombre_licencia", f"Nombre encontrado: {m.group(1).strip()}")
        return self._warning("nombre_licencia", "Nombre del titular no encontrado en la licencia")

    def _check_vigencia(self, extracted_data: Dict, raw_text: str) -> CheckItem:
        expiry = extracted_data.get("expiration_date", "")
        text_to_search = expiry if expiry else raw_text
        m = _DATE_RE.search(text_to_search)
        if not m:
            return self._warning("vigencia_licencia", "Fecha de vigencia no encontrada en la licencia")
        try:
            parts = [int(m.group(1)), int(m.group(2)), int(m.group(3))]
            # Si el año está en posición 3 y es > 2000, es DD/MM/YYYY
            if parts[2] > 2000:
                expiry_date = date(parts[2], parts[1], parts[0])
            else:
                # YYYY/MM/DD
                expiry_date = date(parts[0], parts[1], parts[2])
            today = date.today()
            if expiry_date < today:
                return self._failed("vigencia_licencia", f"Licencia VENCIDA: vigencia hasta {expiry_date}")
            return self._passed("vigencia_licencia", f"Licencia vigente hasta: {expiry_date}")
        except (ValueError, IndexError):
            return self._warning("vigencia_licencia", "No se pudo interpretar la fecha de vigencia")

    def _check_curp(self, extracted_data: Dict, raw_text: str) -> CheckItem:
        curp = extracted_data.get("curp", "")
        if not curp:
            m = _CURP_RE.search(raw_text.upper())
            curp = m.group(1) if m else ""
        if curp:
            return self._passed("curp_licencia", f"CURP presente en la licencia: {curp}")
        return self._warning("curp_licencia", "CURP no encontrado — algunas licencias estatales no lo incluyen")

    def _check_clase(self, raw_text: str) -> CheckItem:
        t = raw_text.lower()
        found_clase = next((c for c in _CLASES_LICENCIA if c in t), None)
        if found_clase:
            return self._passed("clase_licencia", f"Clase/tipo de licencia identificado: {found_clase.upper()}")
        if "tipo" in t or "categoría" in t:
            return self._warning("clase_licencia", "Referencia a tipo/categoría pero clase específica no extraída")
        return self._warning("clase_licencia", "Clase de licencia no identificada en el documento")

    def _check_entidad(self, raw_text: str) -> CheckItem:
        t = raw_text.lower()
        found = [e for e in _ENTIDADES if e in t]
        if found:
            return self._passed("entidad_licencia", f"Entidad emisora: {found[0].title()}")
        return self._warning("entidad_licencia", "Entidad federativa emisora no identificada en la licencia")
