import os
import openai
import requests
import os
from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential
from dotenv import load_dotenv

# Cargar variables de entorno desde .env
load_dotenv()
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

# Inicializar el cliente de OpenAI utilizando el método moderno
client = openai.OpenAI(api_key=OPENAI_API_KEY)
# Configurar las claves y el endpoint desde las variables de entorno
FORM_RECOGNIZER_ENDPOINT = os.getenv('AZURE_FORM_RECOGNIZER_ENDPOINT')
FORM_RECOGNIZER_KEY = os.getenv('AZURE_FORM_RECOGNIZER_KEY')
conversation_history = []
# Crear el cliente para Azure Document Intelligence (anteriormente Form Recognizer)
document_analysis_client = DocumentAnalysisClient(
    endpoint=FORM_RECOGNIZER_ENDPOINT,
    credential=AzureKeyCredential(FORM_RECOGNIZER_KEY)
)

def analyze_document(file_path):
    """Analiza un documento usando Azure Document Intelligence y extrae su contenido."""
    with open(file_path, "rb") as document:
        poller = document_analysis_client.begin_analyze_document(
            model_id="prebuilt-document",  # Usar el modelo preentrenado general
            document=document
        )
        result = poller.result()

    extracted_text = ""

    # Procesar el contenido extraído
    for page in result.pages:
        for line in page.lines:
            extracted_text += line.content + "\n"

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
        model="gpt-4o-mini",  # Modelo a utilizar
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


