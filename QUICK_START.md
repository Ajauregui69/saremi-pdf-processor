# ðŸš€ Quick Start - PDF Processor Service

GuÃ­a rÃ¡pida para poner en marcha el microservicio de procesamiento de PDFs.

## âš¡ Inicio RÃ¡pido (Docker)

```bash
# 1. Ir al directorio del microservicio
cd /home/alonso/projects/livo-backend/pdf-processor-service

# 2. Construir e iniciar
docker-compose up -d

# 3. Verificar que estÃ© corriendo
curl http://localhost:8000/health
```

âœ… **Listo!** El servicio estÃ¡ corriendo en http://localhost:8000

## ðŸ“ Inicio RÃ¡pido (Sin Docker)

### Requisitos

```bash
# Ubuntu/WSL
sudo apt-get update
sudo apt-get install -y tesseract-ocr tesseract-ocr-spa tesseract-ocr-eng poppler-utils

# Verificar instalaciÃ³n
tesseract --version
pdftoppm -v
```

### InstalaciÃ³n

```bash
# 1. Crear entorno virtual
python -m venv venv

# 2. Activar entorno
source venv/bin/activate  # Linux/Mac
# o
venv\Scripts\activate  # Windows

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Ejecutar servicio
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## ðŸ§ª Probar el Servicio

### Test 1: Health Check

```bash
curl http://localhost:8000/health
```

Respuesta esperada:
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

### Test 2: Procesar un PDF

```bash
# Usando el script de prueba
python test_service.py /path/to/your/document.pdf

# O usando curl directamente
curl -X POST http://localhost:8000/process-pdf \
  -F "file=@/path/to/document.pdf" \
  -F "document_type=bank_statement" \
  -F "use_advanced_ocr=true"
```

### Test 3: Procesar una Imagen

```bash
curl -X POST http://localhost:8000/process-image \
  -F "file=@/path/to/image.jpg" \
  -F "use_advanced_ocr=true"
```

## ðŸ”— IntegraciÃ³n con Backend

### 1. Variables de Entorno

Agregar al archivo `.env` del backend AdonisJS:

```bash
PDF_PROCESSOR_URL=http://localhost:8000
PDF_PROCESSOR_ENABLED=true
```

### 2. Verificar Conectividad

```bash
# Desde el directorio del backend
curl http://localhost:8000/health
```

### 3. Reiniciar Backend

```bash
# Detener backend actual (Ctrl+C)
# Reiniciar
node ace serve --hmr
```

### 4. Probar Flujo Completo

```bash
# Subir documento a travÃ©s del backend
curl -X POST http://localhost:3333/api/ai/documents/upload \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@estado_cuenta.pdf" \
  -F "documentType=bank_statement"
```

## ðŸ“Š Endpoints Disponibles

| Endpoint | MÃ©todo | DescripciÃ³n |
|----------|--------|-------------|
| `/` | GET | Info del servicio |
| `/health` | GET | Health check |
| `/process-pdf` | POST | Procesar PDF |
| `/process-image` | POST | Procesar imagen |
| `/extract-structured-data` | POST | Extraer datos estructurados |

## ðŸ› Troubleshooting

### Error: "Tesseract no encontrado"

```bash
# Ubuntu/WSL
sudo apt-get install tesseract-ocr tesseract-ocr-spa

# Verificar
which tesseract
tesseract --version
```

### Error: "Poppler no instalado"

```bash
# Ubuntu/WSL
sudo apt-get install poppler-utils

# Verificar
which pdftoppm
pdftoppm -v
```

### Error: "Puerto 8000 ya en uso"

```bash
# Ver quÃ© proceso usa el puerto
sudo lsof -i :8000

# Matar el proceso
kill -9 PID

# O cambiar el puerto
uvicorn main:app --port 8001
```

### Error: "Out of Memory con EasyOCR"

EasyOCR consume bastante memoria. Opciones:

1. **Usar Tesseract bÃ¡sico** (mÃ¡s ligero):
   ```bash
   curl -X POST http://localhost:8000/process-pdf \
     -F "file=@doc.pdf" \
     -F "use_advanced_ocr=false"  # Usar Tesseract solo
   ```

2. **Reducir DPI** en `services/pdf_processor.py`:
   ```python
   self.dpi = 200  # En lugar de 300
   ```

3. **Aumentar memoria del contenedor** en `docker-compose.yml`:
   ```yaml
   services:
     pdf-processor:
       deploy:
         resources:
           limits:
             memory: 2G  # Aumentar a 2GB
   ```

### Logs No Aparecen

```bash
# Docker
docker-compose logs -f pdf-processor

# Local
# Los logs aparecen en la terminal donde ejecutaste uvicorn
```

## ðŸŽ¯ Verificar que Todo Funciona

### Checklist

- [ ] Servicio responde en http://localhost:8000
- [ ] Health check retorna "healthy"
- [ ] Puede procesar un PDF de prueba
- [ ] Backend puede conectarse al microservicio
- [ ] Logs muestran actividad del procesamiento
- [ ] Documentos se procesan sin errores

### Script de VerificaciÃ³n Completa

```bash
#!/bin/bash

echo "ðŸ” Verificando microservicio PDF Processor..."

# 1. Health check
echo -n "1. Health check... "
HEALTH=$(curl -s http://localhost:8000/health | grep -o "healthy")
if [ "$HEALTH" == "healthy" ]; then
  echo "âœ…"
else
  echo "âŒ Servicio no disponible"
  exit 1
fi

# 2. Root endpoint
echo -n "2. Root endpoint... "
VERSION=$(curl -s http://localhost:8000 | grep -o "1.0.0")
if [ "$VERSION" == "1.0.0" ]; then
  echo "âœ…"
else
  echo "âŒ"
  exit 1
fi

echo ""
echo "âœ… Todos los checks pasaron!"
echo "ðŸŽ‰ Microservicio funcionando correctamente"
echo ""
echo "ðŸ“ Siguiente paso: Probar con un PDF real"
echo "   python test_service.py /path/to/your/document.pdf"
```

Guardar como `verify.sh` y ejecutar:

```bash
chmod +x verify.sh
./verify.sh
```

## ðŸ“š DocumentaciÃ³n Adicional

- **README completo**: `README.md`
- **GuÃ­a de integraciÃ³n**: `/home/alonso/projects/livo-backend/INTEGRACION_PDF_PROCESSOR.md`
- **DocumentaciÃ³n API**: http://localhost:8000/docs (FastAPI auto-docs)

## ðŸŽ“ PrÃ³ximos Pasos

1. âœ… Servicio funcionando
2. âœ… IntegraciÃ³n con backend
3. ðŸ“ Probar con documentos reales
4. ðŸ”§ Ajustar parÃ¡metros si es necesario
5. ðŸš€ Desplegar a producciÃ³n

---

**Â¿Problemas?** Revisar logs:
```bash
# Docker
docker-compose logs -f pdf-processor

# Local
# Revisar terminal donde corre uvicorn
```
