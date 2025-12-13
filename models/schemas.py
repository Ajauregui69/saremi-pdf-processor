"""
Modelos de datos para el servicio de procesamiento de PDFs
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from enum import Enum


class DocumentType(str, Enum):
    """Tipos de documentos soportados"""
    BANK_STATEMENT = "bank_statement"
    PAYROLL = "payroll"
    ID_DOCUMENT = "id_document"
    TAX_RETURN = "tax_return"
    PROOF_OF_ADDRESS = "proof_of_address"
    EMPLOYMENT_LETTER = "employment_letter"


class ProcessedDocument(BaseModel):
    """Resultado del procesamiento de un documento"""
    filename: str = Field(..., description="Nombre del archivo procesado")
    document_type: str = Field(..., description="Tipo de documento")
    num_pages: int = Field(..., description="Número de páginas")
    extracted_text: str = Field(..., description="Texto extraído completo")
    native_text: str = Field(default="", description="Texto nativo del PDF")
    ocr_text: str = Field(default="", description="Texto extraído por OCR")
    ocr_confidence: float = Field(default=0.0, description="Confianza del OCR (0-100)")
    num_images: int = Field(default=0, description="Número de imágenes generadas")
    num_extracted_images: int = Field(default=0, description="Número de imágenes embebidas extraídas")
    text_length: int = Field(..., description="Longitud del texto extraído")
    processing_method: str = Field(..., description="Método usado (native/ocr)")
    document_analysis: Dict = Field(default_factory=dict, description="Análisis del documento")
    success: bool = Field(default=True, description="Si el procesamiento fue exitoso")


class OCRResult(BaseModel):
    """Resultado del procesamiento OCR de una imagen"""
    filename: str = Field(..., description="Nombre del archivo")
    text: str = Field(..., description="Texto extraído")
    confidence: float = Field(..., description="Confianza del OCR (0-100)")
    method: str = Field(..., description="Método OCR usado (tesseract/easyocr)")
    success: bool = Field(default=True, description="Si el procesamiento fue exitoso")


class FinancialData(BaseModel):
    """Datos financieros estructurados extraídos"""
    account_number: Optional[str] = None
    bank_name: Optional[str] = None
    account_holder: Optional[str] = None
    balance: Optional[float] = None
    monthly_income: Optional[float] = None
    monthly_expenses: Optional[float] = None
    transactions_count: Optional[int] = None
    average_balance: Optional[float] = None
    savings_rate: Optional[float] = None


class PayrollData(BaseModel):
    """Datos de nómina estructurados"""
    employee_name: Optional[str] = None
    employee_rfc: Optional[str] = None
    employer_name: Optional[str] = None
    gross_salary: Optional[float] = None
    net_salary: Optional[float] = None
    payment_period: Optional[str] = None
    payment_date: Optional[str] = None
    deductions: Optional[Dict[str, float]] = None


class IDDocumentData(BaseModel):
    """Datos de documento de identificación"""
    full_name: Optional[str] = None
    curp: Optional[str] = None
    voter_id: Optional[str] = None
    address: Optional[str] = None
    birth_date: Optional[str] = None
    expiration_date: Optional[str] = None
