"""
Servicio de extracción de datos estructurados
Extrae información específica según el tipo de documento
"""

import re
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def extract_financial_data(text: str, document_type: str) -> Dict:
    """
    Extrae datos financieros estructurados según el tipo de documento

    Args:
        text: Texto del documento
        document_type: Tipo de documento

    Returns:
        Diccionario con datos extraídos
    """
    logger.info(f"📊 Extrayendo datos de {document_type}")

    if document_type == "bank_statement":
        return extract_bank_statement_data(text)
    elif document_type == "payroll":
        return extract_payroll_data(text)
    elif document_type == "id_document":
        return extract_id_document_data(text)
    elif document_type == "tax_return":
        return extract_tax_return_data(text)
    elif document_type == "proof_of_address":
        return extract_proof_of_address_data(text)
    elif document_type == "employment_letter":
        return extract_employment_letter_data(text)
    else:
        return {}


def extract_bank_statement_data(text: str) -> Dict:
    """Extrae datos de estado de cuenta bancario"""
    data = {}

    # Banco
    banks = ['BBVA', 'Santander', 'Banamex', 'Banorte', 'HSBC', 'Scotiabank', 'Inbursa']
    for bank in banks:
        if bank.lower() in text.lower():
            data['bank_name'] = bank
            break

    # Número de cuenta
    account_patterns = [
        r'cuenta[:\s]+(\d{10,})',
        r'account[:\s]+(\d{10,})',
        r'no\.?\s*de\s*cuenta[:\s]+(\d{10,})'
    ]
    for pattern in account_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            data['account_number'] = match.group(1)
            break

    # Saldo actual
    balance_patterns = [
        r'saldo\s+actual[:\s]+\$?\s*([\d,]+\.?\d*)',
        r'balance[:\s]+\$?\s*([\d,]+\.?\d*)',
        r'saldo\s+final[:\s]+\$?\s*([\d,]+\.?\d*)'
    ]
    for pattern in balance_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            amount_str = match.group(1).replace(',', '')
            data['balance'] = float(amount_str)
            break

    # Ingresos mensuales (suma de depósitos)
    deposits = re.findall(r'dep[oó]sito[:\s]+\$?\s*([\d,]+\.?\d*)', text, re.IGNORECASE)
    if deposits:
        total_deposits = sum(float(d.replace(',', '')) for d in deposits)
        data['monthly_income'] = total_deposits

    # Gastos mensuales (suma de retiros/cargos)
    withdrawals = re.findall(r'(?:retiro|cargo)[:\s]+\$?\s*([\d,]+\.?\d*)', text, re.IGNORECASE)
    if withdrawals:
        total_withdrawals = sum(float(w.replace(',', '')) for w in withdrawals)
        data['monthly_expenses'] = total_withdrawals

    # Calcular tasa de ahorro
    if 'monthly_income' in data and 'monthly_expenses' in data and data['monthly_income'] > 0:
        savings = data['monthly_income'] - data['monthly_expenses']
        data['savings_rate'] = (savings / data['monthly_income']) * 100

    # Nombre del titular
    name_patterns = [
        r'titular[:\s]+([A-ZÁÉÍÓÚÑ\s]+)',
        r'cliente[:\s]+([A-ZÁÉÍÓÚÑ\s]+)'
    ]
    for pattern in name_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            data['account_holder'] = match.group(1).strip()
            break

    logger.info(f"✅ Datos bancarios extraídos: {len(data)} campos")
    return data


