"""
Servicio de procesamiento de imágenes
Optimización y análisis de imágenes para OCR
"""

import logging
from typing import Tuple
from PIL import Image, ImageEnhance, ImageFilter
import numpy as np
import cv2

logger = logging.getLogger(__name__)


class ImageProcessor:
    """Procesador de imágenes para mejorar OCR"""

    def __init__(self):
        logger.info("🎨 ImageProcessor inicializado")

    def enhance_for_ocr(self, image: Image.Image) -> Image.Image:
        """
        Mejora una imagen para OCR óptimo

        Args:
            image: Imagen PIL

        Returns:
            Imagen mejorada
        """
        try:
            # Convertir a OpenCV
            img_cv = self._pil_to_cv2(image)

            # Aplicar procesamiento
            img_cv = self._denoise(img_cv)
            img_cv = self._increase_contrast(img_cv)
            img_cv = self._sharpen(img_cv)
            img_cv = self._binarize(img_cv)

            # Convertir de vuelta a PIL
            return self._cv2_to_pil(img_cv)

        except Exception as e:
            logger.error(f"❌ Error mejorando imagen: {str(e)}")
            return image

    def _pil_to_cv2(self, pil_image: Image.Image) -> np.ndarray:
        """Convierte imagen PIL a OpenCV"""
        if pil_image.mode != 'RGB':
            pil_image = pil_image.convert('RGB')
        return cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)

    def _cv2_to_pil(self, cv_image: np.ndarray) -> Image.Image:
        """Convierte imagen OpenCV a PIL"""
        color_converted = cv2.cvtColor(cv_image, cv2.COLOR_BGR2RGB)
        return Image.fromarray(color_converted)

    def _denoise(self, image: np.ndarray) -> np.ndarray:
        """Reduce ruido en la imagen"""
        try:
            return cv2.fastNlMeansDenoisingColored(image, None, 10, 10, 7, 21)
        except:
            return image

    def _increase_contrast(self, image: np.ndarray) -> np.ndarray:
        """Aumenta el contraste usando CLAHE"""
        try:
            # Convertir a LAB
            lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)

            # Aplicar CLAHE al canal L
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            l = clahe.apply(l)

            # Combinar canales
            lab = cv2.merge([l, a, b])
            return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
        except:
            return image

    def _sharpen(self, image: np.ndarray) -> np.ndarray:
        """Aumenta la nitidez de la imagen"""
        try:
            kernel = np.array([[-1, -1, -1],
                             [-1,  9, -1],
                             [-1, -1, -1]])
            return cv2.filter2D(image, -1, kernel)
        except:
            return image

    def _binarize(self, image: np.ndarray) -> np.ndarray:
        """Binariza la imagen (blanco y negro)"""
        try:
            # Convertir a escala de grises
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

            # Binarización adaptativa
            binary = cv2.adaptiveThreshold(
                gray, 255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                11, 2
            )

            # Convertir de vuelta a BGR para consistencia
            return cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
        except:
            return image

    def detect_orientation(self, image: Image.Image) -> float:
        """
        Detecta la orientación del texto en la imagen

        Args:
            image: Imagen PIL

        Returns:
            Ángulo de rotación necesario
        """
        try:
            import pytesseract

            # Detectar orientación
            osd = pytesseract.image_to_osd(image)

            # Parsear resultado
            angle = 0
            for line in osd.split('\n'):
                if 'Rotate:' in line:
                    angle = int(line.split(':')[1].strip())
                    break

            return angle

        except Exception as e:
            logger.warning(f"⚠️ No se pudo detectar orientación: {str(e)}")
            return 0

    def auto_rotate(self, image: Image.Image) -> Image.Image:
        """
        Rota automáticamente la imagen a la orientación correcta

        Args:
            image: Imagen PIL

        Returns:
            Imagen rotada
        """
        try:
            angle = self.detect_orientation(image)

            if angle != 0:
                logger.info(f"🔄 Rotando imagen {angle} grados")
                return image.rotate(angle, expand=True)

            return image

        except Exception as e:
            logger.error(f"❌ Error rotando imagen: {str(e)}")
            return image

    def remove_borders(self, image: Image.Image, threshold: int = 240) -> Image.Image:
        """
        Elimina bordes blancos de la imagen

        Args:
            image: Imagen PIL
            threshold: Umbral para considerar píxel como blanco

        Returns:
            Imagen sin bordes
        """
        try:
            # Convertir a numpy array
            img_array = np.array(image.convert('L'))

            # Encontrar bordes no blancos
            coords = np.argwhere(img_array < threshold)

            if len(coords) == 0:
                return image

            # Obtener bounding box
            y0, x0 = coords.min(axis=0)
            y1, x1 = coords.max(axis=0) + 1

            # Recortar
            cropped = image.crop((x0, y0, x1, y1))

            logger.info(f"✂️ Imagen recortada de {image.size} a {cropped.size}")
            return cropped

        except Exception as e:
            logger.error(f"❌ Error removiendo bordes: {str(e)}")
            return image

    def resize_for_ocr(self, image: Image.Image, min_width: int = 1000) -> Image.Image:
        """
        Redimensiona imagen para OCR óptimo

        Args:
            image: Imagen PIL
            min_width: Ancho mínimo deseado

        Returns:
            Imagen redimensionada
        """
        try:
            if image.width < min_width:
                ratio = min_width / image.width
                new_size = (min_width, int(image.height * ratio))
                resized = image.resize(new_size, Image.Resampling.LANCZOS)
                logger.info(f"📏 Imagen redimensionada de {image.size} a {resized.size}")
                return resized

            return image

        except Exception as e:
            logger.error(f"❌ Error redimensionando: {str(e)}")
            return image
