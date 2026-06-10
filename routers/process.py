"""
Router para endpoints de procesamiento de documentos (migrado desde main.py)
Prefijo: /v1/process
"""

import logging
import os
import io
import tempfile
import shutil
import base64

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from PIL import Image

from models.schemas import ProcessedDocument, OCRResult
from services.pdf_processor import PDFProcessor
from services.ocr_service import OCRService
from services.qr_service import QRService
from services.data_extractor import extract_financial_data

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/process", tags=["process"])

pdf_processor = PDFProcessor()
ocr_service = OCRService()
qr_service = QRService()


@router.post("/process-pdf", response_model=ProcessedDocument)
async def process_pdf(
    file: UploadFile = File(...),
    document_type: str = Form("bank_statement"),
    use_advanced_ocr: bool = Form(True),
    extract_images: bool = Form(True),
):
    """Procesa un PDF y extrae texto e imágenes."""
    logger.info(f"Procesando PDF: {file.filename}, tipo: {document_type}")

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="El archivo debe ser un PDF")

    temp_file_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            temp_file_path = tmp.name
            shutil.copyfileobj(file.file, tmp)

        native_text = pdf_processor.extract_text(temp_file_path)
        pdf_info = pdf_processor.get_pdf_info(temp_file_path)
        is_id_document = document_type in ["ine", "curp", "id_document"]

        images = []
        if not is_id_document:
            max_pages = 3
            if extract_images and pdf_info["num_pages"] <= max_pages or len(native_text.strip()) < 100:
                images = pdf_processor.convert_to_images(temp_file_path)

        ocr_text = ""
        ocr_confidence = 0.0

        if not is_id_document and len(native_text.strip()) < 100 and images:
            if pdf_info["num_pages"] > 3:
                use_advanced_ocr = False
            if use_advanced_ocr:
                ocr_results = await ocr_service.process_images_advanced(images)
            else:
                ocr_results = ocr_service.process_images_basic(images)
            ocr_text = "\n\n".join(r["text"] for r in ocr_results)
            ocr_confidence = (sum(r["confidence"] for r in ocr_results) / len(ocr_results)) if ocr_results else 0

        if is_id_document:
            final_text = native_text if native_text.strip() else "Documento de identificación"
        else:
            final_text = native_text if len(native_text.strip()) >= 100 else ocr_text
            if len(native_text.strip()) >= 100 and ocr_text.strip():
                final_text = f"{native_text}\n\n--- OCR Additional Text ---\n\n{ocr_text}"

        extracted_images = []
        extracted_images_base64 = []
        if extract_images:
            extracted_images = pdf_processor.extract_embedded_images(temp_file_path)
            if not extracted_images:
                if is_id_document:
                    images = pdf_processor.convert_to_images(temp_file_path)
                    extracted_images = images
                elif images:
                    extracted_images = images

            for img in extracted_images:
                try:
                    if isinstance(img, str) and os.path.exists(img):
                        with open(img, "rb") as f:
                            extracted_images_base64.append(
                                "data:image/png;base64," + base64.b64encode(f.read()).decode()
                            )
                        if img not in images:
                            os.unlink(img)
                    elif hasattr(img, "save"):
                        buf = io.BytesIO()
                        img.save(buf, format="PNG")
                        extracted_images_base64.append(
                            "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
                        )
                except Exception as e:
                    logger.warning(f"Error convirtiendo imagen a base64: {e}")

        document_analysis = _analyze_document_type(final_text, document_type)
        processing_method = "vision" if is_id_document else ("native" if len(native_text.strip()) >= 100 else "ocr")

        return ProcessedDocument(
            filename=file.filename,
            document_type=document_type,
            num_pages=pdf_info["num_pages"],
            extracted_text=final_text,
            native_text=native_text,
            ocr_text=ocr_text,
            ocr_confidence=ocr_confidence,
            num_images=len(images),
            num_extracted_images=len(extracted_images),
            extracted_images_base64=extracted_images_base64,
            text_length=len(final_text),
            processing_method=processing_method,
            document_analysis=document_analysis,
            success=True,
        )

    except Exception as e:
        logger.error(f"Error procesando PDF: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error procesando PDF: {e}")
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            os.unlink(temp_file_path)


