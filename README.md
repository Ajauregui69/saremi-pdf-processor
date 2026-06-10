# ðŸ” Microservicio de Procesamiento de PDFs - HAVI Score

Microservicio Python especializado en procesamiento avanzado de documentos PDF para el sistema de scoring crediticio HAVI. Extrae texto e imÃ¡genes de documentos financieros para facilitar el anÃ¡lisis de IA.

## ðŸŽ¯ CaracterÃ­sticas

- **Procesamiento de PDFs**: ExtracciÃ³n de texto nativo y conversiÃ³n a imÃ¡genes
- **OCR Avanzado**: Doble motor (Tesseract + EasyOCR) para mÃ¡xima precisiÃ³n
- **Procesamiento de ImÃ¡genes**: OptimizaciÃ³n automÃ¡tica para mejorar OCR
- **ExtracciÃ³n de Datos**: Datos estructurados segÃºn tipo de documento
- **Alta Performance**: Procesamiento asÃ­ncrono y optimizado
- **API REST**: IntegraciÃ³n fÃ¡cil con cualquier backend

## ðŸ—ï¸ Arquitectura

```
pdf-processor-service/
â”œâ”€â”€ main.py                     # AplicaciÃ³n FastAPI principal
â”œâ”€â”€ models/
â”‚   â””â”€â”€ schemas.py              # Modelos Pydantic
â”œâ”€â”€ services/
â”‚   â”œâ”€â”€ pdf_processor.py        # Procesamiento de PDFs
â”‚   â”œâ”€â”€ ocr_service.py          # OCR (Tesseract + EasyOCR)
â”‚   â”œâ”€â”€ image_processor.py      # Procesamiento de imÃ¡genes
â”‚   â””â”€â”€ data_extractor.py       # ExtracciÃ³n de datos estructurados
â”œâ”€â”€ Dockerfile                  # Imagen Docker
â”œâ”€â”€ docker-compose.yml          # OrquestaciÃ³n
â”œâ”€â”€ requirements.txt            # Dependencias Python
â””â”€â”€ README.md                   # DocumentaciÃ³n
```

## ðŸš€ InstalaciÃ³n

### OpciÃ³n 1: Docker (Recomendado)

```bash
# Construir imagen
docker-compose build

# Iniciar servicio
docker-compose up -d

# Ver logs
docker-compose logs -f
```

El servicio estarÃ¡ disponible en: `http://localhost:8000`

### OpciÃ³n 2: InstalaciÃ³n Local

#### Requisitos del Sistema

- Python 3.11+
- Tesseract OCR
- Poppler (para pdf2image)

**Ubuntu/Debian:**
```bash
sudo apt-get update
sudo apt-get install -y tesseract-ocr tesseract-ocr-spa tesseract-ocr-eng poppler-utils
```

**macOS:**
```bash
brew install tesseract tesseract-lang poppler
```

**Windows:**
- Instalar Tesseract: https://github.com/UB-Mannheim/tesseract/wiki
- Instalar Poppler: https://blog.alivate.com.au/poppler-windows/

#### InstalaciÃ³n de Python

```bash
# Crear entorno virtual
python -m venv venv

# Activar entorno
source venv/bin/activate  # Linux/Mac
# o
venv\Scripts\activate  # Windows

# Instalar dependencias
pip install -r requirements.txt

# Ejecutar servicio
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## ðŸ“š API Endpoints

### 1. Health Check

```bash
GET /health
```

**Respuesta:**
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

### 2. Procesar PDF

```bash
POST /process-pdf
Content-Type: multipart/form-data

file: [PDF file]
document_type: bank_statement
use_advanced_ocr: true
extract_images: true
```

**Ejemplo con curl:**
```bash
curl -X POST http://localhost:8000/process-pdf \
  -F "file=@estado_cuenta.pdf" \
  -F "document_type=bank_statement" \
  -F "use_advanced_ocr=true" \
  -F "extract_images=true"
```

**Respuesta:**
```json
{
  "filename": "estado_cuenta.pdf",
  "document_type": "bank_statement",
  "num_pages": 3,
  "extracted_text": "Texto extraÃ­do del PDF...",
  "native_text": "Texto nativo del PDF...",
  "ocr_text": "Texto adicional del OCR...",
  "ocr_confidence": 92.5,
  "num_images": 3,
  "num_extracted_images": 2,
  "text_length": 5420,
  "processing_method": "native",
  "document_analysis": {
    "keywords_found": ["banco", "saldo", "cuenta", "balance"],
    "estimated_quality": "high",
    "suggestions": []
  },
  "success": true
}
```

### 3. Procesar Imagen

```bash
POST /process-image
Content-Type: multipart/form-data

file: [Image file]
use_advanced_ocr: true
```

**Ejemplo:**
```bash
curl -X POST http://localhost:8000/process-image \
  -F "file=@ine.jpg" \
  -F "use_advanced_ocr=true"
```

**Respuesta:**
```json
{
  "filename": "ine.jpg",
  "text": "INSTITUTO NACIONAL ELECTORAL...",
  "confidence": 88.3,
  "method": "easyocr",
  "success": true
}
```

### 4. Extraer Datos Estructurados

```bash
POST /extract-structured-data
Content-Type: multipart/form-data

