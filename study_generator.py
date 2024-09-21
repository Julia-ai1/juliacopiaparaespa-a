from langchain.document_loaders import PyPDFLoader
from langchain.text_splitter import CharacterTextSplitter
from langchain_community.chat_models import ChatDeepInfra
from flask import current_app
import os
import json
from models import db, UserProgress
from dotenv import load_dotenv
import re
from langchain.schema import Document  # Asegúrate de importar Document
import unicodedata

# Cargar variables de entorno
load_dotenv()
os.environ["DEEPINFRA_API_TOKEN"] = os.getenv("DEEPINFRA_API_TOKEN")

# Función para normalizar texto
def normalize_text(text):
    """
    Normaliza el texto eliminando acentos, mayúsculas y caracteres especiales.
    """
    return ''.join(
        c for c in unicodedata.normalize('NFD', text)
        if unicodedata.category(c) != 'Mn'
    ).lower().strip()

# Función para dividir el texto basado en un patrón regex
def custom_regex_splitter(text, pattern):
    """
    Divide el texto basado en el patrón regex proporcionado.
    
    :param text: Texto completo a dividir.
    :param pattern: Patrón regex para dividir el texto.
    :return: Lista de objetos Document.
    """
    # Encuentra todas las coincidencias del patrón
    splits = list(re.finditer(pattern, text, re.MULTILINE | re.IGNORECASE))
    
    # Lista para almacenar los documentos
    documents = []
    
    # Iterar sobre las coincidencias y extraer los chunks
    for i in range(len(splits)):
        start = splits[i].start()
        end = splits[i+1].start() if i+1 < len(splits) else len(text)
        chunk = text[start:end]
        documents.append(Document(page_content=chunk))
    
    return documents

# Función para extraer texto del PDF y dividirlo en chunks
def extract_text_from_pdf(pdf_path):
    """
    Función para extraer texto desde un PDF utilizando LangChain.
    Divide el texto en chunks basados en los títulos de los temas.
    """
    loader = PyPDFLoader(pdf_path)
    documents = loader.load()

    # Unir todo el texto del PDF
    full_text = "\n".join([doc.page_content for doc in documents])

    # Definir un patrón regex más general para los títulos de los temas
    regex_pattern = r'^(Tema|Unidad|Capítulo)\s+\d+[\.:]?\s+.*'

    # Usar el splitter personalizado
    chunks = custom_regex_splitter(full_text, regex_pattern)

    # Depuración: Imprimir los títulos de cada chunk
    for i, chunk in enumerate(chunks):
        first_line = chunk.page_content.splitlines()[0] if chunk.page_content else 'Sin contenido'
        print(f"Chunk {i}: {first_line}")

    return chunks

# Función para extraer los temas desde un PDF
def extract_topics_from_pdf(pdf_path, max_tokens_per_chunk=4000):
    """
    Función para extraer los temas del PDF utilizando ChatDeepInfra con un límite en el contenido de los chunks.
    
    :param pdf_path: Ruta al archivo PDF.
    :param max_tokens_per_chunk: Número máximo de tokens permitidos por chunk para el modelo. Default: 4000.
    """
    # Cargar el contenido del PDF
    loader = PyPDFLoader(pdf_path)
    documents = loader.load()
    
    # Unir todo el texto del PDF
    full_text = "\n".join([doc.page_content for doc in documents])

    # Dividir el texto en trozos manejables para el modelo, respetando el límite de tokens
    text_splitter = CharacterTextSplitter(chunk_size=2000, chunk_overlap=200)
    text_chunks = text_splitter.split_text(full_text)

    # Inicializar el modelo ChatDeepInfra
    chat = ChatDeepInfra(model="meta-llama/Meta-Llama-3.1-8B-Instruct", max_tokens=max_tokens_per_chunk)

    # Lista para almacenar los temas extraídos
    topics = []

    for chunk in text_chunks:
        # Truncar el chunk si excede el número máximo de tokens
        if len(chunk) > max_tokens_per_chunk:
            chunk = chunk[:max_tokens_per_chunk]
        
        # Crear el prompt para extraer los temas en formato JSON
        prompt = f"""
        Analiza el siguiente texto y extrae una lista de los temas o títulos principales que se abordan. Proporciona la lista en formato JSON (una lista de cadenas de texto), sin ninguna explicación adicional.

        Texto:
        {chunk}

        Lista de temas (en formato JSON):
        """

        # Obtener la respuesta del modelo
        response = chat.invoke(prompt)
        response_text = response.content.strip()

        # Intentar cargar la respuesta como JSON
        try:
            topics_chunk = json.loads(response_text)
            if isinstance(topics_chunk, list):
                topics.extend([topic.strip() for topic in topics_chunk if topic.strip()])
        except json.JSONDecodeError:
            # Si no se pudo decodificar como JSON, procesar como texto
            topics_chunk = response_text.strip().split('\n')
            topics.extend([topic.strip('- ').strip() for topic in topics_chunk if topic.strip()])

    # Eliminar duplicados manteniendo el orden y limpiar comillas y espacios innecesarios
    unique_topics = list(dict.fromkeys([topic.strip('"').strip() for topic in topics]))

    return unique_topics

# Función para filtrar chunks por temas seleccionados
def filter_chunks_by_topics(chunks, selected_topics):
    """
    Función para filtrar los chunks que corresponden a los temas seleccionados.
    """
    filtered_chunks = []
    for chunk in chunks:
        chunk_text_normalized = normalize_text(chunk.page_content)
        for topic in selected_topics:
            topic_normalized = normalize_text(topic)
            if topic_normalized in chunk_text_normalized:
                print(f"Coincidencia encontrada: '{topic}' en chunk.")
                filtered_chunks.append(chunk)
                break
    return filtered_chunks

