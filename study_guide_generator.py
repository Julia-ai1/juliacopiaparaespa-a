from langchain.document_loaders import PyPDFLoader
from langchain.text_splitter import CharacterTextSplitter
from langchain.prompts import PromptTemplate
from langchain.chains import LLMChain # Asegúrate de tener el SDK adecuado
from langchain_community.chat_models import ChatDeepInfra
import os
import json
from dotenv import load_dotenv
os.environ["DEEPINFRA_API_TOKEN"] = os.getenv("DEEPINFRA_API_TOKEN")
# Función para extraer texto desde un PDF usando LangChain

PROGRESS_FILE_PATH = 'user_progress.json'  # Archivo donde se guarda el progreso
load_dotenv()
# Función para extraer texto desde un PDF usando LangChain
def extract_text_from_pdf(pdf_path):
    loader = PyPDFLoader(pdf_path)
    documents = loader.load()

    # Usamos un text splitter para dividir el contenido del PDF en segmentos manejables
    text_splitter = CharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    chunks = text_splitter.split_documents(documents)

    return chunks

# Función para generar la guía de estudio desde un PDF con un prompt mejorado
def generate_study_guide_from_pdf(pdf_path, progress=None):
    pdf_chunks = extract_text_from_pdf(pdf_path)

    if progress is None:
        progress = [False] * len(pdf_chunks)  # Si no hay progreso, empezamos desde cero

    # Solo mostramos los chunks que aún no se han completado
    incomplete_chunks = [chunk for i, chunk in enumerate(pdf_chunks) if not progress[i]]

    if not incomplete_chunks:
        return {'message': '¡Felicidades! Has completado toda la guía de estudio.'}

    # Generar la guía para el próximo chunk
    next_chunk = incomplete_chunks[0]
    chat = ChatDeepInfra(model="meta-llama/Meta-Llama-3.1-8B-Instruct", max_tokens=1000)

    # Prompt detallado para generar un resumen extenso y con ejemplos
    prompt = f"""
    Eres un asistente educativo. Tienes acceso a la siguiente sección de una guía de estudio:
    
    {next_chunk.page_content}
    
    Por favor, realiza las siguientes tareas:
    
    1. Explica este contenido de manera sencilla, destacando los conceptos clave.
    2. Proporciona ejemplos concretos para ilustrar los conceptos importantes.
    3. Incluye recomendaciones prácticas para que el estudiante pueda aplicar los conceptos en situaciones reales o ejercicios.
    4. Divide la explicación en puntos clave para que sea más fácil de seguir.
    5. Si hay definiciones, explícalas en términos sencillos, y si es posible, relaciona con situaciones cotidianas.
    6. Indica si el tema requiere conocimientos previos y sugiere revisiones breves de esos temas si es necesario.

    Asegúrate de que el estudiante comprenda cada aspecto de la sección, y si es relevante, incluye pasos para resolver ejercicios relacionados.
    """

    response = chat.invoke(prompt)
    guide_text = response.get('answer', 'No se pudo generar la guía.')

    return {
        'guide': guide_text,
        'progress': progress
    }

# Función para guardar el progreso
def save_progress(user_id, progress):
    # Crear un archivo JSON para guardar el progreso si no existe
    if not os.path.exists(PROGRESS_FILE_PATH):
        with open(PROGRESS_FILE_PATH, 'w') as f:
            json.dump({}, f)

    # Cargar el progreso existente
    with open(PROGRESS_FILE_PATH, 'r') as f:
        all_progress = json.load(f)

    # Actualizar el progreso del usuario
    all_progress[user_id] = progress

    # Guardar el progreso actualizado
    with open(PROGRESS_FILE_PATH, 'w') as f:
        json.dump(all_progress, f)

# Función para cargar el progreso
def load_progress(user_id):
    if not os.path.exists(PROGRESS_FILE_PATH):
        return None  # Si no existe, significa que no hay progreso guardado

    with open(PROGRESS_FILE_PATH, 'r') as f:
        all_progress = json.load(f)

    # Devolver el progreso del usuario si existe
    return all_progress.get(user_id, None)
