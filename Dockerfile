# syntax=docker/dockerfile:1
FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-spa \
    tesseract-ocr-eng \
    poppler-utils \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

RUN sed -i 's/opencv-python==/opencv-python-headless==/g' requirements.txt

# Cache de pip persiste entre builds — torch (190 MB) no se vuelve a bajar si ya está en cache
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install torch==2.6.0+cpu torchvision==0.21.0+cpu \
    --index-url https://download.pytorch.org/whl/cpu

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# Pre-descargar modelos de EasyOCR durante el build.
# Evita que el primer request tarde 2-3 minutos descargando modelos.
# Los modelos quedan cacheados en /root/.EasyOCR/model/ (~110 MB).
RUN python -c "import easyocr; easyocr.Reader(['es', 'en'], gpu=False)" 2>&1 | grep -v "^$" || true

COPY . .

RUN mkdir -p /tmp/pdf-processor uploads && \
    chmod +x /app/entrypoint.sh

ENV TESSDATA_PREFIX=/usr/share/tesseract-ocr/4.00/tessdata
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
