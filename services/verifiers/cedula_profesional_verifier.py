"""
Verificador de Cédula Profesional
Checks: layout SEP/Buholegal, número de cédula, carrera/institución, nombre, QR SEP
"""

import re
import logging
from datetime import date
from typing import Dict, List, Optional

import httpx

from models.verification_schemas import CheckItem
from services.verifiers.base_verifier import BaseVerifier

logger = logging.getLogger(__name__)

SCRAPER_TIMEOUT = int(__import__('os').getenv("SCRAPER_TIMEOUT_SECONDS", "15"))

_CEDULA_RE = re.compile(r'\b(\d{7,8})\b')
_DATE_RE = re.compile(r'\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\b')
_CURP_RE = re.compile(r'\b([A-Z]{4}\d{6}[HM][A-Z]{5}[0-9A-Z]\d)\b')


class CedulaProfesionalVerifier(BaseVerifier):
    """Verifica autenticidad de una Cédula Profesional de la SEP."""

    async def verify(self, file_path: str, extracted_data: Dict, preloaded_qr_codes: Optional[List] = None) -> List[CheckItem]:
        checks: List[CheckItem] = []
        raw_text: str = extracted_data.get("_raw_text", "")

        checks.append(self._check_layout(raw_text))
        cedula_num = extracted_data.get("cedula_number", "") or extracted_data.get("numero_cedula", "")
        checks.append(self._check_numero_cedula(cedula_num, raw_text))
        checks.append(self._check_carrera_institucion(raw_text))
        checks.append(self._check_nombre(extracted_data, raw_text))
        checks.append(await self._check_cedula_sep(cedula_num, raw_text))
        checks.append(self._check_qr_sep(preloaded_qr_codes, raw_text))
        checks.extend(await self._run_fraud_analysis(file_path, "cedula_profesional", extracted_data, preloaded_qr_codes))

        return checks

    def _check_layout(self, text: str) -> CheckItem:
        t = text.lower()
        signals = [
            any(w in t for w in ["cédula profesional", "cedula profesional", "certificado profesional"]),
            any(w in t for w in ["secretaría de educación pública", "sep", "dirección general de profesiones"]),
            any(w in t for w in ["licenciatura", "maestría", "doctorado", "ingeniería", "carrera"]),
            any(w in t for w in ["institución", "universidad", "instituto tecnológico", "escuela"]),
        ]
        score = sum(signals)
        if score >= 3:
            return self._passed("layout_cedula_profesional", "Documento identificado como Cédula Profesional de la SEP")
        if score >= 2:
            return self._warning("layout_cedula_profesional", "Documento parcialmente identificado como cédula profesional")
        return self._warning("layout_cedula_profesional", "No se confirmó que el documento sea una Cédula Profesional")

    def _check_numero_cedula(self, cedula: str, raw_text: str) -> CheckItem:
        candidate = cedula.strip() if cedula else ""
        if not candidate:
            m = _CEDULA_RE.search(raw_text)
            candidate = m.group(1) if m else ""
        if not candidate:
            return self._warning("numero_cedula", "Número de cédula no encontrado en el documento")
        if len(candidate) not in (7, 8):
            return self._warning("numero_cedula", f"Número de cédula con longitud inusual: {candidate!r} (se esperan 7-8 dígitos)")
        return self._passed("numero_cedula", f"Número de cédula profesional: {candidate}")

    def _check_carrera_institucion(self, raw_text: str) -> CheckItem:
        t = raw_text.lower()
        carreras = [
            "derecho", "medicina", "ingeniería", "arquitectura", "contaduría", "administración",
            "psicología", "enfermería", "odontología", "química", "biología", "economía",
            "licenciatura", "maestría", "doctorado",
        ]
        carrera_encontrada = next((c for c in carreras if c in t), None)
        has_institucion = any(w in t for w in ["universidad", "instituto", "escuela", "tecnológico", "politécnico"])
        if carrera_encontrada and has_institucion:
            return self._passed("carrera_institucion_cedula", f"Carrera ({carrera_encontrada.title()}) e institución presentes")
        if carrera_encontrada:
            return self._warning("carrera_institucion_cedula", f"Carrera ({carrera_encontrada.title()}) presente pero institución no identificada")
        if has_institucion:
            return self._warning("carrera_institucion_cedula", "Institución presente pero carrera/grado no identificado")
        return self._warning("carrera_institucion_cedula", "Carrera e institución no identificadas en la cédula")

    def _check_nombre(self, extracted_data: Dict, raw_text: str) -> CheckItem:
        name = extracted_data.get("full_name", "")
        if name and len(name.strip()) >= 4:
            return self._passed("nombre_cedula", f"Nombre del titular: {name}")
        m = re.search(r'nombre[:\s]+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s]{4,60})', raw_text, re.I)
        if m:
            return self._passed("nombre_cedula", f"Nombre encontrado: {m.group(1).strip()}")
        return self._warning("nombre_cedula", "Nombre del profesionista no encontrado")

    async def _check_cedula_sep(self, cedula: str, raw_text: str) -> CheckItem:
        """Consulta el portal de la SEP (Buholegal / cedulaprofesional.sep.gob.mx)."""
        candidate = cedula.strip() if cedula else ""
        if not candidate:
            m = _CEDULA_RE.search(raw_text)
            candidate = m.group(1) if m else ""
        if not candidate:
            return self._skipped("cedula_sep_consulta", "Número de cédula no disponible para consultar la SEP")
        try:
            async with httpx.AsyncClient(timeout=SCRAPER_TIMEOUT, follow_redirects=True) as client:
                resp = await client.get(
                    f"https://www.buholegal.com/consultacedula/?cedula={candidate}",
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                text_lower = resp.text.lower()
                if "no se encontraron" in text_lower or "no existe" in text_lower:
                    return self._failed("cedula_sep_consulta", f"Cédula {candidate} NO encontrada en el registro de la SEP")
                if candidate in resp.text or "nombre" in text_lower:
                    return self._passed("cedula_sep_consulta", f"Cédula {candidate} encontrada en el registro de la SEP")
                return self._warning("cedula_sep_consulta", f"Respuesta SEP/Buholegal no concluyente para cédula {candidate}")
        except httpx.TimeoutException:
            return self._skipped("cedula_sep_consulta", "Timeout al consultar SEP — verificar en cedulaprofesional.sep.gob.mx")
        except Exception as e:
            return self._skipped("cedula_sep_consulta", f"Error al consultar SEP: {str(e)[:80]}")

    def _check_qr_sep(self, preloaded_qr_codes: Optional[List], raw_text: str) -> CheckItem:
        if preloaded_qr_codes:
            for qr in preloaded_qr_codes:
                data = qr.get("data", "")
                if "sep.gob.mx" in data.lower() or "buholegal" in data.lower() or "cedula" in data.lower():
                    return self._passed("qr_cedula_sep", f"QR de la SEP detectado: {data[:80]}")
                if data.startswith("http"):
                    return self._warning("qr_cedula_sep", f"QR presente pero no apunta a portal SEP: {data[:60]}")
        t = raw_text.lower()
        if "código qr" in t or "qr" in t:
            return self._warning("qr_cedula_sep", "QR mencionado pero no decodificado — verificar en cedulaprofesional.sep.gob.mx")
        return self._skipped("qr_cedula_sep", "QR no encontrado — cédulas físicas pueden no tener QR")