def extract_payroll_data(text: str) -> Dict:
    """Extrae datos de nómina"""
    data = {}

    # RFC del empleado
    rfc_pattern = r'\b[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}\b'
    match = re.search(rfc_pattern, text)
    if match:
        data['employee_rfc'] = match.group(0)

    # Nombre del empleado
    name_patterns = [
        r'nombre[:\s]+([A-ZÁÉÍÓÚÑ\s]+?)(?:\n|rfc)',
        r'empleado[:\s]+([A-ZÁÉÍÓÚÑ\s]+?)(?:\n|rfc)'
    ]
    for pattern in name_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            data['employee_name'] = match.group(1).strip()
            break

    # Empresa
    company_patterns = [
        r'empresa[:\s]+([A-ZÁÉÍÓÚÑ\s\.]+?)(?:\n|$)',
        r'patr[oó]n[:\s]+([A-ZÁÉÍÓÚÑ\s\.]+?)(?:\n|$)'
    ]
    for pattern in company_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            data['employer_name'] = match.group(1).strip()
            break

    # Salario bruto - patrones más flexibles
    gross_patterns = [
        r'(?:salario|sueldo)\s+bruto[:\s]+\$?\s*([\d,]+\.?\d*)',
        r'percepciones\s+totales?[:\s]+\$?\s*([\d,]+\.?\d*)',
        r'total\s+percepciones[:\s]+\$?\s*([\d,]+\.?\d*)',
        r'ingreso\s+bruto[:\s]+\$?\s*([\d,]+\.?\d*)'
    ]
    for pattern in gross_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            amount_str = match.group(1).replace(',', '').replace(' ', '')
            data['gross_salary'] = float(amount_str)
            break

    # Salario neto - patrones más flexibles
    net_patterns = [
        r'(?:salario|sueldo)\s+neto[:\s]+\$?\s*([\d,]+\.?\d*)',
        r'neto\s+a\s+pagar[:\s]+\$?\s*([\d,]+\.?\d*)',
        r'total\s+(?:a\s+)?pagar[:\s]+\$?\s*([\d,]+\.?\d*)',
        r'l[ií]quido\s+a\s+recibir[:\s]+\$?\s*([\d,]+\.?\d*)',
        r'pago\s+neto[:\s]+\$?\s*([\d,]+\.?\d*)'
    ]
    for pattern in net_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            amount_str = match.group(1).replace(',', '').replace(' ', '')
            data['net_salary'] = float(amount_str)
            break

    # Si no encontramos salarios con patrones específicos, buscar cualquier cantidad grande
    if 'net_salary' not in data and 'gross_salary' not in data:
        # Buscar cantidades que parezcan salarios (entre $5,000 y $500,000)
        amounts = re.findall(r'\$\s*([\d,]+\.?\d*)', text)
        for amount in amounts:
            try:
                value = float(amount.replace(',', ''))
                if 5000 <= value <= 500000:
                    # Asignar al net_salary si no tenemos ninguno
                    if 'net_salary' not in data:
                        data['net_salary'] = value
                        logger.info(f"💰 Salario inferido: ${value:,.2f}")
                        break
            except:
                continue

    # UUID / Folio Fiscal SAT (formato XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX)
    uuid_re = re.compile(
        r'\b([0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12})\b'
    )
    uuid_match = uuid_re.search(text)
    if uuid_match:
        data['cfdi_uuid'] = uuid_match.group(1).upper()

    # RFC del patrón (segundo RFC en el documento, diferente al del empleado)
    all_rfcs = re.findall(r'\b[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}\b', text)
    if len(all_rfcs) >= 2:
        emp_rfc = data.get('employee_rfc', '')
        for rfc in all_rfcs:
            if rfc != emp_rfc:
                data['employer_rfc'] = rfc
                break

    # Periodo de pago
    period_patterns = [
        r'periodo[:\s]+(\d{1,2}/\d{1,2}/\d{4}\s*-\s*\d{1,2}/\d{1,2}/\d{4})',
        r'del\s+(\d{1,2}/\d{1,2}/\d{4})\s+al\s+(\d{1,2}/\d{1,2}/\d{4})'
    ]
    for pattern in period_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            data['payment_period'] = match.group(0)
            break

    logger.info(f"✅ Datos de nómina extraídos: {len(data)} campos")
    return data


