"""
Servicio de detección de códigos QR y códigos de barras.
Usa pyzbar (zbar) como detector principal — mucho más robusto que OpenCV
para documentos escaneados con QR pequeños o de baja resolución.
OpenCV actúa como fallback.
"""

import logging
from typing import List, Dict, Optional
from PIL import Image
import numpy as np

logger = logging.getLogger(__name__)

# Resoluciones de reintento cuando la detección falla a resolución original
_UPSCALE_FACTORS = [1.5, 2.0, 3.0]


def _decode_pyzbar(pil_image: Image.Image) -> List[Dict]:
    """
    Decodifica todos los QR y códigos de barras en una imagen PIL usando pyzbar.
    Retorna lista de {data, type, rect}.
    """
    from pyzbar.pyzbar import decode as zbar_decode
    results = []
    for obj in zbar_decode(pil_image):
        try:
            data = obj.data.decode("utf-8", errors="replace")
        except Exception:
            data = str(obj.data)
        results.append({
            "data": data,
            "type": obj.type,
            "rect": obj.rect,
        })
    return results


def _decode_opencv(pil_image: Image.Image) -> Optional[str]:
    """Fallback: usa cv2.QRCodeDetector. Menos robusto pero no requiere libzbar."""
    try:
        import cv2
        import numpy as _np
        arr = cv2.cvtColor(_np.array(pil_image.convert("RGB")), cv2.COLOR_RGB2BGR)
        det = cv2.QRCodeDetector()
        gray = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
        for candidate in [arr, gray]:
            data, _, _ = det.detectAndDecode(candidate)
            if data:
                return data
        for scale in _UPSCALE_FACTORS:
            h, w = gray.shape[:2]
            up = cv2.resize(gray, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)
            data, _, _ = det.detectAndDecode(up)
            if data:
                return data
    except Exception:
        pass
    return None


class QRService:
    """Detecta y decodifica códigos QR en imágenes de documentos."""

    def __init__(self):
        try:
            from pyzbar.pyzbar import decode  # noqa: F401 — verify it's importable
            self._use_pyzbar = True
        except ImportError:
            self._use_pyzbar = False
            logger.warning("pyzbar no disponible — usando OpenCV (menor precisión)")
        logger.info(f"QRService inicializado ({'pyzbar' if self._use_pyzbar else 'opencv'})")

    def scan_images(self, images: List[Image.Image]) -> List[Dict]:
        """
        Escanea una lista de imágenes PIL en busca de QR / códigos de barras.
        Devuelve lista de { page, data, type, points }.
        """
        found = []
        for idx, pil_image in enumerate(images):
            page_num = idx + 1
            try:
                page_results = self._scan_single(pil_image, page_num)
                found.extend(page_results)
            except Exception as e:
                logger.warning(f"Error escaneando QR en página {page_num}: {e}")
        return found

    def _scan_single(self, pil_image: Image.Image, page_num: int) -> List[Dict]:
        """Detecta todos los códigos en una página. Retorna lista (puede haber varios)."""
        if pil_image.mode not in ("RGB", "L"):
            pil_image = pil_image.convert("RGB")

        if self._use_pyzbar:
            # Intento 1: imagen original
            decoded = _decode_pyzbar(pil_image)
            if not decoded:
                # Intento 2: escala de grises
                gray = pil_image.convert("L")
                decoded = _decode_pyzbar(gray)
            if not decoded:
                # Intento 3: upscale progresivo (QR pequeños en documentos comprimidos)
                for scale in _UPSCALE_FACTORS:
                    new_w = int(pil_image.width * scale)
                    new_h = int(pil_image.height * scale)
                    upscaled = pil_image.resize((new_w, new_h), Image.LANCZOS)
                    decoded = _decode_pyzbar(upscaled)
                    if decoded:
                        break
            if decoded:
                results = []
                for obj in decoded:
                    raw = obj["data"]
                    # Descartar resultados con NUL bytes o contenido binario no UTF-8
                    if "\x00" in raw or not raw.isprintable() and not any(c.isalnum() for c in raw):
                        logger.debug(f"QR descartado (datos binarios/corruptos) en página {page_num}")
                        continue
                    # Limpiar NUL residuales por si acaso
                    clean = raw.replace("\x00", "").strip()
                    if not clean:
                        continue
                    logger.info(f"QR/barcode en página {page_num}: type={obj['type']} data={clean[:80]}")
                    results.append({
                        "page": page_num,
                        "data": clean,
                        "type": obj.get("type", "QRCODE"),
                        "points": None,
                    })
                return results
        else:
            # Fallback OpenCV
            data = _decode_opencv(pil_image)
            if data:
                logger.info(f"QR en página {page_num} (opencv): {data[:80]}")
                return [{"page": page_num, "data": data, "type": "QRCODE", "points": None}]

        logger.debug(f"Página {page_num}: sin QR detectado")
        return []
