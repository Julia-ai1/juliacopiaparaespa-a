import os
import pdfplumber  # PyMuPDF para leer PDFs
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
import uuid

# Configurar las credenciales y el endpoint de Azure Cognitive Search
SEARCH_SERVICE_ENDPOINT = "https://julia.search.windows.net"
SEARCH_API_KEY = "1tVHTOPzhAJm9RnBby7QaM9bdNgJpfonSiBlMy10eBAzSeA5U1dj"
INDEX_NAME = "exam_questions_sel"
# Crear el cliente de Azure Cognitive Search
search_client = SearchClient(
    endpoint=SEARCH_SERVICE_ENDPOINT,
    index_name=INDEX_NAME,
    credential=AzureKeyCredential(SEARCH_API_KEY)
)


def search_documents_in_azure(query_text, num_results=5):
    try:
        results = search_client.search(search_text=query_text, top=num_results)
        for result in results:
            print(f"Documento encontrado - ID: {result['id']}, Archivo: {result['file_name']}")
            print(f"Contenido: {result['content'][:500]}...\n")  # Imprimir una parte del contenido
    except Exception as e:
        print(f"Error al buscar documentos: {e}")

# Realizar una búsqueda de prueba
query_text = "matrices"  #esto por cualquier palabra clave para probar
search_documents_in_azure(query_text)