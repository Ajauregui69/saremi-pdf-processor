"""
Clase base abstracta para todos los verificadores de documentos
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from models.verification_schemas import CheckItem, CheckStatus, VerificationResult, VerificationStatus


class BaseVerifier(ABC):

    @abstractmethod
    async def verify(self, file_path: str, extracted_data: Dict) -> List[CheckItem]:
        """
        Realiza las verificaciones específicas del tipo de documento.

        Args:
            file_path: Ruta al archivo temporal del documento
            extracted_data: Datos ya extraídos por el extractor (OCR + regex)

        Returns:
            Lista de CheckItem con los resultados de cada verificación
        """
        ...

    def _check(self, name: str, status: CheckStatus, detail: str) -> CheckItem:
        return CheckItem(name=name, status=status, detail=detail)

    def _passed(self, name: str, detail: str) -> CheckItem:
        return CheckItem(name=name, status=CheckStatus.PASSED, detail=detail)

    def _failed(self, name: str, detail: str) -> CheckItem:
        return CheckItem(name=name, status=CheckStatus.FAILED, detail=detail)

    def _skipped(self, name: str, detail: str) -> CheckItem:
        return CheckItem(name=name, status=CheckStatus.SKIPPED, detail=detail)

    def _warning(self, name: str, detail: str) -> CheckItem:
        return CheckItem(name=name, status=CheckStatus.WARNING, detail=detail)

    async def _run_fraud_analysis(
        self,
        file_path: str,
        doc_type: str,
        extracted_data: Optional[Dict] = None,
        preloaded_qr_codes: Optional[List] = None,
    ) -> List[CheckItem]:
        from services.fraud_detector import analyze_document
        return await analyze_document(file_path, doc_type, extracted_data, preloaded_qr_codes)
