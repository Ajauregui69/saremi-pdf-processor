"""
Motor de conclusión: agrega checks → confidence → veredicto final + texto legible + fraud flags
"""

import logging
from typing import List, Dict, Any
from models.verification_schemas import (
    CheckItem, CheckStatus, VerificationStatus, FraudFlag, FraudFlagSeverity,
)

logger = logging.getLogger(__name__)

# Pesos por status de check
_WEIGHTS = {
    CheckStatus.PASSED: 1.0,
    CheckStatus.WARNING: 0.4,
    CheckStatus.FAILED: -0.8,
    CheckStatus.SKIPPED: 0.0,
}

# Checks que, si fallan, fuerzan el estado a INVALID sin importar el score.
# Los checks deterministas (dígitos verificadores, estructura) solo emiten FAILED
# cuando la evidencia es matemática, así que su fallo es veto directo.
_CRITICAL_CHECKS = {
    "vigencia",
    # INE: validaciones deterministas (ICAO 9303 / RENAPO)
    "mrz_integridad",
    "formato_curp",
    "curp_consistencia",
    "cfdi_timbrado",
    "fraude_manipulacion_digital",
    "fraude_integridad_visual",
    "fraude_ia_generativa",
    "qr_verificacion_ine",
    "qr_verificacion_curp",
    "qr_validez_ine",
    # SPEI
    "cep_banxico",
    # RFC listas negras SAT
    "rfc_lista_69b",
    # CLABE inválida es crítico porque indica SPEI falso
    "clabe_origen",
    "clabe_destino",
}

# Mapeo check_name → (FraudFlag.code, FraudFlagSeverity, descripción)
_FRAUD_FLAG_MAP: Dict[str, tuple] = {
    # Análisis visual Claude Vision
    "fraude_manipulacion_digital":    ("DIGITAL_MANIPULATION",    FraudFlagSeverity.CRITICAL, "Manipulación digital detectada: parches, edición de campos o splicing de imagen"),
    "fraude_integridad_visual":        ("VISUAL_INTEGRITY_FAILURE", FraudFlagSeverity.CRITICAL, "Integridad visual comprometida: cortes, zonas incoherentes o elementos fuera de lugar"),
    "fraude_coherencia_tipografica":  ("TYPOGRAPHY_INCONSISTENCY", FraudFlagSeverity.HIGH,     "Tipografía inconsistente: mezcla de fuentes que sugiere alteración de campos"),
    "fraude_elementos_seguridad":     ("SECURITY_ELEMENTS_ABSENT", FraudFlagSeverity.HIGH,     "Elementos de seguridad ausentes o alterados (hologramas, sellos, guilloqué)"),
    "fraude_foto_autenticidad":       ("PHOTO_SUBSTITUTION",       FraudFlagSeverity.CRITICAL, "Posible sustitución de fotografía en documento de identidad"),
    "fraude_logotipo_banco":          ("BANK_LOGO_ALTERED",        FraudFlagSeverity.HIGH,     "Logo o membrete bancario posiblemente alterado o sustituido"),
    "fraude_sellos_y_firmas":         ("SEALS_SIGNATURES_ALTERED", FraudFlagSeverity.HIGH,     "Sellos o firmas con indicios de inserción o modificación digital"),
    "fraude_sello_oficial":           ("OFFICIAL_SEAL_ALTERED",    FraudFlagSeverity.HIGH,     "Sello oficial gubernamental con indicios de alteración"),
    "fraude_ia_generativa":           ("AI_GENERATED_DOCUMENT",    FraudFlagSeverity.CRITICAL, "Documento posiblemente generado por inteligencia artificial"),
    # INE: validaciones deterministas
    "mrz_integridad":                 ("MRZ_CHECK_DIGITS_INVALID", FraudFlagSeverity.CRITICAL, "Dígitos verificadores de la MRZ inválidos (ICAO 9303) — zona de lectura mecánica fabricada o manipulada"),
    "formato_curp":                   ("CURP_MALFORMED",           FraudFlagSeverity.CRITICAL, "CURP estructuralmente imposible — un CURP real siempre tiene 18 caracteres con estructura fija"),
    "curp_consistencia":              ("CURP_INCONSISTENT",        FraudFlagSeverity.CRITICAL, "CURP inconsistente con los datos del propio documento (dígito verificador, fecha, sexo o entidad)"),
    # QR
    "qr_verificacion_ine":            ("QR_INE_INVALID",           FraudFlagSeverity.CRITICAL, "QR de INE marcado como inválido por el portal oficial del INE"),
    "qr_validez_ine":                 ("QR_INE_PORTAL_REJECTED",   FraudFlagSeverity.CRITICAL, "El portal del INE indica que la credencial no es válida"),
    "qr_verificacion_curp":           ("QR_CURP_MISMATCH",         FraudFlagSeverity.CRITICAL, "CURP del QR no coincide con el CURP del documento"),
    "qr_crosscheck_curp":             ("QR_CURP_MISMATCH",         FraudFlagSeverity.CRITICAL, "CURP del QR no coincide con el CURP del documento"),
    # SPEI / Banxico
    "cep_banxico":                    ("SPEI_NOT_FOUND_CEP",        FraudFlagSeverity.CRITICAL, "Clave de rastreo SPEI no encontrada en CEP Banxico — SPEI posiblemente falso"),
    "clabe_origen":                   ("CLABE_INVALID",             FraudFlagSeverity.CRITICAL, "CLABE de origen con dígito verificador inválido — transferencia posiblemente fabricada"),
    "clabe_destino":                  ("CLABE_INVALID",             FraudFlagSeverity.CRITICAL, "CLABE de destino con dígito verificador inválido — transferencia posiblemente fabricada"),
    # RFC / SAT
    "rfc_lista_69b":                  ("RFC_BLACKLISTED_SAT_69B",   FraudFlagSeverity.CRITICAL, "RFC en lista SAT 69-B (EFOS): emisor de facturas apócrifas — operación de alto riesgo AML"),
    "rfc_lista_69":                   ("RFC_NOT_LOCATED_SAT",       FraudFlagSeverity.HIGH,     "RFC en lista SAT 69: contribuyente no localizado"),
    "rfc_estado_padron":              ("RFC_CANCELLED_OR_SUSPENDED", FraudFlagSeverity.CRITICAL, "RFC cancelado o suspendido ante el SAT"),
    # Documentos inmobiliarios
    "folio_real_rpp":                 ("FOLIO_REAL_NOT_FOUND",      FraudFlagSeverity.CRITICAL, "Folio Real no encontrado en RPP — posible escritura sin inscripción registral"),
    # Vigencia
    "vigencia":                       ("DOCUMENT_EXPIRED",          FraudFlagSeverity.CRITICAL, "Documento vencido — no puede usarse como identificación válida"),
    "vigencia_csf":                   ("CSF_EXPIRED",               FraudFlagSeverity.CRITICAL, "CSF con más de 90 días de antigüedad — no cumple requisito notarial"),
    "anio_fiscal_predial":            ("PREDIAL_OUTDATED",          FraudFlagSeverity.HIGH,     "Boleta predial de año anterior — se requiere predial del año en curso"),
    "estado_pago_predial":            ("PREDIAL_UNPAID",            FraudFlagSeverity.HIGH,     "Adeudo en predial — no se puede escriturar con predial adeudado"),
    # Estructura
    "cfdi_timbrado":                  ("CFDI_NOT_STAMPED",          FraudFlagSeverity.CRITICAL, "Documento no timbrado por el SAT — no es un CFDI válido en México"),
    # Fecha SPEI
    "fecha_spei":                     ("SPEI_FUTURE_DATE",          FraudFlagSeverity.CRITICAL, "Fecha futura en comprobante SPEI — indicador directo de falsificación"),
}


