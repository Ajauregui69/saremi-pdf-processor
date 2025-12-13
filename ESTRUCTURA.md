# 📁 Estructura del Proyecto - PDF Processor Service

```
pdf-processor-service/
│
├── 📄 main.py                      # Aplicación FastAPI principal
│   ├── Endpoints REST
│   ├── /process-pdf              # Procesar documentos PDF
│   ├── /process-image            # Procesar imágenes
│   ├── /extract-structured-data  # Extraer datos estructurados
│   └── /health                   # Health check
│
├── 📂 models/                      # Modelos de datos
│   ├── __init__.py
│   └── schemas.py                # Esquemas Pydantic
│       ├── ProcessedDocument     # Resultado de procesamiento PDF
│       ├── OCRResult             # Resultado de OCR
│       ├── FinancialData         # Datos de estado de cuenta
│       ├── PayrollData           # Datos de nómina
│       └── IDDocumentData        # Datos de identificación
│
├── 📂 services/                    # Lógica de negocio
│   ├── __init__.py
│   ├── pdf_processor.py          # Procesamiento de PDFs
│   │   ├── extract_text()        # Extraer texto nativo
│   │   ├── get_pdf_info()        # Info del PDF
│   │   ├── convert_to_images()   # PDF → imágenes
│   │   └── extract_embedded_images()
│   │
│   ├── ocr_service.py             # OCR (Tesseract + EasyOCR)
│   │   ├── process_single_image_basic()    # Tesseract
│   │   ├── process_single_image_advanced() # EasyOCR
│   │   ├── process_images_basic()
│   │   └── process_images_advanced()
│   │
│   ├── image_processor.py         # Procesamiento de imágenes
│   │   ├── enhance_for_ocr()     # Mejorar imagen para OCR
│   │   ├── denoise()             # Reducir ruido
│   │   ├── increase_contrast()   # CLAHE
│   │   ├── sharpen()             # Aumentar nitidez
│   │   ├── binarize()            # Binarización
│   │   ├── detect_orientation()  # Detectar rotación
│   │   └── auto_rotate()         # Rotar automáticamente
│   │
│   └── data_extractor.py          # Extracción de datos estructurados
│       ├── extract_financial_data()
│       ├── extract_bank_statement_data()
│       ├── extract_payroll_data()
│       ├── extract_id_document_data()
│       ├── extract_tax_return_data()
│       ├── extract_proof_of_address_data()
│       └── extract_employment_letter_data()
│
├── 🐳 Docker Files
│   ├── Dockerfile                 # Imagen Docker
│   ├── docker-compose.yml         # Orquestación
│   ├── .dockerignore              # Archivos a ignorar
│   └── .env.example               # Variables de entorno ejemplo
│
├── 📦 Configuración
│   ├── requirements.txt           # Dependencias Python
│   └── .gitignore                 # Git ignore
│
├── 📚 Documentación
│   ├── README.md                  # Documentación principal
│   ├── QUICK_START.md             # Guía de inicio rápido
│   └── ESTRUCTURA.md              # Este archivo
│
└── 🧪 Testing
    └── test_service.py            # Script de pruebas

```

## 🔧 Tecnologías Utilizadas

### Core
- **FastAPI** - Framework web moderno y rápido
- **Uvicorn** - Servidor ASGI
- **Pydantic** - Validación de datos

### Procesamiento de PDFs
- **PyPDF2** - Lectura y extracción de texto nativo
- **pdf2image** - Conversión de PDF a imágenes
- **Poppler** - Librería subyacente para conversión

### OCR (Reconocimiento Óptico de Caracteres)
- **Tesseract OCR** - Motor OCR básico (rápido)
- **EasyOCR** - Motor OCR avanzado (preciso)
- **pytesseract** - Wrapper Python para Tesseract

### Procesamiento de Imágenes
- **Pillow (PIL)** - Manipulación de imágenes
- **OpenCV** - Procesamiento avanzado de imágenes
- **NumPy** - Operaciones numéricas

### Utilidades
- **python-multipart** - Manejo de archivos multipart
- **aiofiles** - Operaciones async de archivos
- **python-dotenv** - Variables de entorno

## 🎯 Flujo de Procesamiento

### 1. Recepción de PDF

```
Usuario → POST /process-pdf → FastAPI
                                 ↓
                         Guardar archivo temporal
```

### 2. Extracción de Texto

```
PDF Temporal → PDFProcessor
                    ↓
            ¿Tiene texto nativo?
                    ├─ SÍ → Extraer texto con PyPDF2
                    └─ NO → Continuar a OCR
```

### 3. OCR (si es necesario)

```
PDF sin texto → Convertir a imágenes (pdf2image)
                         ↓
              ImageProcessor (optimizar)
                         ↓
            ¿Usar OCR avanzado?
                ├─ SÍ → EasyOCR (preciso, lento)
                └─ NO → Tesseract (rápido, menos preciso)
                         ↓
                  Texto extraído
```

