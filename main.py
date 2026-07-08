"""
SarEmi API — Servicio de verificación de documentos para instituciones
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from database import init_db, close_db
from routers import verify, process, admin, soap

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logger.info("SarEmi API iniciada")
    yield
    await close_db()
    logger.info("SarEmi API detenida")


app = FastAPI(
    title="SarEmi API",
    description=(
        "Servicio de verificación de documentos para instituciones. "
        "Verifica INE, CURP, estados de cuenta y comprobantes de domicilio. "
        "Acceso por institución mediante X-API-Key."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
cors_origins = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(verify.router)
app.include_router(process.router)
app.include_router(admin.router)
app.include_router(soap.router)


@app.get("/", tags=["health"])
async def root():
    return {"service": "SarEmi API", "status": "running", "version": "1.0.0"}


@app.get("/health", tags=["health"])
async def health_check():
    return {
        "status": "healthy",
        "services": {
            "pdf_processor": "ready",
            "ocr_service": "ready",
            "verifiers": "ready",
            "database": "ready",
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", "8000")),
    )