def _mrz_check_digit(s: str) -> int:
    """Calcula dígito verificador MRZ según ICAO 9303."""
    weights = [7, 3, 1]
    total = 0
    for i, ch in enumerate(s):
        if ch.isdigit():
            val = int(ch)
        elif ch.isalpha():
            val = ord(ch.upper()) - ord('A') + 10
        else:  # '<' o desconocido
            val = 0
        total += val * weights[i % 3]
    return total % 10


def _mrz_year(yy: str, prefer_future: bool = False) -> int:
    """
    Convierte año de 2 dígitos a 4.
    - prefer_future=False (nacimiento): >30 → 19xx, ≤30 → 20xx.
    - prefer_future=True (vencimiento): elige el año que quede en el futuro.
    """
    try:
        y = int(yy)
        year_19 = 1900 + y
        year_20 = 2000 + y
        if prefer_future:
            from datetime import date
            cur = date.today().year
            return year_20 if year_19 < cur else year_19
        return year_19 if y > 30 else year_20
    except ValueError:
        return 0


def _extract_mrz_line(pattern: re.Pattern, text: str) -> Optional[str]:
    """
    Busca en cada línea del texto un segmento que coincida con el patrón MRZ.
    Tolera ruido OCR antes/después del contenido MRZ en la misma línea.
    """
    for line in text.splitlines():
        line_clean = line.strip()
        m = pattern.search(line_clean)
        if m:
            candidate = m.group(0)
            if len(candidate) == 30:
                return candidate
    return None


def parse_mrz(text: str) -> Optional[Dict]:
    """
    Extrae y parsea las 3 líneas MRZ de una INE mexicana (TD1, 3×30 chars).
    Tolera ruido OCR en la misma línea antes/después del contenido MRZ.
    Retorna dict con campos parseados y resultado de validación de check digits,
    o None si no se detecta MRZ válida.
    """
    # Estrategia 1: regex estricta (líneas limpias consecutivas)
    mrz_re_strict = re.compile(
        r'(IDMEX[A-Z0-9<]{25})\s*[\r\n]+\s*'
        r'([0-9A-Z<]{30})\s*[\r\n]+\s*'
        r'([A-Z<]{30})',
        re.MULTILINE,
    )
    m = mrz_re_strict.search(text)
    if m:
        l1, l2, l3 = m.group(1), m.group(2), m.group(3)
    else:
        # Estrategia 2: buscar cada línea MRZ de forma independiente,
        # tolerando ruido OCR antes/después en la misma línea de texto.
        # Línea 1: empieza con IDMEX seguida de 25 chars MRZ (total 30)
        l1 = _extract_mrz_line(re.compile(r'IDMEX[A-Z0-9<]{25}'), text)
        # Línea 2: 30 chars de dígitos/letras/<, empieza con 6 dígitos (AAMMDD)
        l2 = _extract_mrz_line(re.compile(r'\d{6}[0-9A-Z<]{24}'), text)
        # Línea 3: 30 chars de letras mayúsculas y < (nombre)
        l3 = _extract_mrz_line(re.compile(r'[A-Z<]{30}'), text)
        if not (l1 and l2 and l3):
            return None

    if len(l1) != 30 or len(l2) != 30 or len(l3) != 30:
        return None

    result: Dict = {"line1": l1, "line2": l2, "line3": l3}

    # ── Línea 1 ──────────────────────────────────────────────────────────────
    # Pos:  1-2  tipo | 3-5  país | 6-14  nro doc | 15  check | 16-30  opcional
    result["doc_number"] = l1[5:14].replace("<", "")
    result["doc_check_ok"] = _mrz_check_digit(l1[5:14]) == int(l1[14]) if l1[14].isdigit() else None

    # ── Línea 2 ──────────────────────────────────────────────────────────────
    # Pos:  1-6  DOB | 7  check | 8  sexo | 9-14  vencimiento | 15  check |
    #        16-18  nac | 19-29  opcional | 30  check compuesto
    dob_raw   = l2[0:6]
    exp_raw   = l2[8:14]
    opt2      = l2[18:29]

    result["dob_raw"]     = dob_raw
    result["expiry_raw"]  = exp_raw
    result["sex_mrz"]     = l2[7]
    result["nationality"] = l2[15:18].replace("<", "")

    # Check digits individuales
    result["dob_check_ok"]    = _mrz_check_digit(dob_raw) == int(l2[6])   if l2[6].isdigit()  else None
    result["expiry_check_ok"] = _mrz_check_digit(exp_raw) == int(l2[14])  if l2[14].isdigit() else None

    # Check dígito compuesto (cubre l1[5:30] + l2[0:7] + l2[8:15] + l2[18:29])
    composite_str = l1[5:30] + l2[0:7] + l2[8:15] + l2[18:29]
    result["composite_check_ok"] = (
        _mrz_check_digit(composite_str) == int(l2[29]) if l2[29].isdigit() else None
    )

    # Fecha de nacimiento formateada
    yy_dob = _mrz_year(dob_raw[0:2])
    try:
        result["dob_mrz"] = f"{dob_raw[4:6]}/{dob_raw[2:4]}/{yy_dob}"  # DD/MM/YYYY
    except Exception:
        result["dob_mrz"] = None

    # Año de vencimiento (prefer_future=True porque documentos siempre expiran en el futuro)
    try:
        result["expiry_year_mrz"] = _mrz_year(exp_raw[0:2], prefer_future=True)
    except Exception:
        result["expiry_year_mrz"] = None

    # ── Línea 3 — nombre ─────────────────────────────────────────────────────
    # Formato: APELLIDO1<APELLIDO2<<NOMBRE1<NOMBRE2<...
    name_raw = l3.rstrip("<")
    parts = name_raw.split("<<")
    if len(parts) >= 2:
        surnames   = parts[0].replace("<", " ").strip()
        given      = parts[1].replace("<", " ").strip()
        result["name_mrz"] = f"{surnames} {given}".strip()
    else:
        result["name_mrz"] = name_raw.replace("<", " ").strip()

    return result


