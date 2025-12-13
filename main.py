"""
Microservicio de Procesamiento de PDFs para HAVI Score
Extrae texto e imágenes de documentos financieros para facilitar el análisis de IA
"""

from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging
import os
from typing import List, Optional
import tempfile
import shutil

from services.pdf_processor import PDFProcessor
from services.ocr_service import OCRService
from services.image_processor import ImageProcessor
from models.schemas import ProcessedDocument, DocumentType, OCRResult

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Inicializar FastAPI
app = FastAPI(
    title="HAVI Score - PDF Processor Service",
    description="Microservicio para procesamiento avanzado de PDFs y extracción de datos para scoring crediticio",
    version="1.0.0"
)

# CORS - Permitir requests desde el backend de AdonisJS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3333", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inicializar servicios
pdf_processor = PDFProcessor()
ocr_service = OCRService()
image_processor = ImageProcessor()


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "service": "HAVI Score PDF Processor",
        "status": "running",
        "version": "1.0.0"
    }


@app.get("/health")
async def health_check():
    """Health check detallado"""
    return {
        "status": "healthy",
        "services": {
            "pdf_processor": "ready",
            "ocr_service": "ready",
            "image_processor": "ready"
        }
    }


@app.post("/process-pdf", response_model=ProcessedDocument)
async def process_pdf(
    file: UploadFile = File(...),
    document_type: str = Form("bank_statement"),
    use_advanced_ocr: bool = Form(True),
    extract_images: bool = Form(True)
):
    """
    Procesa un archivo PDF y extrae texto e imágenes

    Args:
        file: Archivo PDF a procesar
        document_type: Tipo de documento (bank_statement, payroll, id_document, etc.)
        use_advanced_ocr: Usar OCR avanzado (EasyOCR + Tesseract)
        extract_images: Extraer imágenes del documento

    Returns:
        ProcessedDocument con texto extraído, imágenes y metadatos
    """
    logger.info(f"📄 Procesando PDF: {file.filename}, tipo: {document_type}")

    # Validar tipo de archivo
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="El archivo debe ser un PDF")

    temp_file_path = None

    try:
        # Guardar archivo temporalmente
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
            temp_file_path = temp_file.name
            shutil.copyfileobj(file.file, temp_file)

        logger.info(f"📁 Archivo guardado temporalmente en: {temp_file_path}")

        # 1. Extraer texto nativo del PDF
        logger.info("📝 Extrayendo texto nativo...")
        native_text = pdf_processor.extract_text(temp_file_path)

        # 2. Obtener información del PDF
        pdf_info = pdf_processor.get_pdf_info(temp_file_path)
        logger.info(f"📊 PDF Info: {pdf_info['num_pages']} páginas")

        # 3. Convertir PDF a imágenes
        logger.info("🖼️ Convirtiendo PDF a imágenes...")
        images = pdf_processor.convert_to_images(temp_file_path)
        logger.info(f"✅ Generadas {len(images)} imágenes")

        # 4. OCR si el texto nativo es insuficiente
        ocr_text = ""
        ocr_confidence = 0.0

        if len(native_text.strip()) < 100:  # Poco texto nativo
            logger.info("🔍 Texto nativo insuficiente, aplicando OCR...")

            if use_advanced_ocr:
                # OCR avanzado con EasyOCR
                ocr_results = await ocr_service.process_images_advanced(images)
                ocr_text = "\n\n".join([result['text'] for result in ocr_results])
                ocr_confidence = sum([result['confidence'] for result in ocr_results]) / len(ocr_results) if ocr_results else 0
                logger.info(f"✨ OCR avanzado completado - Confianza: {ocr_confidence:.2f}%")
            else:
                # OCR básico con Tesseract
                ocr_results = ocr_service.process_images_basic(images)
                ocr_text = "\n\n".join([result['text'] for result in ocr_results])
                ocr_confidence = sum([result['confidence'] for result in ocr_results]) / len(ocr_results) if ocr_results else 0
                logger.info(f"📝 OCR básico completado - Confianza: {ocr_confidence:.2f}%")

        # 5. Combinar texto nativo y OCR
        final_text = native_text if len(native_text.strip()) >= 100 else ocr_text
        if len(native_text.strip()) >= 100 and len(ocr_text.strip()) > 0:
            final_text = f"{native_text}\n\n--- OCR Additional Text ---\n\n{ocr_text}"

        # 6. Extraer y procesar imágenes embebidas
        extracted_images = []
        if extract_images:
            logger.info("🎨 Extrayendo imágenes embebidas...")
            extracted_images = pdf_processor.extract_embedded_images(temp_file_path)
            logger.info(f"✅ Extraídas {len(extracted_images)} imágenes embebidas")

        # 7. Análisis específico por tipo de documento
        document_analysis = analyze_document_type(final_text, document_type)

        logger.info(f"✅ Procesamiento completado - {len(final_text)} caracteres extraídos")

        return ProcessedDocument(
            filename=file.filename,
            document_type=document_type,
            num_pages=pdf_info['num_pages'],
            extracted_text=final_text,
            native_text=native_text,
            ocr_text=ocr_text,
            ocr_confidence=ocr_confidence,
            num_images=len(images),
            num_extracted_images=len(extracted_images),
            text_length=len(final_text),
            processing_method="native" if len(native_text.strip()) >= 100 else "ocr",
            document_analysis=document_analysis,
            success=True
        )

    except Exception as e:
        logger.error(f"❌ Error procesando PDF: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error procesando PDF: {str(e)}")

    finally:
        # Limpiar archivo temporal
        if temp_file_path and os.path.exists(temp_file_path):
            os.unlink(temp_file_path)
            logger.info("🧹 Archivo temporal eliminado")


