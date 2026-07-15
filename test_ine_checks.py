"""
Test de regresión: detección de INE falsificada mediante checks deterministas.

Caso real (2026-07-14): una INE fabricada con CURP de 20 caracteres y dígitos
verificadores MRZ inválidos fue marcada VERIFIED. Estos tests garantizan que
los checks deterministas la marquen INVALID con banderas de fraude.

Uso: python test_ine_checks.py  (sin red, sin API keys)
"""

import asyncio
import sys

from models.verification_schemas import CheckItem, CheckStatus, VerificationStatus
from services.data_extractor import parse_mrz
from services.verifiers.ine_verifier import INEVerifier, _curp_check_digit
from services.conclusion_engine import (
    compute_confidence, determine_status, extract_fraud_flags, generate_conclusion,
)

# MRZ tal como aparece en el documento falsificado (dígitos verificadores no cuadran)
FAKE_MRZ_L1 = "IDMEX2259684084<<0313097179021"
FAKE_MRZ_L2 = "9611235H3412318MEX<01<<0319667"
FAKE_MRZ_L3 = "RODARTE<CASTANEDA<<SERGIO<<<<<"

FAKE_CURP_20 = "ROCASR961123HQTDSR08"  # 20 chars — imposible en un CURP real

FAKE_DATA = {
    "full_name": "RODARTE CASTAÑEDA SERGIO",
    "birth_date": "23/11/1996",
    "sex": "H",
    "voter_id": "RDCSSR96112322H400",
    "curp_invalid_raw": FAKE_CURP_20,
    "expiration_date": "2024-2034",
}

verifier = INEVerifier()
failures = []


def check(desc, cond):
    mark = "OK " if cond else "FALLO"
    print(f"[{mark}] {desc}")
    if not cond:
        failures.append(desc)


# ── 1. parse_mrz detecta los dígitos inválidos ────────────────────────────────
mrz = parse_mrz(f"{FAKE_MRZ_L1}\n{FAKE_MRZ_L2}\n{FAKE_MRZ_L3}")
check("parse_mrz reconoce las 3 líneas", mrz is not None)
check("dígito de fecha de nacimiento inválido detectado", mrz["dob_check_ok"] is False)
check("dígito de vencimiento válido (control negativo)", mrz["expiry_check_ok"] is True)
check("dígito de número de documento inválido detectado", mrz["doc_check_ok"] is False)
check("dígito compuesto inválido detectado", mrz["composite_check_ok"] is False)

# ── 2. mrz_integridad → FAILED con 2+ dígitos malos ──────────────────────────
item = verifier._check_mrz_integrity({"mrz": mrz})
check("mrz_integridad = FAILED con 3 dígitos inválidos", item.status == CheckStatus.FAILED)

# Con exactamente 1 dígito malo → WARNING (posible error de transcripción)
mrz_1fail = dict(mrz, doc_check_ok=True, composite_check_ok=True)
item = verifier._check_mrz_integrity({"mrz": mrz_1fail})
check("mrz_integridad = WARNING con solo 1 dígito inválido", item.status == CheckStatus.WARNING)

# ── 3. formato_curp → FAILED cuando visión leyó un CURP imposible ────────────
item = verifier._check_curp_format("", FAKE_CURP_20)
check("formato_curp = FAILED con CURP de 20 caracteres (visión)", item.status == CheckStatus.FAILED)

item = verifier._check_curp_format("", "")
check("formato_curp = SKIPPED sin CURP (sin regresión)", item.status == CheckStatus.SKIPPED)

# ── 4. curp_consistencia ─────────────────────────────────────────────────────
# CURP legítimo derivado de los datos del frente, con dígito verificador correcto
curp17 = "ROCS961123HQTDSR0"
curp_ok = curp17 + str(_curp_check_digit(curp17))
data_ok = dict(FAKE_DATA, curp=curp_ok)
data_ok.pop("curp_invalid_raw")
item = verifier._check_curp_consistency(data_ok)
check("curp_consistencia = PASSED con CURP coherente", item.status == CheckStatus.PASSED)