# Función para generar una guía de estudio desde el contenido filtrado
def generate_study_guide_from_content(content, student_profile=None):
    """
    Genera una guía de estudio a partir del contenido proporcionado.
    
    :param content: Texto que corresponde únicamente al tema seleccionado.
    :param student_profile: Perfil del estudiante.
    :return: Diccionario con la guía generada.
    """
    chat = ChatDeepInfra(model="meta-llama/Meta-Llama-3.1-8B-Instruct", max_tokens=4000)

    if student_profile is None:
        student_profile = {
            'proficiency_level': 'intermedio',
            'learning_style': 'visual',
            'interests': [],
            'language': 'es',
        }

    # Crear el prompt enfocado en el contenido específico
    prompt = f"""
    Eres un asistente educativo que adapta sus explicaciones al estilo de aprendizaje del estudiante.
    El estudiante tiene las siguientes características:

    - Nivel de competencia: {student_profile.get('proficiency_level', 'intermedio')}
    - Estilo de aprendizaje: {student_profile.get('learning_style', 'visual')}
    - Intereses: {', '.join(student_profile.get('interests', []))}
    - Idioma: {student_profile.get('language', 'es')}

    Tienes acceso a la siguiente sección de una guía de estudio:

    {content}

    Por favor, realiza las siguientes tareas:

    1. Explica este contenido de manera sencilla, destacando los conceptos clave.
    2. Proporciona ejemplos concretos que se relacionen con los intereses del estudiante.
    3. Incluye recomendaciones prácticas para que el estudiante pueda aplicar los conceptos en situaciones reales o ejercicios.
    4. Divide la explicación en puntos clave para que sea más fácil de seguir.
    5. Si hay definiciones, explícalas en términos sencillos, y si es posible, relaciónalas con situaciones cotidianas.
    6. Indica si el tema requiere conocimientos previos y sugiere revisiones breves de esos temas si es necesario.
    7. Genera tres preguntas de opción múltiple para evaluar la comprensión del estudiante, incluyendo las opciones y la respuesta correcta.

    Por favor, presenta la respuesta en **formato Markdown** siguiendo esta estructura:

    # Guía de estudio

    ...

    # Preguntas de práctica

    1. **Pregunta 1**
       - a) Opción A
       - b) Opción B
       - c) Opción C
       **Respuesta correcta:** c)

    2. **Pregunta 2**
       - a) Opción A
       - b) Opción B
       - c) Opción C
       **Respuesta correcta:** b)

    3. **Pregunta 3**
       - a) Opción A
       - b) Opción B
       - c) Opción C
       **Respuesta correcta:** a)
    """

    # Imprimir el prompt para depuración
    print(f"Generando guía con el siguiente prompt:\n{prompt}")

    response = chat.invoke(prompt)
    guide_text = response.content if hasattr(response, 'content') else 'No se pudo generar la guía.'

    # Imprimir la respuesta del modelo
    print(f"Respuesta del modelo:\n{guide_text}")

    return {
        'guide': guide_text,
        'progress': [True],  # Actualiza según corresponda
        'guide_content': [guide_text],  # Actualiza según corresponda
        'current_chunk_index': 0,  # Actualiza según corresponda
        'total_chunks': 1  # Actualiza según corresponda
    }


# study_generator.py

def save_study_session(user_id, selected_chunks, progress, guide_content):
    """
    Guarda una nueva sesión de estudio del usuario en la base de datos.
    
    :param user_id: ID del usuario.
    :param selected_chunks: Lista de objetos Document seleccionados.
    :param progress: Lista de booleanos indicando el progreso.
    :param guide_content: Lista de contenidos generados.
    """
    with current_app.app_context():
        # Crear una nueva instancia de UserProgress
        user_progress = UserProgress(
            user_id=user_id,
            selected_chunks=json.dumps([
                {
                    'page_content': chunk.page_content,
                    'metadata': chunk.metadata
                }
                for chunk in selected_chunks
            ], ensure_ascii=False),
            progress_data=json.dumps(progress, ensure_ascii=False),
            guide_content=json.dumps(guide_content, ensure_ascii=False)
            # timestamp se añade automáticamente
        )
        
        # Imprimir los datos antes de guardarlos para depuración
        print(f"Guardando nueva sesión de estudio para el usuario {user_id}:")
        print(f"Selected Chunks: {user_progress.selected_chunks}")
        print(f"Progress: {user_progress.progress_data}")
        print(f"Guide Content: {user_progress.guide_content}")
    
        db.session.add(user_progress)
        db.session.commit()

def load_study_session(user_id):
    """
    Carga la sesión de estudio del usuario desde la base de datos.
    
    :param user_id: ID del usuario.
    :return: Tuple de selected_chunks, progress_data, guide_content.
    """
    with current_app.app_context():
        user_progress = db.session.query(UserProgress).filter_by(user_id=user_id).first()

        if user_progress:
            selected_chunks_serializable = json.loads(user_progress.selected_chunks)
            progress_data = json.loads(user_progress.progress_data)
            guide_content = json.loads(user_progress.guide_content)
            
            # Reconstruir los objetos Document
            selected_chunks = [
                Document(
                    page_content=chunk['page_content'],
                    metadata=chunk.get('metadata', {})
                )
                for chunk in selected_chunks_serializable
            ]

            # Imprimir los datos cargados para depuración
            print(f"Cargando sesión de estudio para el usuario {user_id}:")
            print(f"Selected Chunks: {selected_chunks_serializable}")
            print(f"Progress Data: {progress_data}")
            print(f"Guide Content: {guide_content}")
            
            return selected_chunks, progress_data, guide_content
        print(f"No se encontró una sesión de estudio para el usuario {user_id}.")
        return None, None, None