@app.post("/process-image", response_model=OCRResult)
async def process_image(
    file: UploadFile = File(...),
    use_advanced_ocr: bool = Form(True)
):
    """
    Procesa una imagen y extrae texto mediante OCR

    Args:
        file: Imagen a procesar (JPG, PNG, etc.)
        use_advanced_ocr: Usar OCR avanzado (EasyOCR)

    Returns:
        OCRResult con texto extraído y confianza
    """
    logger.info(f"🖼️ Procesando imagen: {file.filename}")

    # Validar tipo de archivo
    valid_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff']
    if not any(file.filename.lower().endswith(ext) for ext in valid_extensions):
        raise HTTPException(status_code=400, detail="Formato de imagen no soportado")

    temp_file_path = None

    try:
        # Guardar archivo temporalmente
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as temp_file:
            temp_file_path = temp_file.name
            shutil.copyfileobj(file.file, temp_file)

        # Procesar imagen
        if use_advanced_ocr:
            result = await ocr_service.process_single_image_advanced(temp_file_path)
            logger.info(f"✨ OCR avanzado completado - Confianza: {result['confidence']:.2f}%")
        else:
            result = ocr_service.process_single_image_basic(temp_file_path)
            logger.info(f"📝 OCR básico completado - Confianza: {result['confidence']:.2f}%")

        return OCRResult(
            filename=file.filename,
            text=result['text'],
            confidence=result['confidence'],
            method="easyocr" if use_advanced_ocr else "tesseract",
            success=True
        )

    except Exception as e:
        logger.error(f"❌ Error procesando imagen: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error procesando imagen: {str(e)}")

    finally:
        # Limpiar archivo temporal
        if temp_file_path and os.path.exists(temp_file_path):
            os.unlink(temp_file_path)


@app.post("/extract-structured-data")
async def extract_structured_data(
    file: UploadFile = File(...),
    document_type: str = Form("bank_statement")
):
    """
    Extrae datos estructurados específicos según el tipo de documento
    Útil para análisis de HAVI score
    """
    logger.info(f"📊 Extrayendo datos estructurados de {document_type}")

    # Primero procesar el documento
    processed = await process_pdf(file, document_type, use_advanced_ocr=True, extract_images=False)

    # Extraer datos estructurados según tipo
    from services.data_extractor import extract_financial_data

    structured_data = extract_financial_data(processed.extracted_text, document_type)

    return {
        "document_type": document_type,
        "extracted_data": structured_data,
        "confidence": processed.ocr_confidence,
        "analysis": processed.document_analysis
    }


def analyze_document_type(text: str, doc_type: str) -> dict:
    """
    Analiza el documento según su tipo y devuelve insights relevantes
    """
    analysis = {
        "keywords_found": [],
        "estimated_quality": "unknown",
        "suggestions": []
    }

    text_lower = text.lower()

    if doc_type == "bank_statement":
        keywords = ["banco", "saldo", "cuenta", "balance", "transacción", "depósito", "retiro"]
        analysis["keywords_found"] = [kw for kw in keywords if kw in text_lower]

        if len(analysis["keywords_found"]) >= 4:
            analysis["estimated_quality"] = "high"
        elif len(analysis["keywords_found"]) >= 2:
            analysis["estimated_quality"] = "medium"
        else:
            analysis["estimated_quality"] = "low"
            analysis["suggestions"].append("El documento podría no ser un estado de cuenta válido")

    elif doc_type == "payroll":
        keywords = ["nómina", "salario", "sueldo", "imss", "rfc", "empresa", "periodo"]
        analysis["keywords_found"] = [kw for kw in keywords if kw in text_lower]

        if len(analysis["keywords_found"]) >= 3:
            analysis["estimated_quality"] = "high"
        elif len(analysis["keywords_found"]) >= 2:
            analysis["estimated_quality"] = "medium"
        else:
            analysis["estimated_quality"] = "low"
            analysis["suggestions"].append("El documento podría no ser un recibo de nómina válido")

    elif doc_type == "id_document":
        keywords = ["ine", "elector", "curp", "domicilio", "vigencia", "folio"]
        analysis["keywords_found"] = [kw for kw in keywords if kw in text_lower]

        if len(analysis["keywords_found"]) >= 3:
            analysis["estimated_quality"] = "high"
        else:
            analysis["estimated_quality"] = "low"
            analysis["suggestions"].append("Verificar que sea una identificación oficial válida")

    return analysis


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