# Mismo CURP con el sexo alterado en el documento → FAILED
item = verifier._check_curp_consistency(dict(data_ok, sex="M"))
check("curp_consistencia = FAILED si el sexo no cuadra", item.status == CheckStatus.FAILED)

# Dígito verificador alterado → FAILED
bad_dv = curp17 + str((int(curp_ok[17]) + 1) % 10)
item = verifier._check_curp_consistency(dict(data_ok, curp=bad_dv))
check("curp_consistencia = FAILED con dígito verificador alterado", item.status == CheckStatus.FAILED)

# ── 5. Pipeline completo: el documento falso debe salir INVALID ──────────────
checks = [
    CheckItem(name="formato_clave_elector", status=CheckStatus.PASSED, detail="ok"),
    CheckItem(name="formato_curp", status=CheckStatus.FAILED,
              detail="CURP estructuralmente imposible: 20 caracteres"),
    CheckItem(name="curp_consistencia", status=CheckStatus.SKIPPED, detail="CURP de 18 no disponible"),
    CheckItem(name="cross_check_curp_nombre", status=CheckStatus.SKIPPED, detail="sin CURP"),
    CheckItem(name="vigencia", status=CheckStatus.PASSED, detail="ok"),
    CheckItem(name="padron_ine", status=CheckStatus.SKIPPED, detail="portal no disponible"),
    CheckItem(name="ambos_lados_ine", status=CheckStatus.PASSED, detail="ok"),
    CheckItem(name="mrz_integridad", status=CheckStatus.FAILED, detail="3 dígitos MRZ inválidos"),
    CheckItem(name="cross_check_fecha_nacimiento", status=CheckStatus.PASSED, detail="ok"),
    CheckItem(name="cross_check_nombre_mrz", status=CheckStatus.PASSED, detail="ok"),
    CheckItem(name="fraude_manipulacion_digital", status=CheckStatus.PASSED, detail="ok"),
    CheckItem(name="fraude_coherencia_tipografica", status=CheckStatus.PASSED, detail="ok"),
    CheckItem(name="fraude_elementos_seguridad", status=CheckStatus.WARNING, detail="holograma no visible"),
    CheckItem(name="fraude_foto_autenticidad", status=CheckStatus.PASSED, detail="ok"),
    CheckItem(name="fraude_ia_generativa", status=CheckStatus.PASSED, detail="ok"),
]

conf = compute_confidence(checks)
status = determine_status(conf, checks)
flags = extract_fraud_flags(checks)
flag_codes = {f.code for f in flags}

check(f"veredicto = INVALID (antes salía VERIFIED; confianza {conf:.2f})",
      status == VerificationStatus.INVALID)
check(f"confianza desplomada con check crítico fallido ({conf:.2f} ≤ 0.15, antes salía 0.91)",
      conf <= 0.15)
check("bandera CURP_MALFORMED presente", "CURP_MALFORMED" in flag_codes)
check("bandera MRZ_CHECK_DIGITS_INVALID presente", "MRZ_CHECK_DIGITS_INVALID" in flag_codes)

conclusion = generate_conclusion(status, checks, "ine", {"full_name": "RODARTE CASTAÑEDA SERGIO"})
check("la conclusión es una ALERTA DE FRAUDE", "ALERTA DE FRAUDE" in conclusion)
print(f"\nConclusión generada:\n  {conclusion}\n")

# ── 6. Sin regresión: una INE legítima sigue saliendo VERIFIED ───────────────
checks_ok = [
    CheckItem(name=c.name, status=CheckStatus.PASSED, detail="ok") if c.status == CheckStatus.FAILED
    else c
    for c in checks
]
conf_ok = compute_confidence(checks_ok)
status_ok = determine_status(conf_ok, checks_ok)
check(f"INE legítima sigue VERIFIED (confianza {conf_ok:.2f})",
      status_ok == VerificationStatus.VERIFIED)

print()
if failures:
    print(f"❌ {len(failures)} test(s) fallaron:")
    for f in failures:
        print(f"   - {f}")
    sys.exit(1)
print("✅ Todos los tests pasaron")