def compute_confidence(checks: List[CheckItem]) -> float:
    scored = [c for c in checks if c.status != CheckStatus.SKIPPED]
    if not scored:
        return 0.0
    max_possible = len(scored) * 1.0
    actual = sum(_WEIGHTS[c.status] for c in scored)
    score = (actual + max_possible) / (2 * max_possible)
    score = max(0.0, min(1.0, score))

    # Un check crítico fallido invalida el documento sin importar el promedio:
    # la confianza reportada debe reflejar el veredicto. Sin este tope, un
    # documento fraudulento salía "INVALID con confianza 0.91" porque los demás
    # checks (visuales, formato) sí pasaban.
    failed_critical = any(
        c.status == CheckStatus.FAILED and c.name in _CRITICAL_CHECKS
        for c in checks
    )
    if failed_critical:
        return min(score, 0.15)
    return score


def determine_status(confidence: float, checks: List[CheckItem]) -> VerificationStatus:
    failed_critical = [
        c for c in checks
        if c.status == CheckStatus.FAILED and c.name in _CRITICAL_CHECKS
    ]
    if failed_critical:
        return VerificationStatus.INVALID

    if confidence >= 0.75:
        return VerificationStatus.VERIFIED
    elif confidence >= 0.45:
        return VerificationStatus.INCONCLUSIVE
    else:
        return VerificationStatus.MANUAL_REVIEW


