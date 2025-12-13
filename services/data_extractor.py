"""
Servicio de extracción de datos estructurados
Extrae información específica según el tipo de documento
"""

import re
import logging
from typing import Dict, Optional, List

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

    # Salario bruto
    gross_patterns = [
        r'salario\s+bruto[:\s]+\$?\s*([\d,]+\.?\d*)',
        r'percepciones[:\s]+\$?\s*([\d,]+\.?\d*)'
    ]
    for pattern in gross_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            data['gross_salary'] = float(match.group(1).replace(',', ''))
            break

    # Salario neto
    net_patterns = [
        r'salario\s+neto[:\s]+\$?\s*([\d,]+\.?\d*)',
        r'neto\s+a\s+pagar[:\s]+\$?\s*([\d,]+\.?\d*)',
        r'total\s+a\s+pagar[:\s]+\$?\s*([\d,]+\.?\d*)'
    ]
    for pattern in net_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            data['net_salary'] = float(match.group(1).replace(',', ''))
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


def extract_id_document_data(text: str) -> Dict:
    """Extrae datos de documento de identificación (INE)"""
    data = {}

    # CURP
    curp_pattern = r'\b[A-Z]{4}\d{6}[HM][A-Z]{5}[0-9A-Z]\d\b'
    match = re.search(curp_pattern, text)
    if match:
        data['curp'] = match.group(0)

    # Clave de elector
    elector_pattern = r'\b[A-Z]{6}\d{8}[HM]\d{3}\b'
    match = re.search(elector_pattern, text)
    if match:
        data['voter_id'] = match.group(0)

    # Nombre completo
    name_patterns = [
        r'nombre[:\s]+([A-ZÁÉÍÓÚÑ\s]+?)(?:\n|curp)',
        r'apellidos?\s+y\s+nombre[:\s]+([A-ZÁÉÍÓÚÑ\s]+?)(?:\n|$)'
    ]
    for pattern in name_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            data['full_name'] = match.group(1).strip()
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

    # Vigencia
    expiry_patterns = [
        r'vigencia[:\s]+(\d{4})',
        r'v[aá]lida\s+hasta[:\s]+(\d{1,2}/\d{1,2}/\d{4})'
    ]
    for pattern in expiry_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            data['expiration_date'] = match.group(1)
            break

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
