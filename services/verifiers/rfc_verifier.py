"""
Verificador de RFC
Checks: formato, existencia SAT, lista 69-B (EFOS), lista 69 (no localizados), estado padrón
"""

import re
import logging
import os
from typing import Dict, List, Optional, Tuple

import httpx

from models.verification_schemas import CheckItem
from services.verifiers.base_verifier import BaseVerifier

logger = logging.getLogger(__name__)

SCRAPER_TIMEOUT = int(os.getenv("SCRAPER_TIMEOUT_SECONDS", "15"))

# RFC persona física: 4 letras + 6 dígitos + 3 alfanuméricos = 13 chars
# RFC persona moral:  3 letras + 6 dígitos + 3 alfanuméricos = 12 chars
_RFC_PF_RE = re.compile(r'^[A-ZÑ&]{4}\d{6}[A-Z0-9]{3}$')
_RFC_PM_RE = re.compile(r'^[A-ZÑ&]{3}\d{6}[A-Z0-9]{3}$')

# RFC genérico para búsqueda en texto
_RFC_TEXT_RE = re.compile(r'\b([A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3})\b')

# RFCs genéricos que no corresponden a una persona real
_RFC_GENERICOS = {"XAXX010101000", "XEXX010101000", "PUBLICO EN GENERAL"}