def extract_fraud_flags(checks: List[CheckItem]) -> List[FraudFlag]:
    """
    Convierte checks FAILED en FraudFlag estructurados.
    Solo checks con nombre en _FRAUD_FLAG_MAP y status FAILED generan flags.
    """
    flags: List[FraudFlag] = []
    seen_codes = set()

    for check in checks:
        if check.status != CheckStatus.FAILED:
            continue
        if check.name not in _FRAUD_FLAG_MAP:
            continue

        code, severity, base_desc = _FRAUD_FLAG_MAP[check.name]

        # Evitar flags duplicados con el mismo código
        if code in seen_codes:
            continue
        seen_codes.add(code)

        flags.append(FraudFlag(
            code=code,
            severity=severity,
            description=f"{base_desc}. Detalle: {check.detail}",
            source_check=check.name,
        ))

    # Ordenar: CRITICAL primero, luego HIGH, luego MEDIUM
    order = {FraudFlagSeverity.CRITICAL: 0, FraudFlagSeverity.HIGH: 1, FraudFlagSeverity.MEDIUM: 2}
    flags.sort(key=lambda f: order.get(f.severity, 3))
    return flags


def generate_conclusion(
    status: VerificationStatus,
    checks: List[CheckItem],
    doc_type: str,
    extracted_data: Dict[str, Any],
) -> str:
    name = (
        extracted_data.get("full_name")
        or extracted_data.get("employee_name")
        or extracted_data.get("account_holder")
        or "el titular"
    )
    doc_labels = {
        "ine": "INE / Credencial para votar",
        "curp": "CURP",
        "csf": "Constancia de Situación Fiscal",
        "rfc": "RFC",
        "cfdi": "CFDI / Factura electrónica",
        "bank_statement": "Estado de cuenta bancario",
        "bank_statement_aml": "Estado de cuenta (AML)",
        "proof_of_address": "Comprobante de domicilio",
        "payroll": "Recibo de nómina",
        "income_proof": "Comprobante de ingresos",
        "employment_letter": "Carta laboral",
        "tax_return": "Declaración fiscal",
        "spei": "Comprobante SPEI",
        "escritura": "Escritura Pública",
        "predial": "Boleta Predial",
        "passport": "Pasaporte",
        "passport_mx": "Pasaporte Mexicano",
        "passport_ext": "Pasaporte Extranjero",
        "acta_nacimiento": "Acta de Nacimiento",
        "acta_matrimonio": "Acta de Matrimonio",
        "acta_defuncion": "Acta de Defunción",
        "licencia": "Licencia de Conducir",
        "fm_residencia": "Tarjeta de Residencia / FM",
        "cedula_profesional": "Cédula Profesional",
        "cert_libertad_gravamen": "Certificado de Libertad de Gravamen",
        "avaluo": "Avalúo",
        "carta_no_adeudo": "Carta de No Adeudo",
        "document": "Documento",
    }
    doc_label = doc_labels.get(doc_type, doc_type)

    passed = [c for c in checks if c.status == CheckStatus.PASSED]
    failed = [c for c in checks if c.status == CheckStatus.FAILED]
    warnings = [c for c in checks if c.status == CheckStatus.WARNING]
    fraud_flags = extract_fraud_flags(checks)

    if status == VerificationStatus.VERIFIED:
        base = f"El {doc_label} presentado para {name} ha sido VERIFICADO exitosamente."
        if passed:
            base += f" Se superaron {len(passed)} verificación(es)."
        # Transparencia: nunca ocultar checks fallidos aunque el veredicto sea VERIFIED.
        if failed:
            reasons = "; ".join(c.detail for c in failed[:3])
            base += f" ATENCIÓN: {len(failed)} verificación(es) fallida(s) que requieren revisión: {reasons}"
    elif status == VerificationStatus.INVALID:
        if fraud_flags:
            critical = [f for f in fraud_flags if f.severity == FraudFlagSeverity.CRITICAL]
            # Priorizar el flag de IA/generación digital en el resumen — es el hallazgo
            # más relevante para el usuario.
            critical.sort(key=lambda f: 0 if f.code == "AI_GENERATED_DOCUMENT" else 1)
            flag_summary = "; ".join(f.description.split(".")[0] for f in critical[:2])
            base = f"⚠️ ALERTA DE FRAUDE en {doc_label}: {flag_summary}."
        else:
            reasons = "; ".join(c.detail for c in failed[:3])
            base = f"El {doc_label} fue marcado como INVÁLIDO. Razón(es): {reasons}."
    elif status == VerificationStatus.INCONCLUSIVE:
        base = f"La verificación del {doc_label} para {name} es INCONCLUSA."
        if failed:
            base += f" Se detectaron {len(failed)} problema(s) que requieren revisión."
    else:
        base = f"El {doc_label} requiere REVISIÓN MANUAL. No se pudo confirmar autenticidad automáticamente."

    # No agregar advertencias cuando ya hay alerta de fraude: el veredicto crítico
    # manda y las advertencias menores solo ensucian el mensaje.
    if warnings and not (status == VerificationStatus.INVALID and fraud_flags):
        base += f" Advertencias: {'; '.join(c.detail for c in warnings[:3])}."

    return base