@router.post("/process-image", response_model=OCRResult)
async def process_image(
    file: UploadFile = File(...),
    use_advanced_ocr: bool = Form(True),
):
    """Procesa una imagen y extrae texto mediante OCR."""
    logger.info(f"Procesando imagen: {file.filename}")

    valid_extensions = [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff"]
    if not any(file.filename.lower().endswith(ext) for ext in valid_extensions):
        raise HTTPException(status_code=400, detail="Formato de imagen no soportado")

    temp_file_path = None
    try:
        ext = os.path.splitext(file.filename)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            temp_file_path = tmp.name
            shutil.copyfileobj(file.file, tmp)

        if use_advanced_ocr:
            result = await ocr_service.process_single_image_advanced(temp_file_path)
        else:
            result = ocr_service.process_single_image_basic(temp_file_path)

        return OCRResult(
            filename=file.filename,
            text=result["text"],
            confidence=result["confidence"],
            method="easyocr" if use_advanced_ocr else "tesseract",
            success=True,
        )
    except Exception as e:
        logger.error(f"Error procesando imagen: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error procesando imagen: {e}")
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            os.unlink(temp_file_path)


@router.post("/extract-structured-data")
async def extract_structured_data(
    file: UploadFile = File(...),
    document_type: str = Form("bank_statement"),
):
    """Extrae datos estructurados específicos según el tipo de documento."""
    logger.info(f"Extrayendo datos estructurados de {document_type}")

    file_content = await file.read()
    file.file = io.BytesIO(file_content)
    file.file.seek(0)

    processed = await process_pdf(file, document_type, use_advanced_ocr=True, extract_images=True)
    structured_data = extract_financial_data(processed.extracted_text, document_type)

    qr_codes = []
    if document_type == "bank_statement":
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(file_content)
                tmp_path = tmp.name
            page_images = pdf_processor.convert_to_images(tmp_path)
            os.unlink(tmp_path)
            qr_codes = qr_service.scan_images(page_images)
        except Exception as e:
            logger.warning(f"Error en escaneo QR: {e}")

    return {
        "document_type": document_type,
        "extracted_data": structured_data,
        "extracted_images_base64": processed.extracted_images_base64,
        "confidence": processed.ocr_confidence,
        "analysis": processed.document_analysis,
        "qr_codes": qr_codes,
        "qr_verified": len(qr_codes) > 0,
    }


def _analyze_document_type(text: str, doc_type: str) -> dict:
    analysis = {"keywords_found": [], "estimated_quality": "unknown", "suggestions": []}
    text_lower = text.lower()

    kw_map = {
        "bank_statement": ["banco", "saldo", "cuenta", "balance", "transacción", "depósito", "retiro"],
        "payroll": ["nómina", "salario", "sueldo", "imss", "rfc", "empresa", "periodo"],
        "id_document": ["ine", "elector", "curp", "domicilio", "vigencia", "folio"],
    }
    thresholds = {"bank_statement": (4, 2), "payroll": (3, 2), "id_document": (3, 1)}

    keywords = kw_map.get(doc_type, [])
    found = [kw for kw in keywords if kw in text_lower]
    analysis["keywords_found"] = found

    hi, lo = thresholds.get(doc_type, (3, 2))
    if len(found) >= hi:
        analysis["estimated_quality"] = "high"
    elif len(found) >= lo:
        analysis["estimated_quality"] = "medium"
    else:
        analysis["estimated_quality"] = "low"
        analysis["suggestions"].append(f"El documento podría no ser un {doc_type} válido")

    return analysis
