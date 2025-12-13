# 🎯 Ejemplos Prácticos - PDF Processor Service

Ejemplos de uso real del microservicio de procesamiento de PDFs.

## 📝 Tabla de Contenidos

1. [Procesamiento Básico](#procesamiento-básico)
2. [Procesamiento Avanzado](#procesamiento-avanzado)
3. [Integración con AdonisJS](#integración-con-adonisjs)
4. [Casos de Uso Reales](#casos-de-uso-reales)
5. [Optimización y Performance](#optimización-y-performance)

---

## 📄 Procesamiento Básico

### Ejemplo 1: Estado de Cuenta Bancario

```bash
curl -X POST http://localhost:8000/process-pdf \
  -F "file=@estado_cuenta_bbva.pdf" \
  -F "document_type=bank_statement" \
  -F "use_advanced_ocr=true"
```

**Respuesta:**
```json
{
  "filename": "estado_cuenta_bbva.pdf",
  "document_type": "bank_statement",
  "num_pages": 3,
  "extracted_text": "BBVA Bancomer\nEstado de Cuenta\n...",
  "ocr_confidence": 92.5,
  "text_length": 5420,
  "processing_method": "native",
  "document_analysis": {
    "keywords_found": ["banco", "saldo", "cuenta", "balance", "transacción"],
    "estimated_quality": "high",
    "suggestions": []
  },
  "success": true
}
```

### Ejemplo 2: Recibo de Nómina

```bash
curl -X POST http://localhost:8000/extract-structured-data \
  -F "file=@recibo_nomina.pdf" \
  -F "document_type=payroll"
```

**Respuesta:**
```json
{
  "document_type": "payroll",
  "extracted_data": {
    "employee_name": "JUAN PEREZ GARCIA",
    "employee_rfc": "PEGJ850101ABC",
    "employer_name": "EMPRESA EJEMPLO S.A. DE C.V.",
    "gross_salary": 18500.0,
    "net_salary": 14250.0,
    "payment_period": "01/11/2024 - 15/11/2024"
  },
  "confidence": 88.3,
  "analysis": {
    "keywords_found": ["nómina", "salario", "imss", "rfc"],
    "estimated_quality": "high"
  }
}
```

### Ejemplo 3: INE/Credencial de Elector

```bash
curl -X POST http://localhost:8000/process-image \
  -F "file=@ine_frente.jpg" \
  -F "use_advanced_ocr=true"
```

**Respuesta:**
```json
{
  "filename": "ine_frente.jpg",
  "text": "INSTITUTO NACIONAL ELECTORAL\nNOMBRE: JUAN PEREZ GARCIA\nCURP: PEGJ850101HDFRNN01\n...",
  "confidence": 91.7,
  "method": "easyocr",
  "success": true
}
```

---

## 🚀 Procesamiento Avanzado

### Ejemplo 4: PDF Escaneado de Baja Calidad

Para PDFs escaneados o de baja calidad, es mejor usar OCR avanzado:

```python
import requests

# Archivo con baja calidad
with open('estado_cuenta_escaneado.pdf', 'rb') as f:
    files = {'file': f}
    data = {
        'document_type': 'bank_statement',
        'use_advanced_ocr': 'true',  # EasyOCR para mejor precisión
        'extract_images': 'true'
    }

    response = requests.post(
        'http://localhost:8000/process-pdf',
        files=files,
        data=data,
        timeout=180  # 3 minutos para documentos grandes
    )

    result = response.json()
    print(f"Confianza: {result['ocr_confidence']}%")
    print(f"Método: {result['processing_method']}")
    print(f"Texto extraído: {result['text_length']} caracteres")
```

### Ejemplo 5: Procesamiento Batch

```python
import requests
import os
from pathlib import Path

def process_directory(directory_path, document_type):
    """Procesa todos los PDFs en un directorio"""

    results = []
    pdf_files = list(Path(directory_path).glob('*.pdf'))

    print(f"📁 Procesando {len(pdf_files)} archivos...")

    for i, pdf_path in enumerate(pdf_files, 1):
        print(f"\n[{i}/{len(pdf_files)}] Procesando: {pdf_path.name}")

        try:
            with open(pdf_path, 'rb') as f:
                files = {'file': f}
                data = {
                    'document_type': document_type,
                    'use_advanced_ocr': 'true'
                }

                response = requests.post(
                    'http://localhost:8000/extract-structured-data',
                    files=files,
                    data=data,
                    timeout=120
                )

                if response.status_code == 200:
                    result = response.json()
                    results.append({
                        'filename': pdf_path.name,
                        'success': True,
                        'data': result['extracted_data'],
                        'confidence': result['confidence']
                    })
                    print(f"  ✅ Confianza: {result['confidence']:.1f}%")
                else:
                    results.append({
                        'filename': pdf_path.name,
                        'success': False,
                        'error': response.text
                    })
                    print(f"  ❌ Error: {response.status_code}")

        except Exception as e:
            results.append({
                'filename': pdf_path.name,
                'success': False,
                'error': str(e)
            })
            print(f"  ❌ Excepción: {e}")

    return results

# Usar la función
results = process_directory('./estados_cuenta', 'bank_statement')

# Resumen
successful = sum(1 for r in results if r['success'])
print(f"\n📊 Resumen: {successful}/{len(results)} procesados exitosamente")
```

---

## 🔗 Integración con AdonisJS

### Ejemplo 6: Cliente TypeScript Completo

```typescript
// app/services/pdf_processor_client.ts

import axios from 'axios'
import FormData from 'form-data'
import { createReadStream } from 'fs'
import fs from 'fs/promises'
import env from '#start/env'

export class PdfProcessorClient {
  private baseUrl: string
  private timeout: number

  constructor() {
    this.baseUrl = env.get('PDF_PROCESSOR_URL', 'http://localhost:8000')
    this.timeout = 120000
  }

  /**
   * Procesa un estado de cuenta bancario
   */
  async processBankStatement(filePath: string) {
    const result = await this.processPdf(filePath, 'bank_statement', true)

    // Extraer datos específicos
    const extractedData = this.parseBankStatement(result.extracted_text)

    return {
      ...result,
      structuredData: extractedData
    }
  }

  /**
   * Procesa un recibo de nómina
   */
  async processPayroll(filePath: string) {
    return await this.extractStructuredData(filePath, 'payroll')
  }

  /**
   * Procesa una identificación
   */
  async processIdDocument(imagePath: string) {
    return await this.extractStructuredData(imagePath, 'id_document')
  }

  /**
   * Procesa cualquier PDF
   */
  async processPdf(
    filePath: string,
    documentType: string,
    useAdvancedOcr: boolean = true
  ) {
    const formData = new FormData()
    formData.append('file', createReadStream(filePath))
    formData.append('document_type', documentType)
    formData.append('use_advanced_ocr', useAdvancedOcr.toString())

    const response = await axios.post(
      `${this.baseUrl}/process-pdf`,
      formData,
      {
        headers: formData.getHeaders(),
        timeout: this.timeout
      }
    )

    return response.data
  }

  /**
   * Extrae datos estructurados
   */
  async extractStructuredData(filePath: string, documentType: string) {
    const formData = new FormData()
    formData.append('file', createReadStream(filePath))
    formData.append('document_type', documentType)

    const response = await axios.post(
      `${this.baseUrl}/extract-structured-data`,
      formData,
      {
        headers: formData.getHeaders(),
        timeout: this.timeout
      }
    )

    return response.data
  }

  /**
   * Parser personalizado para estado de cuenta
   */
  private parseBankStatement(text: string) {
    // Implementar lógica personalizada si es necesario
    return {
      rawText: text
    }
  }
}

export const pdfProcessorClient = new PdfProcessorClient()
```

### Ejemplo 7: Uso en Controller

```typescript
// app/controllers/document_controller.ts

import { HttpContext } from '@adonisjs/core/http'
import DocumentUpload from '#models/document_upload'
import { pdfProcessorClient } from '#services/pdf_processor_client'
import { s3Service } from '#services/s3_service'
import fs from 'fs/promises'

export default class DocumentController {
  async upload({ request, auth, response }: HttpContext) {
    const user = auth.user!
    const file = request.file('file', {
      size: '10mb',
      extnames: ['pdf', 'jpg', 'jpeg', 'png']
    })

    if (!file) {
      return response.badRequest({ error: 'No file provided' })
    }

    try {
      // 1. Guardar en S3
      const s3Path = `documents/${user.id}/${Date.now()}_${file.clientName}`
      await s3Service.uploadPrivateFile(file, s3Path)

      // 2. Crear registro en DB
      const documentUpload = await DocumentUpload.create({
        userId: user.id,
        fileName: file.clientName,
        filePath: s3Path,
        mimeType: file.type,
        fileSize: file.size,
        documentType: request.input('documentType'),
        status: 'pending'
      })

      // 3. Procesar con microservicio Python (async)
      this.processDocumentAsync(documentUpload)

      return response.created({
        message: 'Document uploaded successfully',
        document: documentUpload
      })

    } catch (error) {
      console.error('Error uploading document:', error)
      return response.internalServerError({ error: 'Upload failed' })
    }
  }

  /**
   * Procesa documento de forma asíncrona
   */
  private async processDocumentAsync(documentUpload: DocumentUpload) {
    try {
      // Descargar de S3 a temporal
      const tempPath = await this.downloadToTemp(documentUpload.filePath)

      // Procesar con microservicio
      const result = await pdfProcessorClient.extractStructuredData(
        tempPath,
        documentUpload.documentType
      )

      // Actualizar documento
      documentUpload.extractedData = result.extracted_data
      documentUpload.confidence = result.confidence
      documentUpload.status = result.confidence >= 70 ? 'processed' : 'needs_review'
      documentUpload.processingNotes = `Procesado con microservicio Python. Confianza: ${result.confidence}%`
      await documentUpload.save()

      // Limpiar temporal
      await fs.unlink(tempPath)

      console.log(`✅ Documento ${documentUpload.id} procesado exitosamente`)

    } catch (error) {
      console.error(`❌ Error procesando documento ${documentUpload.id}:`, error)

      documentUpload.status = 'failed'
      documentUpload.processingNotes = `Error: ${error.message}`
      await documentUpload.save()
    }
  }

  private async downloadToTemp(s3Key: string): Promise<string> {
    // Implementar descarga de S3 a archivo temporal
    // (Ver INTEGRACION_PDF_PROCESSOR.md para código completo)
  }
}
```

---

## 💼 Casos de Uso Reales

### Caso 1: Análisis Crediticio Completo

```typescript
// app/services/credit_analysis_service.ts

import { pdfProcessorClient } from '#services/pdf_processor_client'
import User from '#models/user'
import DocumentUpload from '#models/document_upload'

export class CreditAnalysisService {
  /**
   * Analiza perfil crediticio completo de un usuario
   */
  async analyzeUserProfile(userId: number) {
    const user = await User.findOrFail(userId)

    // Obtener documentos del usuario
    const documents = await DocumentUpload.query()
      .where('user_id', userId)
      .where('status', 'processed')

    const analysis = {
      userId,
      documents: [],
      bankStatements: [],
      payrolls: [],
      identifications: [],
      overallScore: 0
    }

    // Procesar cada documento
    for (const doc of documents) {
      const tempPath = await this.downloadToTemp(doc.filePath)

      try {
        const result = await pdfProcessorClient.extractStructuredData(
          tempPath,
          doc.documentType
        )

        analysis.documents.push({
          id: doc.id,
          type: doc.documentType,
          data: result.extracted_data,
          confidence: result.confidence
        })

        // Clasificar por tipo
        if (doc.documentType === 'bank_statement') {
          analysis.bankStatements.push(result.extracted_data)
        } else if (doc.documentType === 'payroll') {
          analysis.payrolls.push(result.extracted_data)
        }

      } catch (error) {
        console.error(`Error procesando documento ${doc.id}:`, error)
      }
    }

    // Calcular score
    analysis.overallScore = this.calculateHaviScore(analysis)

    return analysis
  }

  private calculateHaviScore(analysis: any): number {
    let score = 300 // Base score

    // Analizar estados de cuenta
    if (analysis.bankStatements.length > 0) {
      const avgBalance = analysis.bankStatements.reduce(
        (sum, bs) => sum + (bs.balance || 0), 0
      ) / analysis.bankStatements.length

      if (avgBalance >= 50000) score += 150
      else if (avgBalance >= 20000) score += 100
      else if (avgBalance >= 10000) score += 50
    }

    // Analizar nóminas
    if (analysis.payrolls.length > 0) {
      const avgSalary = analysis.payrolls.reduce(
        (sum, p) => sum + (p.net_salary || 0), 0
      ) / analysis.payrolls.length

      if (avgSalary >= 25000) score += 200
      else if (avgSalary >= 15000) score += 150
      else if (avgSalary >= 10000) score += 100
    }

    // Documentos completos
    if (analysis.documents.length >= 5) score += 100

    return Math.min(score, 850) // Máximo 850
  }
}
```

### Caso 2: Validación de INE en Tiempo Real

```typescript
// app/controllers/ine_validation_controller.ts

import { HttpContext } from '@adonisjs/core/http'
import { pdfProcessorClient } from '#services/pdf_processor_client'

export default class IneValidationController {
  /**
   * Valida una credencial INE
   */
  async validate({ request, response }: HttpContext) {
    const frontImage = request.file('front_image')
    const backImage = request.file('back_image')

    if (!frontImage || !backImage) {
      return response.badRequest({ error: 'Both images required' })
    }

    try {
      // Guardar temporalmente
      const frontPath = `/tmp/ine_front_${Date.now()}.jpg`
      const backPath = `/tmp/ine_back_${Date.now()}.jpg`

      await frontImage.move(frontPath)
      await backImage.move(backPath)

      // Procesar con OCR
      const [frontResult, backResult] = await Promise.all([
        pdfProcessorClient.extractStructuredData(frontPath, 'id_document'),
        pdfProcessorClient.extractStructuredData(backPath, 'id_document')
      ])

      // Validar datos
      const validation = this.validateIneData(
        frontResult.extracted_data,
        backResult.extracted_data
      )

      return response.ok({
        frontData: frontResult.extracted_data,
        backData: backResult.extracted_data,
        validation,
        confidence: (frontResult.confidence + backResult.confidence) / 2
      })

    } catch (error) {
      console.error('Error validating INE:', error)
      return response.internalServerError({ error: 'Validation failed' })
    }
  }

  private validateIneData(front: any, back: any) {
    const checks = {
      hasCurp: !!front.curp || !!back.curp,
      hasVoterId: !!front.voter_id,
      hasName: !!front.full_name,
      hasAddress: !!front.address || !!back.address,
      isValid: false
    }

    checks.isValid = checks.hasCurp && checks.hasVoterId && checks.hasName

    return checks
  }
}
```

---

## ⚡ Optimización y Performance

### Ejemplo 8: Cache de Resultados

```typescript
// app/services/pdf_cache_service.ts

import redis from '@adonisjs/redis/services/main'
import crypto from 'crypto'

export class PdfCacheService {
  /**
   * Genera hash del archivo para cache
   */
  private async getFileHash(filePath: string): Promise<string> {
    const fs = await import('fs/promises')
    const buffer = await fs.readFile(filePath)
    return crypto.createHash('md5').update(buffer).digest('hex')
  }

  /**
   * Buscar en cache
   */
  async getCached(filePath: string, documentType: string) {
    const hash = await this.getFileHash(filePath)
    const cacheKey = `pdf:${documentType}:${hash}`

    const cached = await redis.get(cacheKey)

    if (cached) {
      console.log('📦 Cache hit!')
      return JSON.parse(cached)
    }

    return null
  }

  /**
   * Guardar en cache
   */
  async setCached(
    filePath: string,
    documentType: string,
    result: any,
    ttl: number = 3600
  ) {
    const hash = await this.getFileHash(filePath)
    const cacheKey = `pdf:${documentType}:${hash}`

    await redis.setex(cacheKey, ttl, JSON.stringify(result))
    console.log('💾 Guardado en cache')
  }

  /**
   * Wrapper con cache
   */
  async processWithCache(
    filePath: string,
    documentType: string,
    processor: () => Promise<any>
  ) {
    // Buscar en cache
    const cached = await this.getCached(filePath, documentType)
    if (cached) return cached

    // Procesar
    const result = await processor()

    // Guardar en cache
    await this.setCached(filePath, documentType, result)

    return result
  }
}

// Uso:
const cacheService = new PdfCacheService()

const result = await cacheService.processWithCache(
  tempPath,
  'bank_statement',
  () => pdfProcessorClient.extractStructuredData(tempPath, 'bank_statement')
)
```

### Ejemplo 9: Procesamiento en Queue

```typescript
// app/jobs/process_document_job.ts

import { Job } from '@adonisjs/bull'
import DocumentUpload from '#models/document_upload'
import { pdfProcessorClient } from '#services/pdf_processor_client'

export default class ProcessDocumentJob extends Job {
  async handle(payload: { documentId: number }) {
    const document = await DocumentUpload.findOrFail(payload.documentId)

    try {
      document.status = 'processing'
      await document.save()

      // Descargar y procesar
      const tempPath = await this.downloadToTemp(document.filePath)

      const result = await pdfProcessorClient.extractStructuredData(
        tempPath,
        document.documentType
      )

      // Actualizar
      document.extractedData = result.extracted_data
      document.confidence = result.confidence
      document.status = 'processed'
      await document.save()

      console.log(`✅ Job completado para documento ${document.id}`)

    } catch (error) {
      console.error(`❌ Job falló para documento ${document.id}:`, error)

      document.status = 'failed'
      document.processingNotes = error.message
      await document.save()
    }
  }
}

// Dispatcher:
import ProcessDocumentJob from '#jobs/process_document_job'
import Bull from '@adonisjs/bull/services/main'

// Encolar procesamiento
await Bull.dispatch(ProcessDocumentJob, { documentId: document.id })
```

---

## 🎓 Tips y Mejores Prácticas

### 1. Manejo de Timeouts

```typescript
// Para documentos grandes, aumentar timeout
const result = await axios.post(url, formData, {
  timeout: 300000  // 5 minutos
})
```

### 2. Retry Logic

```typescript
async function processWithRetry(filePath: string, maxRetries = 3) {
  for (let i = 0; i < maxRetries; i++) {
    try {
      return await pdfProcessorClient.processPdf(filePath, 'bank_statement')
    } catch (error) {
      if (i === maxRetries - 1) throw error
      console.log(`Retry ${i + 1}/${maxRetries}...`)
      await new Promise(resolve => setTimeout(resolve, 2000))
    }
  }
}
```

### 3. Procesamiento Selectivo

```typescript
// Usar OCR básico para documentos simples (más rápido)
if (documentType === 'employment_letter') {
  return await pdfProcessorClient.processPdf(filePath, documentType, false)
}

// Usar OCR avanzado solo para documentos críticos
if (documentType === 'id_document' || documentType === 'bank_statement') {
  return await pdfProcessorClient.processPdf(filePath, documentType, true)
}
```

---

**¿Más ejemplos?** Contacta al equipo de desarrollo.
