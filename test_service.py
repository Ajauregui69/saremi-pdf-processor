"""
Script de prueba para el microservicio de procesamiento de PDFs
"""

import requests
import sys
import os


def test_health_check(base_url: str):
    """Prueba el health check"""
    print("🏥 Probando health check...")
    try:
        response = requests.get(f"{base_url}/health", timeout=5)
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Servicio saludable: {data}")
            return True
        else:
            print(f"❌ Error: Status {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Error conectando al servicio: {e}")
        return False


def test_process_pdf(base_url: str, pdf_path: str):
    """Prueba el procesamiento de un PDF"""
    print(f"\n📄 Probando procesamiento de PDF: {pdf_path}")

    if not os.path.exists(pdf_path):
        print(f"❌ Archivo no encontrado: {pdf_path}")
        return False

    try:
        with open(pdf_path, 'rb') as f:
            files = {'file': f}
            data = {
                'document_type': 'bank_statement',
                'use_advanced_ocr': 'true',
                'extract_images': 'true'
            }

            print("⏳ Procesando (esto puede tardar varios segundos)...")
            response = requests.post(
                f"{base_url}/process-pdf",
                files=files,
                data=data,
                timeout=120
            )

            if response.status_code == 200:
                result = response.json()
                print(f"\n✅ PDF procesado exitosamente:")
                print(f"   📝 Páginas: {result['num_pages']}")
                print(f"   📝 Método: {result['processing_method']}")
                print(f"   📝 Caracteres extraídos: {result['text_length']}")
                print(f"   📝 Confianza OCR: {result.get('ocr_confidence', 0):.2f}%")
                print(f"   📝 Calidad: {result['document_analysis'].get('estimated_quality', 'unknown')}")

                # Mostrar primeros 200 caracteres del texto
                text = result['extracted_text'][:200]
                print(f"\n📄 Primeros 200 caracteres:\n{text}...")

                return True
            else:
                print(f"❌ Error: Status {response.status_code}")
                print(f"   {response.text}")
                return False

    except Exception as e:
        print(f"❌ Error procesando PDF: {e}")
        return False


def test_process_image(base_url: str, image_path: str):
    """Prueba el procesamiento de una imagen"""
    print(f"\n🖼️ Probando procesamiento de imagen: {image_path}")

    if not os.path.exists(image_path):
        print(f"❌ Archivo no encontrado: {image_path}")
        return False

    try:
        with open(image_path, 'rb') as f:
            files = {'file': f}
            data = {'use_advanced_ocr': 'true'}

            print("⏳ Procesando...")
            response = requests.post(
                f"{base_url}/process-image",
                files=files,
                data=data,
                timeout=60
            )

            if response.status_code == 200:
                result = response.json()
                print(f"\n✅ Imagen procesada exitosamente:")
                print(f"   📝 Método: {result['method']}")
                print(f"   📝 Confianza: {result['confidence']:.2f}%")

                # Mostrar primeros 200 caracteres del texto
                text = result['text'][:200]
                print(f"\n📄 Texto extraído:\n{text}...")

                return True
            else:
                print(f"❌ Error: Status {response.status_code}")
                print(f"   {response.text}")
                return False

    except Exception as e:
        print(f"❌ Error procesando imagen: {e}")
        return False


def main():
    """Ejecutar pruebas"""
    print("=" * 60)
    print("🧪 TEST - Microservicio PDF Processor")
    print("=" * 60)

    base_url = "http://localhost:8000"

    # 1. Health check
    if not test_health_check(base_url):
        print("\n❌ El servicio no está disponible. Asegúrate de que esté corriendo:")
        print("   docker-compose up -d")
        print("   o")
        print("   uvicorn main:app --reload")
        return

    # 2. Test PDF (si se proporciona)
    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]
        test_process_pdf(base_url, pdf_path)

        # Si es una imagen
        if pdf_path.lower().endswith(('.jpg', '.jpeg', '.png', '.gif')):
            test_process_image(base_url, pdf_path)
    else:
        print("\n💡 Uso:")
        print(f"   python {sys.argv[0]} <ruta_al_pdf_o_imagen>")
        print("\n   Ejemplo:")
        print(f"   python {sys.argv[0]} /path/to/estado_cuenta.pdf")
        print(f"   python {sys.argv[0]} /path/to/ine.jpg")

    print("\n" + "=" * 60)
    print("✅ Pruebas completadas")
    print("=" * 60)


if __name__ == "__main__":
    main()
