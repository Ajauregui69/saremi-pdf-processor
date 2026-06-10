"""
Modelos para el sistema de verificación de documentos
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from enum import Enum


class CheckStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    WARNING = "warning"


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    INVALID = "invalid"
    INCONCLUSIVE = "inconclusive"
    MANUAL_REVIEW = "manual_review"


class FraudFlagSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"


class FraudFlag(BaseModel):
    code: str = Field(..., description="Código de alerta (ej: AI_GENERATED, DIGITAL_MANIPULATION)")
    severity: FraudFlagSeverity = Field(..., description="Severidad: critical | high | medium")
    description: str = Field(..., description="Descripción legible del fraude detectado")
    source_check: str = Field(..., description="Nombre del check que originó la alerta")


class CheckItem(BaseModel):
    name: str = Field(..., description="Nombre del check realizado")
    status: CheckStatus = Field(..., description="Resultado del check")
    detail: str = Field(..., description="Descripción del resultado")


class VerificationResult(BaseModel):
    document_type: str = Field(..., description="Tipo de documento verificado")
    status: VerificationStatus = Field(..., description="Veredicto final")
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="Puntuación de confianza (0.0 - 1.0)")
    extracted_data: Dict[str, Any] = Field(default_factory=dict, description="Campos extraídos del documento")
    checks: List[CheckItem] = Field(default_factory=list, description="Lista de verificaciones realizadas")
    conclusion: str = Field(..., description="Texto legible con el veredicto")
    warnings: List[str] = Field(default_factory=list, description="Advertencias menores")
    fraud_flags: List[FraudFlag] = Field(default_factory=list, description="Alertas críticas de fraude detectadas")
    processing_time_ms: int = Field(..., description="Tiempo de procesamiento en milisegundos")
