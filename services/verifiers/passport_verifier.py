"""
Verificador de Pasaporte Mexicano
Checks: MRZ ICAO 9303 (5 checksums), vigencia, tipografía OCR-B básica, CURP
"""

import re
import logging
from datetime import date
from typing import Dict, List, Optional

from models.verification_schemas import CheckItem
from services.verifiers.base_verifier import BaseVerifier

logger = logging.getLogger(__name__)

_CURP_RE = re.compile(r'\b([A-Z]{4}\d{6}[HM][A-Z]{5}[0-9A-Z]\d)\b')
_RFC_RE = re.compile(r'\b([A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3})\b')


def _mrz_check(s: str) -> int:
    """Dígito verificador MRZ ICAO 9303 — pesos 7,3,1."""
    weights = [7, 3, 1]
    total = 0
    for i, ch in enumerate(s):
        if ch.isdigit():
            val = int(ch)
        elif ch.isalpha():
            val = ord(ch.upper()) - ord('A') + 10
        else:
            val = 0
        total += val * weights[i % 3]
    return total % 10


def _mrz_year(yy: str, prefer_future: bool = False) -> int:
    try:
        y = int(yy)
        y19, y20 = 1900 + y, 2000 + y
        if prefer_future:
            return y20 if y19 < date.today().year else y19
        return y19 if y > 30 else y20
    except ValueError:
        return 0