def decode_voter_id_date(voter_id: str) -> Optional[str]:
    """
    Decodifica la fecha de nacimiento embebida en la clave de elector.
    Formato estándar INE: AAAAAA (6 letras) + YYMMDD + X + DDD = 18 chars.
    Prueba el offset estándar (6) y uno corto (4) por si el OCR truncó las letras.
    Retorna 'DD/MM/YYYY' o None si no es posible decodificar.
    """
    if not voter_id:
        return None
    for offset in (6, 4):
        if len(voter_id) < offset + 6:
            continue
        date_part = voter_id[offset:offset + 6]
        if not date_part.isdigit():
            continue
        yy, mm, dd = date_part[0:2], date_part[2:4], date_part[4:6]
        year = _mrz_year(yy)
        try:
            if 1 <= int(mm) <= 12 and 1 <= int(dd) <= 31 and year > 0:
                return f"{dd}/{mm}/{year}"
        except ValueError:
            continue
    return None


def extract_id_document_data(text: str) -> Dict:
    """Extrae datos de documento de identificación (INE)"""
    data = {}

    logger.info(f"🔍 Extrayendo datos INE — texto: {len(text)} chars")

    # CURP - Buscar con múltiples patrones
    # Patrón 1: CURP sin espacios
    curp_pattern1 = r'\b[A-Z]{4}\d{6}[HM][A-Z]{5}[0-9A-Z]\d\b'
    # Patrón 2: CURP con espacios posibles
    curp_pattern2 = r'\b[A-Z]{4}\s?\d{6}\s?[HM]\s?[A-Z]{5}\s?[0-9A-Z]\s?\d\b'
    # Patrón 3: Buscar después de "CURP:" o "CLAVE:" o "CLAVE UNICA:"
    curp_pattern3 = r'(?:CURP|CLAVE(?:\s+[UÚ]NICA)?)[:\s]+([A-Z]{4}\s?\d{6}\s?[HM]\s?[A-Z]{5}\s?[0-9A-Z]\s?\d)'

    # Intentar con cada patrón
    for pattern in [curp_pattern3, curp_pattern1, curp_pattern2]:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            # Si es el patrón 3, tomar el grupo 1, si no, todo el match
            curp_found = match.group(1) if pattern == curp_pattern3 else match.group(0)
            # Limpiar espacios
            data['curp'] = curp_found.replace(' ', '').upper()
            break

    # Clave de elector
    elector_pattern = r'\b[A-Z]{6}\d{8}[HM]\d{3}\b'
    match = re.search(elector_pattern, text)
    if match:
        data['voter_id'] = match.group(0)

    # Nombre completo — acepta nombre con comas (apellido, nombre) y múltiples palabras
    # En las INE el campo "NOMBRE" aparece solo en una línea y el nombre en la siguiente
    _LABELS = {"PUESTO", "CARGO", "RFC", "CURP", "DOMICILIO", "DIRECCION", "VIGENCIA", "SECCION"}
    name_patterns = [
        r'nombre[ \t]*[\r\n]+([A-ZÁÉÍÓÚÑ ]{6,60})(?:\r?\n|$)',  # "NOMBRE\n<nombre>" — sin newlines en el capture
        r'nombre[:\s]+([A-ZÁÉÍÓÚÑ ]+?)(?:\n|curp|rfc|domicilio)',
        r'apellidos?\s+y\s+nombre[:\s]+([A-ZÁÉÍÓÚÑ ,]+?)(?:\n|$)',
        r'nombre\s+del\s+ciudadano[:\s]+([A-ZÁÉÍÓÚÑ ,]+?)(?:\n|$)',
    ]
    for pattern in name_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            candidate = match.group(1).strip().rstrip(',').strip()
            if len(candidate) >= 6 and candidate.upper() not in _LABELS:
                data['full_name'] = candidate
                break

    # Domicilio
    address_patterns = [
        r'domicilio[:\s]+([A-ZÁÉÍÓÚÑa-záéíóúñ0-9\s,\.#]+?)(?:\n\n|vigencia)',
        r'direcci[oó]n[:\s]+([A-ZÁÉÍÓÚÑa-záéíóúñ0-9\s,\.#]+?)(?:\n\n|$)'
    ]
    for pattern in address_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            data['address'] = match.group(1).strip()
            break

    # Fecha de nacimiento
    birth_patterns = [
        r'nacimiento[:\s]+(\d{1,2}/\d{1,2}/\d{4})',
        r'fecha\s+de\s+nac[:\s]+(\d{1,2}/\d{1,2}/\d{4})'
    ]
    for pattern in birth_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            data['birth_date'] = match.group(1)
            break

    # Vigencia — capturar rango "2020-2030", "2020 - 2030", o año simple "2030"
    range_match = re.search(r'vigencia[:\s]+(\d{4})\s*[/\-]\s*(\d{4})', text, re.IGNORECASE)
    if range_match:
        data['expiration_date'] = f"{range_match.group(1)}-{range_match.group(2)}"
    else:
        expiry_patterns = [
            r'vigencia[:\s]+(\d{4})',
            r'v[aá]lida\s+hasta[:\s]+(\d{1,2}/\d{1,2}/\d{4})'
        ]
        for pattern in expiry_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                data['expiration_date'] = match.group(1)
                break

    # ── MRZ (Machine Readable Zone) del reverso ──────────────────────────────
    mrz = parse_mrz(text)
    if mrz:
        data['mrz'] = mrz
        if mrz.get('dob_mrz'):
            data['dob_mrz'] = mrz['dob_mrz']
        if mrz.get('name_mrz'):
            data['name_mrz'] = mrz['name_mrz']
        if mrz.get('expiry_year_mrz'):
            data['expiry_year_mrz'] = mrz['expiry_year_mrz']
        logger.info(f"✅ MRZ parseada: DOB={mrz.get('dob_mrz')} nombre={mrz.get('name_mrz')}")
    else:
        logger.info("⚠️  MRZ no detectada en el texto")

    # ── Fecha embebida en clave de elector ───────────────────────────────────
    voter_id = data.get('voter_id', '')
    if voter_id:
        clave_date = decode_voter_id_date(voter_id)
        if clave_date:
            data['dob_clave_elector'] = clave_date
            logger.info(f"✅ Fecha en clave de elector: {clave_date}")

    logger.info(f"✅ Datos de identificación extraídos: {len(data)} campos")
    return data


