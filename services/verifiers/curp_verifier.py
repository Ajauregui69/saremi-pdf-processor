"""
Verificador de CURP
Checks: formato, entidad, consulta RENAPO scraper, cross-check nombre
"""

import re
import logging
import os
from typing import Dict, List

import httpx
from bs4 import BeautifulSoup

from models.verification_schemas import CheckItem
from services.verifiers.base_verifier import BaseVerifier

logger = logging.getLogger(__name__)

SCRAPER_TIMEOUT = int(os.getenv("SCRAPER_TIMEOUT_SECONDS", "15"))
RENAPO_URL = "https://consultas.curp.gob.mx/CurpSP/gobmx/inicio.jsp"

_CURP_RE = re.compile(r"^[A-Z]{4}\d{6}[HM][A-Z]{5}[0-9A-Z]\d$")

_ENTIDADES_CURP = {
    "AS", "BC", "BS", "CC", "CL", "CM", "CS", "CH", "DF", "DG",
    "GT", "GR", "HG", "JC", "MC", "MN", "MS", "NT", "NL", "OC",
    "PL", "QT", "QR", "SP", "SL", "SR", "TC", "TS", "TL", "VZ",
    "YN", "ZS", "NE",
}


def _levenshtein(s1: str, s2: str) -> int:
    """Distancia de edición simple entre dos strings."""
    if len(s1) < len(s2):
        s1, s2 = s2, s1
    row = list(range(len(s2) + 1))
    for c1 in s1:
        new_row = [row[0] + 1]
        for j, c2 in enumerate(s2):
            new_row.append(min(new_row[j] + 1, row[j + 1] + 1, row[j] + (c1 != c2)))
        row = new_row
    return row[-1]


class CURPVerifier(BaseVerifier):
    """Verifica la validez de un CURP, opcionalmente contra RENAPO."""

    async def verify(self, file_path: str, extracted_data: Dict) -> List[CheckItem]:
        checks: List[CheckItem] = []

        curp: str = extracted_data.get("curp", "").replace(" ", "").upper()
        full_name: str = extracted_data.get("full_name", "")

        # 1. Formato regex
        checks.append(self._check_format(curp))

        # 2. Entidad federativa
        if curp and len(curp) >= 13:
            checks.append(self._check_estado(curp))
        else:
            checks.append(self._skipped("entidad_federativa", "CURP incompleto para validar entidad"))

        # 3. Scraper RENAPO
        if curp and _CURP_RE.match(curp):
            renapo_check, renapo_name = await self._query_renapo(curp)
            checks.append(renapo_check)

            # 4. Cross-check nombre si RENAPO devolvió datos
            if renapo_name and full_name:
                checks.append(self._check_name_match(full_name, renapo_name))
            else:
                checks.append(self._skipped("cross_check_nombre_renapo", "Nombre de RENAPO o del documento no disponible"))
        else:
            checks.append(self._skipped("consulta_renapo", "CURP con formato inválido, omitiendo consulta RENAPO"))
            checks.append(self._skipped("cross_check_nombre_renapo", "No se consultó RENAPO"))

        # 5. Análisis de fraude visual + verificación de QR
        checks.extend(await self._run_fraud_analysis(file_path, "curp", extracted_data))

        return checks

    # ── checks internos ───────────────────────────────────────────────────────

    def _check_format(self, curp: str) -> CheckItem:
        if not curp:
            return self._failed("formato_curp_documento", "No se proporcionó CURP")
        if _CURP_RE.match(curp):
            return self._passed("formato_curp_documento", f"Formato CURP válido: {curp}")
        return self._failed("formato_curp_documento", f"Formato CURP inválido: {curp!r}")

    def _check_estado(self, curp: str) -> CheckItem:
        entidad = curp[11:13]
        if entidad in _ENTIDADES_CURP:
            return self._passed("entidad_federativa", f"Entidad federativa válida: {entidad}")
        return self._warning("entidad_federativa", f"Código de entidad desconocido en CURP: {entidad!r}")

    async def _query_renapo(self, curp: str):
        """
        Intenta consultar el portal de RENAPO para verificar el CURP.
        Retorna (CheckItem, nombre_encontrado_o_None).
        """
        try:
            async with httpx.AsyncClient(timeout=SCRAPER_TIMEOUT, follow_redirects=True) as client:
                headers = {
                    "User-Agent": "Mozilla/5.0 (compatible; DocVerifyBot/1.0)",
                    "Accept": "text/html,application/xhtml+xml",
                }
                resp = await client.get(
                    f"https://consultas.curp.gob.mx/CurpSP/gobmx/resultado.jsp?curp={curp}",
                    headers=headers,
                )
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "lxml")
                text_lower = soup.get_text().lower()

                if "no se encontró" in text_lower or "no existe" in text_lower or "curp no registrada" in text_lower:
                    return self._failed("consulta_renapo", "CURP NO encontrado en el registro de RENAPO"), None

                # Intentar extraer nombre
                nombre_encontrado = None
                for tag in soup.find_all(["td", "span", "p"]):
                    t = tag.get_text(strip=True)
                    if len(t) > 8 and all(c.isalpha() or c.isspace() for c in t) and t.isupper():
                        nombre_encontrado = t
                        break

                if "registrada" in text_lower or "encontrada" in text_lower or nombre_encontrado:
                    return self._passed("consulta_renapo", f"CURP registrado en RENAPO: {curp}"), nombre_encontrado

                return self._warning("consulta_renapo", "Respuesta de RENAPO no concluyente"), None

        except httpx.TimeoutException:
            logger.warning("Timeout consultando RENAPO")
            return self._skipped("consulta_renapo", "Timeout al consultar RENAPO (servicio no disponible)"), None
        except Exception as e:
            logger.warning(f"Error consultando RENAPO: {e}")
            return self._skipped("consulta_renapo", f"Error al consultar RENAPO: {str(e)[:100]}"), None

    def _check_name_match(self, doc_name: str, renapo_name: str) -> CheckItem:
        dist = _levenshtein(doc_name.upper().strip(), renapo_name.upper().strip())
        if dist <= 2:
            return self._passed("cross_check_nombre_renapo", f"Nombre coincide con RENAPO (distancia Levenshtein: {dist})")
        elif dist <= 5:
            return self._warning(
                "cross_check_nombre_renapo",
                f"Nombre con diferencia menor vs RENAPO (distancia: {dist}). Doc: {doc_name!r} / RENAPO: {renapo_name!r}",
            )
        return self._failed(
            "cross_check_nombre_renapo",
            f"Nombre NO coincide con RENAPO (distancia: {dist}). Doc: {doc_name!r} / RENAPO: {renapo_name!r}",
        )
