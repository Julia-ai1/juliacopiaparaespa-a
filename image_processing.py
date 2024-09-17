import os
import openai
import requests
from dotenv import load_dotenv
import tempfile

# Cargar variables de entorno desde .env
load_dotenv()

# Configurar las claves desde variables de entorno
AZURE_SUBSCRIPTION_KEY = os.getenv('AZURE_SUBSCRIPTION_KEY')
AZURE_ENDPOINT = os.getenv('AZURE_ENDPOINT')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

# Inicializar el cliente de OpenAI utilizando el método moderno
client = openai.OpenAI(api_key=OPENAI_API_KEY)

# Variable para almacenar el historial de los últimos 15 mensajes
conversation_history = []

def analyze_image(file_path):
    """Analiza una imagen usando la API de Computer Vision de Azure y extrae texto con OCR."""
    ocr_url = f"{AZURE_ENDPOINT}/vision/v3.2/ocr"

    headers = {
        'Ocp-Apim-Subscription-Key': AZURE_SUBSCRIPTION_KEY,
        'Content-Type': 'application/octet-stream'
    }

    # Leer la imagen en binario
    with open(file_path, 'rb') as image_file:
        image_data = image_file.read()

    response = requests.post(ocr_url, headers=headers, data=image_data)

    if response.status_code != 200:
        raise Exception(f"Error al analizar la imagen: {response.status_code} - {response.text}")

    ocr_result = response.json()
    extracted_text = ""
    for region in ocr_result.get('regions', []):
        for line in region.get('lines', []):
            for word in line.get('words', []):
                extracted_text += word['text'] + " "
    
    return extracted_text.strip()

def query_gpt4(content):
    """Envía una consulta a la API de GPT-4 utilizando el cliente moderno de OpenAI y retorna la respuesta."""
    
    # Agregar el mensaje del usuario al historial de conversación
    conversation_history.append({"role": "user", "content": content})
    
    # Limitar el historial a los últimos 15 mensajes
    if len(conversation_history) > 15:
        conversation_history.pop(0)  # Elimina el mensaje más antiguo
    
    # Crear la conversación con los mensajes previos y el nuevo contenido
    response = client.chat.completions.create(
        model="gpt-4",  # Modelo a utilizar
        messages=[
            {"role": "system", "content": "Eres un asistente útil capaz de procesar imágenes y texto. Organiza tus respuestas claramente y usa párrafos separados."}
        ] + conversation_history,  # Incluir el historial en la consulta
        max_tokens=2000,  # Control de longitud de respuesta
        temperature=0.7   # Creatividad de la respuesta
    )
    
    # Extraer correctamente el contenido de la respuesta
    assistant_message = response.model_dump()["choices"][0]["message"]["content"].strip()
    
    # Postprocesar la respuesta para mejorar el formato
    assistant_message = format_response(assistant_message)

    # Agregar la respuesta del asistente al historial
    conversation_history.append({"role": "assistant", "content": assistant_message})
    
    return assistant_message

def format_response(response):
    """Formatea la respuesta de GPT-4 para que esté mejor organizada con más espacios entre los párrafos."""
    # Añadir doble salto de línea después de cada punto seguido para separar en párrafos
    formatted_response = response.replace(". ", ".\n\n")
    return formatted_response


