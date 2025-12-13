"""
Servicio de procesamiento de PDFs
Extrae texto e imágenes de documentos PDF
"""

import logging
from typing import List, Dict
import PyPDF2
from pdf2image import convert_from_path
from PIL import Image
import io
import os

logger = logging.getLogger(__name__)


class PDFProcessor:
    """Procesador de archivos PDF"""

    def __init__(self):
        self.dpi = 300  # Calidad de conversión de PDF a imagen
        logger.info("📄 PDFProcessor inicializado")

    def extract_text(self, pdf_path: str) -> str:
        """
        Extrae texto nativo de un PDF

        Args:
            pdf_path: Ruta al archivo PDF

        Returns:
            Texto extraído del PDF
        """
        try:
            text = ""
            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)

                for page_num in range(len(pdf_reader.pages)):
                    page = pdf_reader.pages[page_num]
                    page_text = page.extract_text()
                    text += f"\n--- Página {page_num + 1} ---\n{page_text}\n"

            logger.info(f"✅ Texto extraído: {len(text)} caracteres")
            return text.strip()

        except Exception as e:
            logger.error(f"❌ Error extrayendo texto: {str(e)}")
            return ""

    def get_pdf_info(self, pdf_path: str) -> Dict:
        """
        Obtiene información del PDF

        Args:
            pdf_path: Ruta al archivo PDF

        Returns:
            Diccionario con información del PDF
        """
        try:
            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)

                info = {
                    'num_pages': len(pdf_reader.pages),
                    'metadata': pdf_reader.metadata if pdf_reader.metadata else {},
                    'is_encrypted': pdf_reader.is_encrypted
                }

                # Extraer metadata útil
                if pdf_reader.metadata:
                    info['title'] = pdf_reader.metadata.get('/Title', '')
                    info['author'] = pdf_reader.metadata.get('/Author', '')
                    info['creator'] = pdf_reader.metadata.get('/Creator', '')

                return info

        except Exception as e:
            logger.error(f"❌ Error obteniendo info del PDF: {str(e)}")
            return {'num_pages': 0, 'metadata': {}, 'is_encrypted': False}

    def convert_to_images(self, pdf_path: str) -> List[Image.Image]:
        """
        Convierte un PDF a imágenes

        Args:
            pdf_path: Ruta al archivo PDF

        Returns:
            Lista de imágenes PIL
        """
        try:
            logger.info(f"🖼️ Convirtiendo PDF a imágenes (DPI: {self.dpi})...")

            images = convert_from_path(
                pdf_path,
                dpi=self.dpi,
                fmt='png'
            )

            logger.info(f"✅ PDF convertido a {len(images)} imágenes")
            return images

        except Exception as e:
            logger.error(f"❌ Error convirtiendo PDF a imágenes: {str(e)}")
            return []

    def extract_embedded_images(self, pdf_path: str) -> List[Image.Image]:
        """
        Extrae imágenes embebidas en el PDF

        Args:
            pdf_path: Ruta al archivo PDF

        Returns:
            Lista de imágenes PIL extraídas
        """
        try:
            images = []

            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)

                for page_num in range(len(pdf_reader.pages)):
                    page = pdf_reader.pages[page_num]

                    # Intentar extraer imágenes usando XObject
                    if '/XObject' in page['/Resources']:
                        x_objects = page['/Resources']['/XObject'].get_object()

                        for obj_name in x_objects:
                            obj = x_objects[obj_name]

                            if obj['/Subtype'] == '/Image':
                                try:
                                    # Extraer datos de la imagen
                                    size = (obj['/Width'], obj['/Height'])
                                    data = obj.get_data()

                                    # Intentar diferentes modos de color
                                    if obj['/ColorSpace'] == '/DeviceRGB':
                                        mode = "RGB"
                                    elif obj['/ColorSpace'] == '/DeviceGray':
                                        mode = "L"
                                    else:
                                        mode = "RGB"

                                    img = Image.frombytes(mode, size, data)
                                    images.append(img)

                                except Exception as img_error:
                                    logger.warning(f"⚠️ No se pudo extraer imagen {obj_name}: {str(img_error)}")
                                    continue

            logger.info(f"✅ Extraídas {len(images)} imágenes embebidas")
            return images

        except Exception as e:
            logger.error(f"❌ Error extrayendo imágenes embebidas: {str(e)}")
            return []

    def optimize_image_for_ocr(self, image: Image.Image) -> Image.Image:
        """
        Optimiza una imagen para mejorar resultados de OCR

        Args:
            image: Imagen PIL

        Returns:
            Imagen optimizada
        """
        try:
            # Convertir a escala de grises
            if image.mode != 'L':
                image = image.convert('L')

            # Aumentar contraste
            from PIL import ImageEnhance
            enhancer = ImageEnhance.Contrast(image)
            image = enhancer.enhance(2.0)

            # Aumentar nitidez
            enhancer = ImageEnhance.Sharpness(image)
            image = enhancer.enhance(1.5)

            return image

        except Exception as e:
            logger.error(f"❌ Error optimizando imagen: {str(e)}")
            return image
