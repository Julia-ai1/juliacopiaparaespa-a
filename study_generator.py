# study_generator.py

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

# Cargar variables de entorno
load_dotenv()
os.environ["DEEPINFRA_API_TOKEN"] = os.getenv("DEEPINFRA_API_TOKEN")


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
    
    # Si no hay coincidencias, retornar todo el texto como un solo chunk
    if not splits:
        documents.append(Document(page_content=text))
        return documents
    
    # Iterar sobre las coincidencias y extraer los chunks
    for i in range(len(splits)):
        start = splits[i].start()
        end = splits[i+1].start() if i+1 < len(splits) else len(text)
        chunk = text[start:end].strip()
        if chunk:  # Asegurarse de no añadir chunks vacíos
            documents.append(Document(page_content=chunk))
    
    return documents



def extract_text_from_pdf(pdf_path):
    """
    Función para extraer texto desde un PDF utilizando LangChain.
    Divide el texto en chunks basados en los títulos de los temas.
    """
    loader = PyPDFLoader(pdf_path)
    documents = loader.load()

    # Unir todo el texto del PDF
    full_text = "\n".join([doc.page_content for doc in documents])

    # Definir el patrón regex genérico para los títulos de los temas
    regex_pattern = r'^(Unidad|Tema|Capítulo|Sección|Lección)\s+\d+(\.\d+)*[:.]\s+.*'

    # Usar el splitter personalizado
    chunks = custom_regex_splitter(full_text, regex_pattern)

    # Depuración: Imprimir los títulos de cada chunk
    for i, chunk in enumerate(chunks):
        first_line = chunk.page_content.splitlines()[0].strip().rstrip(',')
        print(f"Chunk {i}: '{first_line}'")

    return chunks




def extract_topics_from_pdf(pdf_path):
    """
    Función para extraer los temas del PDF utilizando ChatDeepInfra.
    Limpia y filtra los temas extraídos.
    """
    # Cargar el contenido del PDF
    loader = PyPDFLoader(pdf_path)
    documents = loader.load()
    
    # Unir todo el texto del PDF
    full_text = "\n".join([doc.page_content for doc in documents])

    # Dividir el texto en trozos manejables para el modelo
    text_splitter = CharacterTextSplitter(chunk_size=2000, chunk_overlap=200)
    text_chunks = text_splitter.split_text(full_text)

    # Inicializar el modelo ChatDeepInfra
    chat = ChatDeepInfra(model="meta-llama/Meta-Llama-3.1-8B-Instruct", max_tokens=4000)

    # Lista para almacenar los temas extraídos
    topics = []

    for chunk in text_chunks:
        # Crear el prompt para extraer los temas en formato JSON
        prompt = f"""
        Analiza el siguiente texto y extrae una lista de los temas o títulos principales que se abordan. 
        Proporciona la lista en formato JSON (una lista de cadenas de texto), sin ninguna explicación adicional.

        Texto:
        {chunk}

        Lista de temas (en formato JSON):
        Tema 1.
        Tema 2.
        """

        # Obtener la respuesta del modelo
        response = chat.invoke(prompt)
        response_text = response.content.strip()

        # Intentar cargar la respuesta como JSON
        try:
            topics_chunk = json.loads(response_text)
            if isinstance(topics_chunk, list):
                topics.extend([topic.strip().rstrip(',') for topic in topics_chunk if topic.strip()])
        except json.JSONDecodeError:
            # Si no se pudo decodificar como JSON, procesar como texto
            topics_chunk = response_text.strip().split('\n')
            topics.extend([topic.strip('- ').strip().rstrip(',') for topic in topics_chunk if topic.strip()])

    # Eliminar duplicados manteniendo el orden
    unique_topics = list(dict.fromkeys(topics))

    # Filtrar solo los temas que coinciden con el patrón esperado
    pattern = re.compile(r'^(Unidad|Tema|Capítulo|Sección|Lección)\s+\d+(\.\d+)*[:.]\s+.*', re.IGNORECASE)
    filtered_topics = [topic for topic in unique_topics if pattern.match(topic)]

    return filtered_topics