def extract_tax_return_data(text: str) -> Dict:
    """Extrae datos de declaración fiscal"""
    data = {}

    # RFC
    rfc_pattern = r'\b[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}\b'
    match = re.search(rfc_pattern, text)
    if match:
        data['rfc'] = match.group(0)

    # Ingreso anual
    income_patterns = [
        r'ingresos?\s+anuales?[:\s]+\$?\s*([\d,]+\.?\d*)',
        r'total\s+de\s+ingresos[:\s]+\$?\s*([\d,]+\.?\d*)'
    ]
    for pattern in income_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            data['annual_income'] = float(match.group(1).replace(',', ''))
            break

    # Año fiscal
    year_pattern = r'ejercicio\s+fiscal[:\s]+(\d{4})'
    match = re.search(year_pattern, text, re.IGNORECASE)
    if match:
        data['fiscal_year'] = match.group(1)

    logger.info(f"✅ Datos fiscales extraídos: {len(data)} campos")
    return data


def extract_proof_of_address_data(text: str) -> Dict:
    """Extrae datos de comprobante de domicilio"""
    data = {}

    # Dirección
    address_patterns = [
        r'domicilio[:\s]+([A-ZÁÉÍÓÚÑa-záéíóúñ0-9\s,\.#]+?)(?:\n\n|$)',
        r'direcci[oó]n[:\s]+([A-ZÁÉÍÓÚÑa-záéíóúñ0-9\s,\.#]+?)(?:\n\n|$)'
    ]
    for pattern in address_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            data['address'] = match.group(1).strip()
            break

    # Nombre del titular
    name_patterns = [
        r'titular[:\s]+([A-ZÁÉÍÓÚÑ\s]+)',
        r'nombre[:\s]+([A-ZÁÉÍÓÚÑ\s]+)'
    ]
    for pattern in name_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            data['account_holder'] = match.group(1).strip()
            break

    # Tipo de servicio
    services = ['CFE', 'Telmex', 'Telcel', 'Agua', 'Gas']
    for service in services:
        if service.lower() in text.lower():
            data['service_type'] = service
            break

    logger.info(f"✅ Datos de comprobante extraídos: {len(data)} campos")
    return data