class RFCVerifier(BaseVerifier):
    """Verifica validez de un RFC contra el SAT y listas restrictivas."""

    async def verify(self, file_path: str, extracted_data: Dict, preloaded_qr_codes: Optional[List] = None) -> List[CheckItem]:
        checks: List[CheckItem] = []
        raw_text: str = extracted_data.get("_raw_text", "")

        rfc = extracted_data.get("rfc", "").strip().upper()
        if not rfc:
            m = _RFC_TEXT_RE.search(raw_text.upper())
            rfc = m.group(1) if m else ""

        # 1. Formato
        checks.append(self._check_formato(rfc))

        if not rfc or (not _RFC_PF_RE.match(rfc) and not _RFC_PM_RE.match(rfc)):
            checks.append(self._skipped("sat_validador", "RFC con formato inválido — omitiendo consultas externas"))
            checks.append(self._skipped("rfc_lista_69b", "RFC con formato inválido"))
            checks.append(self._skipped("rfc_lista_69", "RFC con formato inválido"))
            checks.extend(await self._run_fraud_analysis(file_path, "rfc", extracted_data, preloaded_qr_codes))
            return checks

        # 2. RFC genérico
        if rfc in _RFC_GENERICOS:
            checks.append(self._warning("rfc_generico", f"RFC genérico detectado ({rfc}) — no identifica a una persona específica"))

        # 3. Validador SAT
        checks.append(await self._check_sat_validador(rfc))

        # 4. Lista 69-B (EFOS) — crítico AML
        checks.append(await self._check_lista_69b(rfc))

        # 5. Lista 69 (no localizados)
        checks.append(await self._check_lista_69(rfc))

        # 6. Análisis de fraude visual
        checks.extend(await self._run_fraud_analysis(file_path, "rfc", extracted_data, preloaded_qr_codes))

        return checks

    # ── checks internos ───────────────────────────────────────────────────────

    def _check_formato(self, rfc: str) -> CheckItem:
        if not rfc:
            return self._failed("formato_rfc", "No se encontró RFC en el documento")
        if rfc in _RFC_GENERICOS:
            return self._warning("formato_rfc", f"RFC genérico: {rfc}")
        if _RFC_PF_RE.match(rfc):
            return self._passed("formato_rfc", f"RFC válido (Persona Física, 13 chars): {rfc}")
        if _RFC_PM_RE.match(rfc):
            return self._passed("formato_rfc", f"RFC válido (Persona Moral, 12 chars): {rfc}")
        return self._failed("formato_rfc", f"Formato RFC inválido: {rfc!r} (se esperan 12 o 13 caracteres con estructura XXXXDDDDDDAAA)")

    async def _check_sat_validador(self, rfc: str) -> CheckItem:
        """Consulta el validador masivo del SAT."""
        try:
            async with httpx.AsyncClient(timeout=SCRAPER_TIMEOUT, follow_redirects=True) as client:
                # Endpoint público del SAT para validación de RFC
                resp = await client.post(
                    "https://agsc.siat.sat.gob.mx/PTSC/ValidaRFC/app?execution=e1s1",
                    data={"rfc": rfc, "submit": "Buscar"},
                    headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/x-www-form-urlencoded"},
                )
                text_lower = resp.text.lower()

                if "no existe" in text_lower or "no se encontró" in text_lower or "invalid" in text_lower:
                    return self._failed("sat_validador", f"RFC {rfc} NO encontrado en el padrón del SAT")
                if "activo" in text_lower or "localizado" in text_lower or rfc.lower() in text_lower:
                    return self._passed("sat_validador", f"RFC {rfc} encontrado y activo en el SAT")
                return self._warning("sat_validador", f"Respuesta del SAT no concluyente para RFC {rfc} — verificar manualmente en sat.gob.mx")

        except httpx.TimeoutException:
            return self._skipped("sat_validador", "Timeout al consultar el SAT — verificar manualmente en sat.gob.mx")
        except Exception as e:
            logger.warning(f"Error consultando SAT: {e}")
            return self._skipped("sat_validador", f"Error al consultar validador SAT: {str(e)[:80]}")

    async def _check_lista_69b(self, rfc: str) -> CheckItem:
        """
        Verifica si el RFC aparece en la lista 69-B del SAT (EFOS).
        EFOS = Empresas que Facturan Operaciones Simuladas — crítico AML.
        """
        try:
            async with httpx.AsyncClient(timeout=SCRAPER_TIMEOUT, follow_redirects=True) as client:
                resp = await client.get(
                    f"https://omawww.sat.gob.mx/cifras_sat/Documents/Lista_69B.csv",
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                if resp.status_code == 200:
                    if rfc in resp.text.upper():
                        return self._failed(
                            "rfc_lista_69b",
                            f"⚠️ RFC {rfc} ENCONTRADO en Lista SAT 69-B (EFOS): empresa que factura operaciones simuladas. Operación de alto riesgo AML.",
                        )
                    return self._passed("rfc_lista_69b", f"RFC {rfc} NO aparece en la Lista 69-B del SAT (EFOS)")
                return self._skipped("rfc_lista_69b", f"No se pudo descargar la Lista 69-B del SAT (HTTP {resp.status_code}) — verificar manualmente")
        except httpx.TimeoutException:
            return self._skipped("rfc_lista_69b", "Timeout al descargar Lista 69-B del SAT")
        except Exception as e:
            logger.warning(f"Error consultando lista 69-B: {e}")
            return self._skipped("rfc_lista_69b", f"Error al verificar Lista 69-B: {str(e)[:80]}")

    async def _check_lista_69(self, rfc: str) -> CheckItem:
        """Verifica si el RFC aparece en la lista 69 del SAT (no localizados)."""
        try:
            async with httpx.AsyncClient(timeout=SCRAPER_TIMEOUT, follow_redirects=True) as client:
                resp = await client.get(
                    "https://omawww.sat.gob.mx/cifras_sat/Documents/Lista_69.csv",
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                if resp.status_code == 200:
                    if rfc in resp.text.upper():
                        return self._failed(
                            "rfc_lista_69",
                            f"RFC {rfc} en Lista SAT 69 (contribuyente no localizado) — SAT no puede ubicar al contribuyente",
                        )
                    return self._passed("rfc_lista_69", f"RFC {rfc} NO aparece en Lista 69 del SAT (no localizados)")
                return self._skipped("rfc_lista_69", f"No se pudo descargar Lista 69 del SAT (HTTP {resp.status_code})")
        except Exception as e:
            return self._skipped("rfc_lista_69", f"Error al verificar Lista 69: {str(e)[:80]}")