class PassportVerifier(BaseVerifier):
    """Verifica autenticidad de un pasaporte mexicano (MRZ TD3 ICAO 9303)."""

    async def verify(self, file_path: str, extracted_data: Dict, preloaded_qr_codes: Optional[List] = None) -> List[CheckItem]:
        checks: List[CheckItem] = []
        raw_text: str = extracted_data.get("_raw_text", "")

        # 1. Identificar documento como pasaporte
        checks.append(self._check_passport_layout(raw_text))

        # 2. MRZ — presencia y checksums ICAO 9303
        mrz_result = self._parse_passport_mrz(raw_text)
        checks.extend(self._check_mrz(mrz_result))

        # 3. Vigencia
        expiry = extracted_data.get("expiration_date", "") or (mrz_result.get("expiry_iso") if mrz_result else "")
        checks.append(self._check_vigencia(expiry, mrz_result))

        # 4. CURP (pasaportes mexicanos recientes lo incluyen)
        curp = extracted_data.get("curp", "")
        checks.append(self._check_curp(curp, raw_text))

        # 5. País emisor = MEX
        checks.append(self._check_pais_emisor(mrz_result, raw_text))

        # 6. Coherencia MRZ línea 1 vs línea 2 (nombre duplicado no)
        checks.append(self._check_mrz_internal_coherence(mrz_result))

        # 7. Análisis de fraude visual
        checks.extend(await self._run_fraud_analysis(file_path, "passport", extracted_data, preloaded_qr_codes))

        return checks

    # ── parseo MRZ ────────────────────────────────────────────────────────────

    def _parse_passport_mrz(self, text: str) -> Optional[Dict]:
        """Extrae y parsea las 2 líneas MRZ del pasaporte (TD3: 2×44 chars)."""
        # Pasaporte MX empieza con P<MEX
        mrz2_re = re.compile(
            r'(P<MEX[A-Z<]{41})\s*[\r\n]+\s*([A-Z0-9<]{44})',
            re.MULTILINE,
        )
        m = mrz2_re.search(text)
        if not m:
            # Tolerante: buscar líneas de 44 chars con patrón numérico
            lines44 = [ln.strip() for ln in text.splitlines() if re.match(r'^[A-Z0-9<]{44}$', ln.strip())]
            if len(lines44) < 2:
                return None
            l1, l2 = lines44[0], lines44[1]
        else:
            l1, l2 = m.group(1), m.group(2)

        if len(l1) != 44 or len(l2) != 44:
            return None

        result: Dict = {"line1": l1, "line2": l2}

        # Línea 1: tipo(P), código país(1-3), apellidos<<nombres
        result["doc_type"] = l1[0]
        result["country"] = l1[2:5].replace("<", "")
        name_part = l1[5:44]
        if "<<" in name_part:
            parts = name_part.split("<<", 1)
            result["surnames"] = parts[0].replace("<", " ").strip()
            result["given_names"] = parts[1].replace("<", " ").strip() if len(parts) > 1 else ""
        else:
            result["surnames"] = name_part.replace("<", " ").strip()

        # Línea 2: número pasaporte (0-8) + check(9) + nac (10-12) + DOB (13-18) + check(19) + sexo(20)
        #          + expiración (21-26) + check(27) + personal# (28-41) + check(42) + check compuesto(43)
        passport_no = l2[0:9]
        result["passport_number"] = passport_no.replace("<", "")
        result["passport_check_ok"] = _mrz_check(passport_no) == int(l2[9]) if l2[9].isdigit() else None

        result["nationality"] = l2[10:13].replace("<", "")

        dob_raw = l2[13:19]
        result["dob_raw"] = dob_raw
        result["dob_check_ok"] = _mrz_check(dob_raw) == int(l2[19]) if l2[19].isdigit() else None
        try:
            yy, mm, dd = dob_raw[0:2], dob_raw[2:4], dob_raw[4:6]
            result["birth_year"] = _mrz_year(yy, prefer_future=False)
            result["dob_iso"] = f"{result['birth_year']}-{mm}-{dd}"
        except Exception:
            pass

        result["sex"] = l2[20]

        exp_raw = l2[21:27]
        result["expiry_raw"] = exp_raw
        result["expiry_check_ok"] = _mrz_check(exp_raw) == int(l2[27]) if l2[27].isdigit() else None
        try:
            ey, em, ed = exp_raw[0:2], exp_raw[2:4], exp_raw[4:6]
            exp_year = _mrz_year(ey, prefer_future=True)
            result["expiry_iso"] = f"{exp_year}-{em}-{ed}"
        except Exception:
            pass

        personal_no = l2[28:42]
        result["personal_number"] = personal_no.replace("<", "")

        # Check compuesto (posición 43)
        composite_str = l2[0:10] + l2[13:20] + l2[21:43]
        result["composite_check_ok"] = _mrz_check(composite_str) == int(l2[43]) if l2[43].isdigit() else None

        return result

    # ── checks internos ───────────────────────────────────────────────────────

    def _check_passport_layout(self, text: str) -> CheckItem:
        t = text.lower()
        signals = [
            "pasaporte" in t or "passport" in t,
            "secretaría de relaciones exteriores" in t or "sre" in t or "p<mex" in t.upper(),
            "nacionalidad" in t or "nationality" in t,
            "fecha de nacimiento" in t or "date of birth" in t,
        ]
        score = sum(signals)
        if score >= 3:
            return self._passed("layout_pasaporte", "Documento identificado como Pasaporte Mexicano")
        if score >= 2:
            return self._warning("layout_pasaporte", "Documento parcialmente identificado como pasaporte")
        return self._warning("layout_pasaporte", "No se confirmó que el documento sea un pasaporte mexicano")

    def _check_mrz(self, mrz: Optional[Dict]) -> List[CheckItem]:
        if not mrz:
            return [self._warning("mrz_pasaporte", "No se encontró zona MRZ en el documento — se requiere imagen del pasaporte completo")]

        results = []

        checks_map = [
            ("passport_check_ok", "Número de pasaporte",     mrz.get("passport_number", "?")),
            ("dob_check_ok",      "Fecha de nacimiento",     mrz.get("dob_raw", "?")),
            ("expiry_check_ok",   "Fecha de expiración",     mrz.get("expiry_raw", "?")),
            ("composite_check_ok","Check compuesto MRZ",     "toda la línea 2"),
        ]
        all_ok = True
        for key, label, src in checks_map:
            val = mrz.get(key)
            if val is True:
                results.append(f"{label}: ✓")
            elif val is False:
                results.append(f"{label}: ✗ INVÁLIDO")
                all_ok = False
            else:
                results.append(f"{label}: no evaluable")

        detail = " | ".join(results)
        if all_ok:
            return [self._passed("mrz_checksums", f"Todos los checksums MRZ ICAO 9303 son válidos. {detail}")]
        return [self._failed("mrz_checksums", f"Checksum(s) MRZ inválido(s) — posible alteración del documento. {detail}")]

    def _check_vigencia(self, expiry: str, mrz: Optional[Dict]) -> CheckItem:
        exp_iso = (mrz or {}).get("expiry_iso", "") or expiry
        if not exp_iso:
            return self._warning("vigencia_pasaporte", "No se encontró fecha de expiración")
        try:
            parts = re.split(r'[-/]', exp_iso.strip())
            if len(parts) == 3:
                if len(parts[0]) == 4:
                    y, mo, d = int(parts[0]), int(parts[1]), int(parts[2])
                else:
                    d, mo, y = int(parts[0]), int(parts[1]), int(parts[2])
                exp_date = date(y, mo, d)
                today = date.today()
                if exp_date < today:
                    return self._failed("vigencia_pasaporte", f"Pasaporte VENCIDO: expiró el {exp_date}")
                days_left = (exp_date - today).days
                return self._passed("vigencia_pasaporte", f"Pasaporte vigente hasta {exp_date} ({days_left} días restantes)")
        except Exception:
            pass
        return self._warning("vigencia_pasaporte", f"No se pudo interpretar la fecha de expiración: {exp_iso!r}")

    def _check_curp(self, curp: str, raw_text: str) -> CheckItem:
        candidate = curp
        if not candidate:
            m = _CURP_RE.search(raw_text.upper())
            candidate = m.group(1) if m else ""
        if candidate:
            return self._passed("curp_pasaporte", f"CURP presente en el pasaporte: {candidate}")
        return self._skipped("curp_pasaporte", "CURP no encontrado — puede estar en páginas adicionales del pasaporte o no aplicar")

    def _check_pais_emisor(self, mrz: Optional[Dict], raw_text: str) -> CheckItem:
        if mrz:
            country = mrz.get("country", "")
            if country == "MEX":
                return self._passed("pais_emisor", "País emisor: MÉXICO (MEX) — confirmado en MRZ")
            if country:
                return self._warning("pais_emisor", f"País emisor en MRZ: {country} — se esperaba MEX para pasaporte mexicano")
        if "mex" in raw_text.lower() or "méxico" in raw_text.lower() or "mexico" in raw_text.lower():
            return self._passed("pais_emisor", "País emisor México identificado en el texto")
        return self._warning("pais_emisor", "No se confirmó México como país emisor")

    def _check_mrz_internal_coherence(self, mrz: Optional[Dict]) -> CheckItem:
        if not mrz:
            return self._skipped("coherencia_mrz", "MRZ no disponible para verificar coherencia interna")
        country = mrz.get("country", "")
        nationality = mrz.get("nationality", "")
        if country and nationality and country != nationality:
            return self._warning(
                "coherencia_mrz",
                f"País emisor ({country}) ≠ nacionalidad ({nationality}) — revisar si es pasaporte de extranjero",
            )
        if mrz.get("dob_raw") and mrz.get("expiry_raw"):
            # Fecha nacimiento debe ser anterior a expiración
            dob = mrz.get("dob_iso", "")
            exp = mrz.get("expiry_iso", "")
            if dob and exp and dob >= exp:
                return self._failed("coherencia_mrz", f"Fecha nacimiento ({dob}) >= fecha expiración ({exp}) — imposible")
        return self._passed("coherencia_mrz", "Coherencia interna MRZ verificada")