def extract_employment_letter_data(text: str) -> Dict:
    """Extrae datos de carta laboral"""
    data = {}

    # Empresa
    company_patterns = [
        r'empresa[:\s]+([A-ZÁÉÍÓÚÑ\s\.]+?)(?:\n|$)',
        r'(?:de|en)\s+([A-ZÁÉÍÓÚÑ\s\.]+?)\s+certifica'
    ]
    for pattern in company_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            data['employer_name'] = match.group(1).strip()
            break

    # Puesto
    position_patterns = [
        r'puesto[:\s]+([A-ZÁÉÍÓÚÑa-záéíóúñ\s]+?)(?:\n|$)',
        r'cargo[:\s]+([A-ZÁÉÍÓÚÑa-záéíóúñ\s]+?)(?:\n|$)'
    ]
    for pattern in position_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            data['position'] = match.group(1).strip()
            break

    # Fecha de ingreso
    start_patterns = [
        r'ingres[oó]\s+(?:el\s+)?(\d{1,2}/\d{1,2}/\d{4})',
        r'desde\s+(?:el\s+)?(\d{1,2}/\d{1,2}/\d{4})'
    ]
    for pattern in start_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            data['start_date'] = match.group(1)
            break

    logger.info(f"✅ Datos de carta laboral extraídos: {len(data)} campos")
    return data
