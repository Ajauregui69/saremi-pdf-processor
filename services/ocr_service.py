"""
Servicio de OCR (Reconocimiento Óptico de Caracteres)
Soporta Tesseract (básico) y EasyOCR (avanzado)
"""

import logging
from typing import List, Dict
import pytesseract
from PIL import Image
import asyncio
import os

logger = logging.getLogger(__name__)


class OCRService:
    """Servicio de OCR con múltiples motores"""

    def __init__(self):
        self.tesseract_config = '--oem 3 --psm 6'  # LSTM OCR Engine, Assume uniform block of text
        self.easyocr_reader = None
        logger.info("🔍 OCRService inicializado")

    async def _get_easyocr_reader(self):
        """
        Inicializa EasyOCR reader de forma lazy (solo cuando se necesita)
        """
        if self.easyocr_reader is None:
            logger.info("📦 Inicializando EasyOCR...")
            import easyocr
            # Soportar español e inglés
            self.easyocr_reader = easyocr.Reader(['es', 'en'], gpu=False)
            logger.info("✅ EasyOCR listo")
        return self.easyocr_reader

    def process_single_image_basic(self, image_path: str) -> Dict:
        """
        Procesa una imagen con Tesseract (OCR básico)

        Args:
            image_path: Ruta a la imagen

        Returns:
            Diccionario con texto y confianza
        """
        try:
            image = Image.open(image_path)

            # Convertir a escala de grises si no lo está
            if image.mode != 'L':
                image = image.convert('L')

            # Extraer texto
            text = pytesseract.image_to_string(
                image,
                lang='spa+eng',
                config=self.tesseract_config
            )

            # Obtener confianza
            data = pytesseract.image_to_data(
                image,
                lang='spa+eng',
                config=self.tesseract_config,
                output_type=pytesseract.Output.DICT
            )

            # Calcular confianza promedio (ignorar valores -1)
            confidences = [int(conf) for conf in data['conf'] if conf != '-1']
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0

            return {
                'text': text.strip(),
                'confidence': avg_confidence
            }

        except Exception as e:
            logger.error(f"❌ Error en OCR básico: {str(e)}")
            return {
                'text': '',
                'confidence': 0
            }

    async def process_single_image_advanced(self, image_path: str) -> Dict:
        """
        Procesa una imagen con EasyOCR (OCR avanzado)

        Args:
            image_path: Ruta a la imagen

        Returns:
            Diccionario con texto y confianza
        """
        try:
            reader = await self._get_easyocr_reader()

            # Ejecutar OCR en thread separado para no bloquear
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                reader.readtext,
                image_path
            )

            # Combinar resultados
            texts = []
            confidences = []

            for detection in result:
                bbox, text, confidence = detection
                texts.append(text)
                confidences.append(confidence * 100)  # Convertir a porcentaje

            combined_text = ' '.join(texts)
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0

            return {
                'text': combined_text.strip(),
                'confidence': avg_confidence
            }

        except Exception as e:
            logger.error(f"❌ Error en OCR avanzado: {str(e)}")
            return {
                'text': '',
                'confidence': 0
            }

    def process_images_basic(self, images: List[Image.Image]) -> List[Dict]:
        """
        Procesa múltiples imágenes con Tesseract

        Args:
            images: Lista de imágenes PIL

        Returns:
            Lista de resultados con texto y confianza
        """
        results = []

        for idx, image in enumerate(images):
            logger.info(f"🔍 Procesando imagen {idx + 1}/{len(images)} con Tesseract...")

            try:
                # Convertir a escala de grises
                if image.mode != 'L':
                    image = image.convert('L')

                # Extraer texto
                text = pytesseract.image_to_string(
                    image,
                    lang='spa+eng',
                    config=self.tesseract_config
                )

                # Obtener confianza
                data = pytesseract.image_to_data(
                    image,
                    lang='spa+eng',
                    config=self.tesseract_config,
                    output_type=pytesseract.Output.DICT
                )

                confidences = [int(conf) for conf in data['conf'] if conf != '-1']
                avg_confidence = sum(confidences) / len(confidences) if confidences else 0

                results.append({
                    'page': idx + 1,
                    'text': text.strip(),
                    'confidence': avg_confidence
                })

            except Exception as e:
                logger.error(f"❌ Error procesando imagen {idx + 1}: {str(e)}")
                results.append({
                    'page': idx + 1,
                    'text': '',
                    'confidence': 0
                })

        return results

    async def process_images_advanced(self, images: List[Image.Image]) -> List[Dict]:
        """
        Procesa múltiples imágenes con EasyOCR

        Args:
            images: Lista de imágenes PIL

        Returns:
            Lista de resultados con texto y confianza
        """
        results = []
        reader = await self._get_easyocr_reader()

        for idx, image in enumerate(images):
            logger.info(f"🔍 Procesando imagen {idx + 1}/{len(images)} con EasyOCR...")

            try:
                # Guardar temporalmente para EasyOCR
                import tempfile
                with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp_file:
                    image.save(tmp_file.name)
                    tmp_path = tmp_file.name

                # Ejecutar OCR
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None,
                    reader.readtext,
                    tmp_path
                )

                # Procesar resultados
                texts = []
                confidences = []

                for detection in result:
                    bbox, text, confidence = detection
                    texts.append(text)
                    confidences.append(confidence * 100)

                combined_text = ' '.join(texts)
                avg_confidence = sum(confidences) / len(confidences) if confidences else 0

                results.append({
                    'page': idx + 1,
                    'text': combined_text.strip(),
                    'confidence': avg_confidence
                })

                # Limpiar archivo temporal
                os.unlink(tmp_path)

            except Exception as e:
                logger.error(f"❌ Error procesando imagen {idx + 1}: {str(e)}")
                results.append({
                    'page': idx + 1,
                    'text': '',
                    'confidence': 0
                })

        return results

    def preprocess_image_for_ocr(self, image: Image.Image) -> Image.Image:
        """
        Preprocesa una imagen para mejorar resultados de OCR

        Args:
            image: Imagen PIL

        Returns:
            Imagen preprocesada
        """
        try:
            # Convertir a escala de grises
            if image.mode != 'L':
                image = image.convert('L')

            # Redimensionar si es muy pequeña
            min_size = 800
            if image.width < min_size or image.height < min_size:
                ratio = max(min_size / image.width, min_size / image.height)
                new_size = (int(image.width * ratio), int(image.height * ratio))
                image = image.resize(new_size, Image.Resampling.LANCZOS)

            # Mejorar contraste
            from PIL import ImageEnhance
            enhancer = ImageEnhance.Contrast(image)
            image = enhancer.enhance(1.5)

            # Mejorar nitidez
            enhancer = ImageEnhance.Sharpness(image)
            image = enhancer.enhance(1.3)

            return image

        except Exception as e:
            logger.error(f"❌ Error preprocesando imagen: {str(e)}")
            return image