file: [PDF file]
document_type: bank_statement
```

**Ejemplo:**
```bash
curl -X POST http://localhost:8000/extract-structured-data \
  -F "file=@estado_cuenta.pdf" \
  -F "document_type=bank_statement"
```

**Respuesta:**
```json
{
  "document_type": "bank_statement",
  "extracted_data": {
    "bank_name": "BBVA",
    "account_number": "0123456789",
    "balance": 45000.0,
    "monthly_income": 25000.0,
    "monthly_expenses": 18000.0,
    "savings_rate": 28.0,
    "account_holder": "JUAN PEREZ GARCIA"
  },
  "confidence": 92.5,
  "analysis": {
    "keywords_found": ["banco", "saldo", "cuenta", "balance"],
    "estimated_quality": "high"
  }
}
```

## ðŸ“„ Tipos de Documentos Soportados

| Tipo | CÃ³digo | Datos ExtraÃ­dos |
|------|--------|-----------------|
| Estado de Cuenta | `bank_statement` | Banco, cuenta, saldo, ingresos, gastos |
| Recibo de NÃ³mina | `payroll` | RFC, empresa, salario bruto/neto, periodo |
| IdentificaciÃ³n | `id_document` | CURP, nombre, domicilio, vigencia |
| DeclaraciÃ³n Fiscal | `tax_return` | RFC, ingresos anuales, aÃ±o fiscal |
| Comprobante Domicilio | `proof_of_address` | DirecciÃ³n, titular, tipo de servicio |
| Carta Laboral | `employment_letter` | Empresa, puesto, fecha de ingreso |

## ðŸ”§ IntegraciÃ³n con Backend AdonisJS

### Crear Servicio de IntegraciÃ³n

Crear archivo: `app/services/pdf_processor_client.ts`

```typescript
import axios from 'axios'
import FormData from 'form-data'
import fs from 'fs'

class PdfProcessorClient {
  private baseUrl: string

  constructor() {
    this.baseUrl = process.env.PDF_PROCESSOR_URL || 'http://localhost:8000'
  }

  /**
   * Procesa un PDF y extrae texto
   */
  async processPdf(
    filePath: string,
    documentType: string,
    useAdvancedOcr: boolean = true
  ): Promise<any> {
    try {
      const formData = new FormData()
      formData.append('file', fs.createReadStream(filePath))
      formData.append('document_type', documentType)
      formData.append('use_advanced_ocr', useAdvancedOcr.toString())
      formData.append('extract_images', 'true')

      const response = await axios.post(`${this.baseUrl}/process-pdf`, formData, {
        headers: formData.getHeaders(),
        timeout: 120000 // 2 minutos
      })

      return response.data
    } catch (error) {
      console.error('Error procesando PDF:', error)
      throw error
    }
  }

  /**
   * Extrae datos estructurados de un PDF
   */
  async extractStructuredData(filePath: string, documentType: string): Promise<any> {
    try {
      const formData = new FormData()
      formData.append('file', fs.createReadStream(filePath))
      formData.append('document_type', documentType)

      const response = await axios.post(
        `${this.baseUrl}/extract-structured-data`,
        formData,
        {
          headers: formData.getHeaders(),
          timeout: 120000
        }
      )

      return response.data
    } catch (error) {
      console.error('Error extrayendo datos:', error)
      throw error
    }
  }

  /**
   * Verifica salud del servicio
   */
  async healthCheck(): Promise<boolean> {
    try {
      const response = await axios.get(`${this.baseUrl}/health`, { timeout: 5000 })
      return response.data.status === 'healthy'
    } catch (error) {
      return false
    }
  }
}

export const pdfProcessorClient = new PdfProcessorClient()
```

### Actualizar Document Extraction Service

Modificar `app/services/document_extraction_service.ts`:

```typescript
import { pdfProcessorClient } from '#services/pdf_processor_client'

class DocumentExtractionService {
  private async getDocumentText(documentUpload: DocumentUpload): Promise<string | null> {
    try {
      // Intentar usar el microservicio Python primero
      const isHealthy = await pdfProcessorClient.healthCheck()

      if (isHealthy) {
        console.log('ðŸ Usando microservicio Python para procesamiento...')

        // Descargar archivo de S3 temporalmente
        const tempFilePath = await this.downloadFromS3(documentUpload.filePath)

        // Procesar con microservicio
        const result = await pdfProcessorClient.processPdf(
          tempFilePath,
          documentUpload.documentType,
          true // usar OCR avanzado
        )

        console.log(`âœ… Texto extraÃ­do: ${result.text_length} caracteres, confianza: ${result.ocr_confidence}%`)

        // Limpiar archivo temporal
        await fs.unlink(tempFilePath)

        return result.extracted_text
      } else {
        console.log('âš ï¸ Microservicio no disponible, usando mÃ©todo tradicional')
        // Fallback al mÃ©todo existente
        return await this.extractTextTraditional(documentUpload)
      }
    } catch (error) {
      console.error('Error con microservicio:', error)
      // Fallback
      return await this.extractTextTraditional(documentUpload)
    }
  }
}
```

### Variables de Entorno

Agregar a `.env`:

```bash
# Microservicio PDF Processor
PDF_PROCESSOR_URL=http://localhost:8000
PDF_PROCESSOR_ENABLED=true
```

## ðŸ§ª Testing

### Test Manual con curl

```bash
# 1. Health check
curl http://localhost:8000/health