### 4. Extracción de Datos Estructurados

```
Texto extraído → DataExtractor
                      ↓
              Según tipo de documento
                      ├─ bank_statement
                      ├─ payroll
                      ├─ id_document
                      ├─ tax_return
                      ├─ proof_of_address
                      └─ employment_letter
                      ↓
              Datos estructurados (JSON)
```

### 5. Respuesta

```
{
  "extracted_text": "...",
  "extracted_data": {...},
  "confidence": 92.5,
  "success": true
}
```

## 📊 Tipos de Datos Extraídos

### Estado de Cuenta Bancario
- Nombre del banco
- Número de cuenta
- Saldo actual
- Ingresos mensuales
- Gastos mensuales
- Tasa de ahorro
- Titular de la cuenta

### Recibo de Nómina
- Nombre del empleado
- RFC
- Empresa
- Salario bruto
- Salario neto
- Periodo de pago
- Fecha de pago
- Deducciones

### Identificación (INE/IFE)
- Nombre completo
- CURP
- Clave de elector
- Domicilio
- Fecha de nacimiento
- Fecha de vigencia

### Declaración Fiscal
- RFC
- Ingresos anuales
- Año fiscal

### Comprobante de Domicilio
- Dirección
- Titular
- Tipo de servicio (CFE, Telmex, etc.)

### Carta Laboral
- Nombre de la empresa
- Puesto
- Fecha de ingreso

## 🚀 Endpoints API

### GET /
**Info del servicio**

Respuesta:
```json
{
  "service": "HAVI Score PDF Processor",
  "status": "running",
  "version": "1.0.0"
}
```

### GET /health
**Health check detallado**

Respuesta:
```json
{
  "status": "healthy",
  "services": {
    "pdf_processor": "ready",
    "ocr_service": "ready",
    "image_processor": "ready"
  }
}
```

### POST /process-pdf
**Procesar documento PDF**

Parámetros:
- `file` (required): Archivo PDF
- `document_type` (optional): Tipo de documento
- `use_advanced_ocr` (optional): true/false
- `extract_images` (optional): true/false

Respuesta: `ProcessedDocument`

### POST /process-image
**Procesar imagen con OCR**

Parámetros:
- `file` (required): Archivo de imagen
- `use_advanced_ocr` (optional): true/false

Respuesta: `OCRResult`

### POST /extract-structured-data
**Extraer datos estructurados**

Parámetros:
- `file` (required): Archivo PDF
- `document_type` (required): Tipo de documento

Respuesta: `StructuredDataResult`

## 🔐 Variables de Entorno

```bash
# Logging
LOG_LEVEL=INFO

# OCR
TESSERACT_LANG=spa+eng
USE_GPU=false

# API
API_HOST=0.0.0.0
API_PORT=8000

# Performance
MAX_WORKERS=4
TIMEOUT_SECONDS=120

# CORS
CORS_ORIGINS=http://localhost:3333,http://localhost:3000
```

## 📈 Métricas de Performance

### Tiempos Promedio

| Operación | Tiempo |
|-----------|--------|
| PDF con texto nativo (3 pág) | 1-2 seg |
| PDF escaneado con Tesseract (3 pág) | 5-8 seg |
| PDF escaneado con EasyOCR (3 pág) | 12-18 seg |
| Imagen con Tesseract | 2-3 seg |
| Imagen con EasyOCR | 4-6 seg |

### Consumo de Recursos

| Componente | RAM | CPU |
|------------|-----|-----|
| Base (FastAPI) | ~50 MB | 1-5% |
| Tesseract (procesando) | ~100 MB | 50-80% |
| EasyOCR (inicialización) | ~500 MB | - |
| EasyOCR (procesando) | ~700 MB | 80-100% |

## 🎓 Patrones de Diseño Utilizados

1. **Dependency Injection** - Servicios inyectados en endpoints
2. **Service Layer** - Lógica de negocio separada
3. **DTO Pattern** - Modelos Pydantic para transferencia de datos
4. **Strategy Pattern** - Múltiples estrategias de OCR
5. **Factory Pattern** - Creación de procesadores según tipo
6. **Singleton** - Instancia única de servicios

## 🛡️ Manejo de Errores

- Todos los endpoints tienen manejo de excepciones
- Errores retornan HTTPException con status apropiado
- Logs detallados para debugging
- Cleanup automático de archivos temporales
- Fallback a métodos alternativos

## ✅ Best Practices Implementadas

- ✅ Type hints en todo el código
- ✅ Documentación de funciones
- ✅ Separación de concerns
- ✅ Validación de entrada con Pydantic
- ✅ Logging estructurado
- ✅ Manejo robusto de errores
- ✅ Cleanup de recursos
- ✅ API RESTful
- ✅ Docker para portabilidad
- ✅ Variables de entorno para configuración

---

**Versión**: 1.0.0
**Última actualización**: Diciembre 2024