def extract_specific_topic_content(selected_chunk, topic_title):
    """
    Extrae únicamente el contenido del tema especificado dentro de un chunk.
    
    :param selected_chunk: Objeto Document que contiene el texto del chunk.
    :param topic_title: Título completo del tema seleccionado (e.g., "Tema 2: Números enteros").
    :return: Texto filtrado que corresponde únicamente al tema seleccionado.
    """
    content = selected_chunk.page_content
    lines = content.split('\n')
    
    start_index = None
    end_index = None
    
    # Encontrar el inicio del tema seleccionado
    for i, line in enumerate(lines):
        if topic_title.lower() in line.lower():
            start_index = i
            break
    
    if start_index is None:
        print(f"No se encontró el título del tema: {topic_title}")
        return ""
    
    # Encontrar el inicio del siguiente tema para determinar el final
    for i in range(start_index + 1, len(lines)):
        # Asumimos que los siguientes temas comienzan con "Unidad", "Tema", etc.
        if re.match(r'^(Unidad|Tema|Capítulo|Sección|Lección)\s+\d+(\.\d+)*[:.]\s+.*', lines[i].strip(), re.IGNORECASE):
            end_index = i
            break
    
    # Extraer el contenido del tema seleccionado
    if end_index:
        topic_content = '\n'.join(lines[start_index:end_index]).strip()
    else:
        # Si no se encuentra otro tema, tomar todo el texto hasta el final del chunk
        topic_content = '\n'.join(lines[start_index:]).strip()
    
    if not topic_content:
        print(f"No se pudo extraer el contenido del tema: {topic_title}")
    else:
        print(f"Contenido extraído para el tema {topic_title}:")
        # Limitar la impresión para evitar logs demasiado largos
        preview = topic_content[:200] + '...' if len(topic_content) > 200 else topic_content
        print(preview)
    
    return topic_content


def filter_chunks_by_topics(chunks, selected_topics):
    """
    Filtra los chunks que corresponden a los temas seleccionados.
    
    :param chunks: Lista de objetos Document extraídos del PDF.
    :param selected_topics: Lista de temas seleccionados.
    :return: Lista de chunks que corresponden a los temas seleccionados.
    """
    filtered_chunks = []
    for chunk in chunks:
        # Obtener el título del chunk (primera línea)
        first_line = chunk.page_content.splitlines()[0].strip().rstrip(',')
        print(f"Procesando chunk: '{first_line}'")
        for topic in selected_topics:
            # Normalizar ambos strings: eliminar caracteres no alfanuméricos y convertir a minúsculas
            normalized_chunk_title = re.sub(r'[^\w\s]', '', first_line.lower())
            normalized_topic = re.sub(r'[^\w\s]', '', topic.lower())
            if normalized_topic in normalized_chunk_title:
                print(f"Coincidencia encontrada: '{topic}' en chunk.")
                filtered_chunks.append(chunk)
                break
    return filtered_chunks

def generate_study_guide_from_content(content, student_profile=None, retries=3, delay=2):
    """
    Genera una guía de estudio a partir del contenido proporcionado con lógica de reintentos.
    
    :param content: Texto que corresponde únicamente al tema seleccionado.
    :param student_profile: Perfil del estudiante.
    :param retries: Número de intentos de reintento.
    :param delay: Tiempo de espera entre reintentos en segundos.
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

    for attempt in range(retries):
        try:
            print(f"Intento {attempt + 1} de {retries} para generar la guía de estudio.")
            response = chat.invoke(prompt)
            if hasattr(response, 'content'):
                guide_text = response.content.strip()
                if not guide_text:
                    raise ValueError("La respuesta del modelo está vacía.")
            else:
                raise ValueError("La respuesta del modelo no contiene 'content'.")

            # Imprimir la respuesta del modelo
            print(f"Respuesta del modelo:\n{guide_text}")

            return {
                'guide': guide_text,
                'progress': [True],  # Actualiza según corresponda
                'guide_content': [guide_text],  # Actualiza según corresponda
                'current_chunk_index': 0,  # Actualiza según corresponda
                'total_chunks': 1  # Actualiza según corresponda
            }
        except Exception as e:
            print(f"Error en el intento {attempt + 1}: {e}")
            if attempt < retries - 1:
                print(f"Reintentando en {delay} segundos...")
                time.sleep(delay)
            else:
                print("Se han agotado todos los intentos para generar la guía de estudio.")
                return {
                    'guide': 'Error al generar la guía de estudio después de varios intentos.',
                    'progress': [False],
                    'guide_content': [None],
                    'current_chunk_index': 0,
                    'total_chunks': 1
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