# 2. Procesar PDF de prueba
curl -X POST http://localhost:8000/process-pdf \
  -F "file=@test.pdf" \
  -F "document_type=bank_statement" \
  -F "use_advanced_ocr=true"

# 3. Procesar imagen
curl -X POST http://localhost:8000/process-image \
  -F "file=@test.jpg" \
  -F "use_advanced_ocr=true"
```

### Test con Python

```python
import requests

# Procesar PDF
with open('estado_cuenta.pdf', 'rb') as f:
    files = {'file': f}
    data = {
        'document_type': 'bank_statement',
        'use_advanced_ocr': 'true'
    }
    response = requests.post('http://localhost:8000/process-pdf', files=files, data=data)
    print(response.json())
```

## ðŸ” ComparaciÃ³n OCR: Tesseract vs EasyOCR

| CaracterÃ­stica | Tesseract (BÃ¡sico) | EasyOCR (Avanzado) |
|----------------|--------------------|--------------------|
| Velocidad | âš¡ RÃ¡pido (1-2 seg/pÃ¡gina) | ðŸ¢ MÃ¡s lento (3-5 seg/pÃ¡gina) |
| PrecisiÃ³n | ðŸ“Š 70-85% | ðŸ“Š 85-95% |
| Idiomas | âœ… EspaÃ±ol + InglÃ©s | âœ… 80+ idiomas |
| GPU | âŒ No soportado | âœ… AceleraciÃ³n GPU |
| Uso de Memoria | ðŸ’š Bajo (~100 MB) | ðŸ’› Alto (~500 MB) |
| Mejor para | Documentos limpios | Documentos complejos |

**RecomendaciÃ³n**: Usar EasyOCR para documentos crÃ­ticos (INE, estados de cuenta) y Tesseract para documentos simples.

## âš™ï¸ ConfiguraciÃ³n Avanzada

### Optimizar para ProducciÃ³n

```python
# En main.py, configurar workers
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        workers=4,  # MÃºltiples workers
        log_level="info"
    )
```

### Configurar Timeout

```python
# En docker-compose.yml
environment:
  - TIMEOUT_SECONDS=180  # 3 minutos para PDFs grandes
```

## ðŸ“Š Monitoreo

### Logs

```bash
# Ver logs en tiempo real
docker-compose logs -f pdf-processor

# Filtrar errores
docker-compose logs pdf-processor | grep ERROR
```

### MÃ©tricas

El servicio loguea informaciÃ³n Ãºtil:

```
ðŸ“„ Procesando PDF: estado_cuenta.pdf, tipo: bank_statement
ðŸ“ Archivo guardado temporalmente
ðŸ“ Extrayendo texto nativo...
ðŸ“Š PDF Info: 3 pÃ¡ginas
ðŸ–¼ï¸ Convirtiendo PDF a imÃ¡genes...
âœ… Generadas 3 imÃ¡genes
ðŸ” Texto nativo insuficiente, aplicando OCR...
âœ¨ OCR avanzado completado - Confianza: 92.5%
âœ… Procesamiento completado - 5420 caracteres extraÃ­dos
```

## ðŸ› ï¸ Troubleshooting

### Error: Tesseract no encontrado

```bash
# Ubuntu/Debian
sudo apt-get install tesseract-ocr tesseract-ocr-spa

# Verificar instalaciÃ³n
tesseract --version
```

### Error: Poppler no instalado

```bash
# Ubuntu/Debian
sudo apt-get install poppler-utils

# Verificar
pdftoppm -v
```

### Error: Out of Memory con EasyOCR

Reducir resoluciÃ³n de imÃ¡genes en `services/pdf_processor.py`:

```python
self.dpi = 200  # En lugar de 300
```

## ðŸš€ Performance

### Tiempos de Procesamiento Estimados

| Tipo | PÃ¡ginas | Tesseract | EasyOCR |
|------|---------|-----------|---------|
| PDF con texto nativo | 3 | 1 seg | 1 seg |
| PDF escaneado | 3 | 6 seg | 15 seg |
| Imagen alta calidad | 1 | 2 seg | 5 seg |

### Optimizaciones

1. **Usar texto nativo cuando sea posible** - El servicio automÃ¡ticamente detecta y usa texto nativo del PDF
2. **CachÃ© de modelos EasyOCR** - Los modelos se cargan una vez y se reutilizan
3. **Procesamiento paralelo** - Usar mÃºltiples workers en producciÃ³n
4. **Reducir DPI para PDFs grandes** - Configurar DPI segÃºn necesidad

## ðŸ“ Licencia

Propiedad de HAVI / SarEmi - Todos los derechos reservados.

## ðŸ¤ Soporte

Para problemas o dudas, contactar al equipo de desarrollo.
