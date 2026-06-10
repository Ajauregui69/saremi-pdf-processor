# HAVI PDF Processor - Deployment Guide

Microservicio Python para procesamiento de documentos PDF, OCR y extracciÃ³n de datos para HAVI.

## ðŸ“‹ Requisitos

- Python 3.9+
- Tesseract OCR
- Poppler (para pdf2image)
- 1GB+ RAM (2GB recomendado)

## ðŸš€ Deployment en Digital Ocean

### OpciÃ³n 1: Droplet Simple (Recomendado para empezar)

1. **Crear Droplet**
   ```bash
   # Ubuntu 22.04 LTS
   # 1GB RAM mÃ­nimo ($6/mes)
   # 2GB RAM recomendado ($12/mes)
   ```

2. **Instalar dependencias**
   ```bash
   # Actualizar sistema
   sudo apt update && sudo apt upgrade -y

   # Instalar Python y pip
   sudo apt install python3-pip python3-venv -y

   # Instalar Tesseract OCR
   sudo apt install tesseract-ocr tesseract-ocr-spa -y

   # Instalar Poppler
   sudo apt install poppler-utils -y
   ```

3. **Deploy de la aplicaciÃ³n**
   ```bash
   # Clonar repo
   cd /opt
   sudo git clone https://github.com/YOUR_USERNAME/saremi-pdf-processor.git
   cd saremi-pdf-processor

   # Crear virtualenv
   python3 -m venv venv
   source venv/bin/activate

   # Instalar dependencias
   pip install -r requirements.txt

   # Configurar variables de entorno
   cp .env.example .env
   nano .env  # Editar segÃºn necesidades
   ```

4. **Configurar como servicio systemd**
   ```bash
   sudo nano /etc/systemd/system/saremi-pdf-processor.service
   ```

   Contenido:
   ```ini
   [Unit]
   Description=HAVI PDF Processor Service
   After=network.target

   [Service]
   Type=simple
   User=root
   WorkingDirectory=/opt/saremi-pdf-processor
   Environment="PATH=/opt/saremi-pdf-processor/venv/bin"
   ExecStart=/opt/saremi-pdf-processor/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8001
   Restart=always
   RestartSec=10

   [Install]
   WantedBy=multi-user.target
   ```

   Activar servicio:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable saremi-pdf-processor
   sudo systemctl start saremi-pdf-processor
   sudo systemctl status saremi-pdf-processor
   ```

5. **Configurar Nginx como proxy reverso** (Opcional pero recomendado)
   ```bash
   sudo apt install nginx -y
   sudo nano /etc/nginx/sites-available/pdf-processor
   ```

   Contenido:
   ```nginx
   server {
       listen 80;
       server_name pdf.havi.app;  # Tu subdominio

       location / {
           proxy_pass http://localhost:8001;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;

           # Timeouts para PDFs grandes
           proxy_connect_timeout 300;
           proxy_send_timeout 300;
           proxy_read_timeout 300;
           send_timeout 300;
       }
   }
   ```

   Activar:
   ```bash
   sudo ln -s /etc/nginx/sites-available/pdf-processor /etc/nginx/sites-enabled/
   sudo nginx -t
   sudo systemctl restart nginx
   ```

6. **Configurar SSL con Let's Encrypt**
   ```bash
   sudo apt install certbot python3-certbot-nginx -y
   sudo certbot --nginx -d pdf.havi.app
   ```

### OpciÃ³n 2: Docker (MÃ¡s moderno)

1. **Instalar Docker**
   ```bash
   curl -fsSL https://get.docker.com -o get-docker.sh
   sudo sh get-docker.sh
   ```

2. **Build y run**
   ```bash
   docker build -t saremi-pdf-processor .
   docker run -d \
     --name pdf-processor \
     -p 8001:8001 \
     --restart always \
     saremi-pdf-processor
   ```

3. **Con Docker Compose**
   ```bash
   docker-compose up -d
   ```

### OpciÃ³n 3: Digital Ocean App Platform (Auto-scaling)

1. Crear `app.yaml`:
   ```yaml
   name: saremi-pdf-processor
   region: nyc
   services:
   - name: api
     github:
       repo: YOUR_USERNAME/saremi-pdf-processor
       branch: main
     build_command: pip install -r requirements.txt
     run_command: uvicorn main:app --host 0.0.0.0 --port 8080
     http_port: 8080
     instance_count: 1
     instance_size_slug: basic-xs
     health_check:
       http_path: /health
   ```

2. Deploy vÃ­a CLI o UI de Digital Ocean

## ðŸ”’ Seguridad

1. **Crear API Key para autenticaciÃ³n**
   ```bash
   # Generar API key segura
   openssl rand -hex 32
   ```

2. **Agregar a .env**
   ```
   API_KEY=tu_api_key_generada_aqui
   ```

3. **Actualizar pdfProcessorClient en livo-backend**
   ```typescript
   // app/services/pdf_processor_client.ts
   const response = await fetch(`${this.baseUrl}/process-ine`, {
     method: 'POST',
     headers: {
       'Content-Type': 'application/json',
       'X-API-Key': env.get('PDF_PROCESSOR_API_KEY')
     },
     body: JSON.stringify(data)
   })
   ```

## ðŸ“Š Monitoreo

### Logs
```bash
# Ver logs del servicio
sudo journalctl -u saremi-pdf-processor -f

# Logs de Docker
docker logs -f pdf-processor
```

### Health Check
```bash
curl http://localhost:8001/health
```

### MÃ©tricas (Opcional)
Instalar Prometheus + Grafana para monitoreo avanzado

## ðŸ”„ Updates

```bash
cd /opt/saremi-pdf-processor
sudo git pull origin main
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart saremi-pdf-processor
```

## ðŸ’° Costos Estimados

| OpciÃ³n | Costo Mensual | Escalabilidad |
|--------|--------------|---------------|
| Droplet 1GB | $6 | Manual |
| Droplet 2GB | $12 | Manual |
| App Platform | $5-15 | Auto |
| Kubernetes | $12+ | Auto |

## ðŸ› Troubleshooting

### Error: No module named 'tesseract'
```bash
sudo apt install tesseract-ocr tesseract-ocr-spa -y
```

### Error: Poppler not found
```bash
sudo apt install poppler-utils -y
```

### Alto uso de CPU/RAM
- Aumentar tamaÃ±o del droplet
- Implementar cola de trabajos con Redis/Celery
- Limitar procesamiento concurrente

## ðŸ“ PrÃ³ximos pasos

1. âœ… Separar microservicio en repo independiente
2. â¬œ Configurar CI/CD con GitHub Actions
3. â¬œ Implementar cola de procesamiento con Redis
4. â¬œ Agregar mÃ©tricas y alertas
5. â¬œ Implementar rate limiting
6. â¬œ Cache de resultados frecuentes
