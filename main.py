from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, current_user, login_user, logout_user, login_required
# from exani import questions_exani, check_answer_exani, generate_new_questions_exani
from baccaulareat import generate_solutions_bac, retrieve_documents_bac, extract_relevant_context_bac
# from enem import generate_questions, check_answer, retrieve_documents, extract_relevant_context
from langchain_community.chat_models import ChatDeepInfra
from selectividad import generate_questions, check_answer, retrieve_documents, extract_relevant_context
import os
import requests as http_requests  # Renombrar la librería requests
import logging
from datetime import datetime, timezone
from models import db, User
import stripe
from elasticsearch import Elasticsearch
from langchain.prompts import ChatPromptTemplate
import re
from flask_talisman import Talisman
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from datetime import datetime, timedelta
import io

from werkzeug.utils import secure_filename
import os

app = Flask(__name__)
load_dotenv()


# Configuración de Azure Blob Storage
AZURE_STORAGE_CONNECTION_STRING = "DefaultEndpointsProtocol=https;AccountName=juliastorage1236;AccountKey=Tj4EdJoBTJnPGx8x5DLO1OVV5Nz8kFJyDPZWBB8dkrFyhtv3uAthYxzc5vfW+mimbvbJ1Xfq0kPU+AStRw4Ydw==;EndpointSuffix=core.windows.net"  # Coloca aquí tu cadena de conexión
blob_service_client = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
container_name = "julia"  # Asegúrate de usar el nombre del contenedor que creaste

# Función para subir archivos PDF a Azure Blob Storage
def upload_pdf_to_azure(pdf_file, user_id):
    filename = secure_filename(pdf_file.filename)
    blob_path = f"{user_id}/{filename}"  # Organizar por usuario en el contenedor
    blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_path)
    
    # Subir el archivo
    blob_client.upload_blob(pdf_file)
    print(f"Archivo {filename} subido a Azure Blob Storage.")
    
    # Generar un SAS Token para el archivo subido
    sas_token = generate_blob_sas(
        account_name=blob_client.account_name,
        container_name=container_name,
        blob_name=blob_path,
        account_key="Tj4EdJoBTJnPGx8x5DLO1OVV5Nz8kFJyDPZWBB8dkrFyhtv3uAthYxzc5vfW+mimbvbJ1Xfq0kPU+AStRw4Ydw==",  # Coloca aquí tu clave de acceso a la cuenta de Azure Storage
        permission=BlobSasPermissions(read=True),  # Solo permisos de lectura
        expiry=datetime.utcnow() + timedelta(hours=1)  # El token expira en 1 hora
    )
    
    # Generar la URL con el SAS Token
    sas_url = f"https://{blob_client.account_name}.blob.core.windows.net/{container_name}/{blob_path}?{sas_token}"
    return sas_url


# Configuración de la aplicación usando variables de entorno
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('SQLALCHEMY_DATABASE_URI')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)
# Cache configuration
app.config['CACHE_TYPE'] = 'simple'
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
# Configuración de OAuth usando variabdles de entorno
app.config['GOOGLE_CLIENT_ID'] = os.getenv('GOOGLE_CLIENT_ID')
app.config['GOOGLE_CLIENT_SECRET'] = os.getenv('GOOGLE_CLIENT_SECRET')
# app.config['PREFERRED_URL_SCHEME'] = 'https'

oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.getenv('GOOGLE_CLIENT_ID'),
    client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
    authorize_url='https://accounts.google.com/o/oauth2/auth',
    authorize_params=None,
    access_token_url='https://accounts.google.com/o/oauth2/token',
    access_token_params=None,
    refresh_token_url=None,
    redirect_uri='https://itsenem.com/callback',
    client_kwargs={'scope': 'email profile'},
)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Código para crear las tablas en el contexto de la aplicación
with app.app_context():
    db.create_all()

# Token de API como variable de entorno
os.environ["DEEPINFRA_API_TOKEN"] = os.getenv("DEEPINFRA_API_TOKEN")

# Configuración de Stripe usando variables de entorno
import stripe
stripe.api_key = os.getenv('STRIPE_API_KEY')

@app.route('/')
def landing():
    return render_template('landing.html')

@app.route('/app')
def app_index():
    if current_user.is_authenticated:
        subscription_type = current_user.subscription_type
        questions_asked = current_user.questions_asked
    else:
        subscription_type = None
        questions_asked = 0

    return render_template('index.html', subscription_type=subscription_type, questions_asked=questions_asked)

import os
from flask import Flask, request, jsonify, render_template
from werkzeug.utils import secure_filename
from langchain_chroma import Chroma  # Use Chroma from the langchain_chroma package
from langchain.embeddings.huggingface import HuggingFaceEmbeddings  # Correct embedding import
from langchain.document_loaders import PyPDFLoader
from langchain.text_splitter import CharacterTextSplitter
from sentence_transformers import SentenceTransformer

# Configuración para la carpeta de uploads
UPLOAD_FOLDER = 'uploads/'
ALLOWED_EXTENSIONS = {'pdf'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Inicializar el modelo de embeddings de Hugging Face
embedding_model = HuggingFaceEmbeddings(model_name='sentence-transformers/all-MiniLM-L6-v2')

# Inicializar Chroma para almacenar y consultar los embeddings
chroma_db_path = "./chroma_db"  # Directorio de persistencia
vectorstore = Chroma(embedding_function=embedding_model, persist_directory=chroma_db_path)


# Función para verificar si el archivo es un PDF
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

import tempfile  # Asegúrate de tener esta importación para trabajar con archivos temporales
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from werkzeug.utils import secure_filename
import os
import io
from datetime import datetime, timedelta

@app.route('/upload_pdf', methods=['POST'])
def upload_pdf():
    user_id = request.form.get('user_id')

    if 'pdfFile' not in request.files:
        return jsonify({"error": "No se ha seleccionado ningún archivo."}), 400

    pdf_file = request.files['pdfFile']
    if allowed_file(pdf_file.filename):
        # Subir el archivo PDF a Azure Blob Storage
        blob_url = upload_pdf_to_azure(pdf_file, user_id)
        print(f"Archivo subido correctamente a Azure. URL con SAS: {blob_url}")
        
        # Descargar el PDF desde Azure para extraer su contenido
        response = http_requests.get(blob_url)
        if response.status_code != 200:
            print(f"Error al descargar el PDF: {response.status_code}")
            return jsonify({"error": "No se pudo descargar el PDF desde Azure."}), 500
        else:
            print(f"PDF descargado correctamente desde {blob_url}")

        # Procesar el PDF descargado guardándolo en un archivo temporal
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
                temp_pdf.write(response.content)
                temp_pdf_path = temp_pdf.name

            print(f"PDF guardado temporalmente en {temp_pdf_path}, iniciando procesamiento con PyPDFLoader.")
            loader = PyPDFLoader(temp_pdf_path)
            documents = loader.load()
            print("PDF procesado correctamente.")
        except Exception as e:
            print(f"Error procesando el PDF: {str(e)}")
            return jsonify({"error": "Error procesando el PDF."}), 500

        # Combinar el texto extraído en una cadena única
        try:
            pdf_text = " ".join([doc.page_content for doc in documents])
            print(f"Texto extraído (primeros 500 caracteres): {pdf_text[:500]}")

            # Dividir el texto en fragmentos más pequeños
            text_splitter = CharacterTextSplitter(chunk_size=5000, chunk_overlap=0)
            texts = text_splitter.split_text(pdf_text)
            print(f"Texto dividido en {len(texts)} fragmentos.")

            # Aquí indexamos los fragmentos en el vectorstore usando solo el nombre del archivo como `pdf_id`
            pdf_id = secure_filename(pdf_file.filename)  # Solo el nombre del archivo
            print(f"PDF ID utilizado para indexación: {pdf_id}")

            # Añadir al vectorstore y verificar el contenido
            vectorstore.add_texts(texts, metadatas=[{"pdf_id": pdf_id}] * len(texts))
            print(f"Fragmentos indexados en el vectorstore: {texts[:3]}")  # Imprime los primeros 3 fragmentos

            # Retornamos el `pdf_id` como el nombre del archivo
            return jsonify({"message": "PDF subido y procesado correctamente", "url": blob_url, "pdf_id": pdf_id}), 200
        except Exception as e:
            print(f"Error durante la indexación: {str(e)}")
            return jsonify({"error": "Error durante la indexación del PDF."}), 500
    else:
        return jsonify({"error": "Formato de archivo no válido. Por favor sube un archivo PDF."}), 400



@app.route('/ask_question', methods=['POST'])
def ask_question():
    question = request.form.get('question')
    pdf_id = request.form.get('pdf_id')  # Recibimos el pdf_id

    # Si el pdf_id es una URL, extraemos solo el nombre del archivo
    if pdf_id.startswith("http"):
        pdf_id = pdf_id.split('/')[-1].split('?')[0]  # Extraer solo el nombre del archivo
    print(f"Pregunta: {question}, PDF ID (nombre del archivo): {pdf_id}")

    if not pdf_id:
        return jsonify({"error": "No se ha proporcionado un ID de PDF válido."}), 400

    try:
        # Realizar la búsqueda semántica utilizando el embedding de la pregunta y el ID del PDF como filtro
        results = vectorstore.similarity_search(query=question, filter={"pdf_id": pdf_id})

        if not results:
            print(f"No se encontraron resultados para el PDF ID: {pdf_id}")
            return jsonify({"answer": "No se encontraron resultados relevantes para esta pregunta."}), 200

        # Extraer el contexto de los resultados de la búsqueda
        context = " ".join([result.page_content for result in results])
        print(f"Contexto encontrado: {context[:500]}")

        # Generar una respuesta basada en el contexto y la pregunta
        response = generate_response(context, question)

        # Ya que `generate_response` devuelve un diccionario, puedes devolverlo directamente
        return jsonify(response), 200

    except Exception as e:
        print(f"Error durante la búsqueda en el vectorstore: {e}")
        return jsonify({"error": "Ocurrió un error durante la búsqueda"}), 500

def generate_response(context, question):
    # Aquí se asume que estás usando un modelo de DeepInfra para generar la respuesta
    chat = ChatDeepInfra(model="meta-llama/Meta-Llama-3.1-8B-Instruct", max_tokens=1000)

    # Prompt actualizado con el contexto y la pregunta
    prompt = f"""
    You are an intelligent assistant. You have access to the following context from a PDF document:
    {context}
    
    Based on the context above, please answer the following question:
    {question}
    
    Please make sure your response is relevant to the context.
    """

    # Invoca la API de DeepInfra para obtener la respuesta
    print("Generando respuesta...")
    print(prompt)
    response = chat.invoke(prompt)  # Realizamos la invocación del modelo

    # Verificar el tipo de la respuesta para extraer el texto
    if isinstance(response, dict):
        # Si la respuesta es un diccionario, busca el campo 'answer'
        answer_text = response.get('answer', 'No se pudo generar una respuesta adecuada.')
    elif hasattr(response, 'text'):
        # Si el objeto tiene un atributo 'text', úsalo
        answer_text = response.text
    elif hasattr(response, 'content'):
        # Si tiene un atributo 'content', úsalo (por si es un objeto más complejo)
        answer_text = response.content.decode('utf-8') if isinstance(response.content, bytes) else response.content
    else:
        # Si no tiene atributos reconocibles, usa una respuesta por defecto
        answer_text = "No se pudo generar una respuesta adecuada debido a un formato de respuesta desconocido."

    # Imprimir la respuesta generada para debugging
    print("Respuesta generada: ", answer_text)

    # Devolver la respuesta en formato diccionario, que luego será serializado a JSON
    return {'answer': answer_text}




from flask import Flask, render_template, request, jsonify, url_for
import os
from werkzeug.utils import secure_filename
from tipotestpdf import retrieve_random_documents, generate_questions, check_answer  # Adjust import based on your module
app.config['UPLOAD_FOLDER'] = 'uploads/'  # Ensure this directory exists or adjust accordingly

# Add route for the PDF interaction page for test purposes
@app.route('/pdf_page')
def pdf_page():
    return render_template('pdf_chat.html')

@app.route('/test_pdf_page')
def test_pdf_page():
    return render_template('pdftest.html')

es = Elasticsearch(
        cloud_id="julia:d2VzdHVzMi5henVyZS5lbGFzdGljLWNsb3VkLmNvbSQyYzM3NDIxODU0MWI0NzFlODYzMjNjNzZiNWFiZjA3MSQ5Nzk5YTRkZTEyYzg0NTU5OTlkOGVjMWMzMzM1MGFmZg==",
        basic_auth=("elastic", "VlXvDov4WtoFcBfEgFfOL6Zd")
    )
from elasticsearch import Elasticsearch
from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename
from langchain_community.document_loaders import PyPDFLoader
from langchain.prompts import ChatPromptTemplate
from langchain_community.chat_models import ChatDeepInfra
import os
import re
import logging

# Configuración de logging
logging.basicConfig(level=logging.INFO)

# Configuración de Elasticsearch
es = Elasticsearch(
    cloud_id="julia:d2VzdHVzMi5henVyZS5lbGFzdGljLWNsb3VkLmNvbSQyYzM3NDIxODU0MWI0NzFlODYzMjNjNzZiNWFiZjA3MSQ5Nzk5YTRkZTEyYzg0NTU5OTlkOGVjMWMzMzM1MGFmZg==",
    basic_auth=("elastic", "VlXvDov4WtoFcBfEgFfOL6Zd")
)
UPLOAD_FOLDER = 'uploads/'
ALLOWED_EXTENSIONS = {'pdf'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
from PyPDF2 import PdfReader
from chromadb import Client
import re
import logging
from flask import Flask, request, jsonify, send_file
import tempfile
import os
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

# Inicializamos Chroma
chroma_client = Client()

# Diccionario temporal para simular la base de datos
questions_db = {}

# Función modificada para extraer texto del PDF e indexarlo en Chroma
def extract_and_store_in_chroma(filepath, filename):
    logging.info(f"Iniciando la extracción e almacenamiento del archivo: {filename}")
    
    # Cargar el PDF
    reader = PdfReader(filepath)
    pdf_text = ""
    for page in reader.pages:
        pdf_text += page.extract_text()

    # Dividir el texto en fragmentos
    chunks = re.split(r'\n+', pdf_text)
    logging.info(f"Dividiendo el texto en {len(chunks)} fragmentos.")

    # Crear una colección en Chroma para almacenar los fragmentos del PDF
    collection_name = f"pdf_{filename}"
    collection = chroma_client.create_collection(name=collection_name)

    # Agregar los fragmentos a Chroma
    indexed_count = 0
    for idx, chunk in enumerate(chunks):
        if chunk.strip():  # Asegurarse de que no se indexen fragmentos vacíos
            collection.add(
                documents=[chunk],
                metadatas=[{"pdf_id": filename, "chunk_id": idx}],
                ids=[f"{filename}_{idx}"]
            )
            indexed_count += 1

    logging.info(f"Se han almacenado {indexed_count} fragmentos del archivo {filename} en Chroma.")

# Ruta para subir y procesar un PDF
@app.route('/upload_pdf_test', methods=['POST'])
def upload_pdf_test():
    if 'pdfFile' not in request.files:
        return jsonify({"error": "No PDF uploaded"}), 400

    pdf_file = request.files['pdfFile']
    user_id = request.form.get('user_id', 'default_user')  # Modifica según la lógica del usuario

    # Subir el archivo a Azure Blob Storage (asumiendo que esta función ya está implementada)
    blob_url = upload_pdf_to_azure(pdf_file, user_id)

    # Descargar el archivo desde la URL generada por Azure
    response = http_requests.get(blob_url)
    if response.status_code != 200:
        return jsonify({"error": "Error downloading PDF from Azure."}), 500

    # Guardar el archivo temporalmente y procesarlo
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
        temp_pdf.write(response.content)
        temp_pdf_path = temp_pdf.name

    # Procesar el PDF con PyPDF2 y almacenar en Chroma
    extract_and_store_in_chroma(temp_pdf_path, secure_filename(pdf_file.filename))

    # Generar un `pdf_id` y devolverlo
    pdf_id = secure_filename(pdf_file.filename)
    return jsonify({"message": "PDF uploaded and processed successfully", "pdf_id": pdf_id}), 200

import random



# Ruta para generar preguntas basadas en el PDF
@app.route('/generate_test_questions', methods=['POST'])
def generate_test_questions():
    num_questions = int(request.form.get('num_questions', 5))
    pdf_id = request.form.get('pdf_id')

    # Recuperar fragmentos relevantes del PDF basados en la consulta de "generar preguntas tipo test del contenido"
    query_text = "generar preguntas tipo test del contenido"  # Texto de consulta para fragmentos relevantes
    documents = retrieve_pdf_content_from_chroma(pdf_id, query_text)
    
    print("Documents recuperados:")
    print(documents)
    
    # Unir los fragmentos para formar el contenido del PDF
    pdf_content = " ".join(documents)
    print("Contenido del PDF:")
    print(pdf_content)
    
    # Generar preguntas basadas en el contenido del PDF
    chat = ChatDeepInfra(model="meta-llama/Meta-Llama-3.1-8B-Instruct")
    questions = generate_questions_test(chat, pdf_content, num_questions)
    
    print("Preguntas generadas finales:")
    print(questions)
    
    # Guardar las preguntas en la "base de datos" temporal
    questions_db[pdf_id] = questions

    return jsonify({'questions': questions})



# Ruta para obtener las preguntas generadas
@app.route('/get_generated_questions', methods=['POST'])
def get_generated_questions():
    pdf_id = request.form.get('pdf_id')

    # Recuperar preguntas desde el diccionario temporal
    questions = questions_db.get(pdf_id)
    if not questions:
        return jsonify({"error": "No questions found for this PDF"}), 404

    return jsonify({"questions": questions})


# Función para generar preguntas a partir del contenido del PDF
def generate_questions_test(chat, pdf_content, num_questions):
    system_text = f"""Eres un asistente experto que genera preguntas de opción múltiple sobre el contenido del texto proporcionado. 
    Debes generar {num_questions} preguntas variadas, con 4 opciones de respuesta cada una. Las preguntas deben ser variadas y cubrir diferentes temas dentro del texto, no concentrarse solo en un tipo de información.
    Añade tus conocimientos generales para generar preguntas que pongan a prueba diferentes habilidades, como conocimiento general, comprensión de lectura, y razonamiento lógico.
    Si encuentras términos matemáticos, utilízalos con formato LaTeX: `\\(...\\)`.
    Sigue este formato:

    Pregunta 1: ¿Cuál es la capital de Francia?
    A) Madrid
    B) París
    C) Berlín
    D) Roma"""

    human_text = f"Genera preguntas a partir del siguiente contenido del PDF:\n{pdf_content}"

    prompt = ChatPromptTemplate.from_messages([("system", system_text), ("human", human_text)])

    response = prompt | chat
    response_msg = response.invoke({"pdf_content": pdf_content, "num_questions": num_questions})
    
    response_text = response_msg.content.strip()

    questions = process_questions_test(response_text)
    print(f"Preguntas generadas: {questions}")
    
    return questions



# Función para procesar las preguntas generadas
def process_questions_test(response_text):
    questions = []
    question_blocks = re.split(r"(\*\*Pregunta|\bPregunta\b|\bPregunta \d+\b|Pregunta\s+\d+:)", response_text, flags=re.IGNORECASE)

    for i in range(1, len(question_blocks), 2):
        question_text_block = question_blocks[i] + question_blocks[i + 1]
        question_text_match = re.search(r"(.*?)(?=\n[A-D]\))", question_text_block, re.DOTALL)
        if not question_text_match:
            continue
        question_text = question_text_match.group(1).strip()
        options = re.findall(r"([A-D])\)\s*(.+)", question_text_block)
        if len(options) < 4:
            continue
        question = {
            'question': question_text,
            'choices': [option[1].strip() for option in options]
        }
        questions.append(question)
    return questions
    
def retrieve_pdf_content_from_chroma(pdf_id, question_text):
    # Obtener la colección correspondiente al PDF
    collection_name = f"pdf_{pdf_id}"
    
    # Intentar obtener la colección
    try:
        collection = chroma_client.get_collection(name=collection_name)
        print(f"Recuperada la colección: {collection_name}")
    except Exception as e:
        print(f"Error al recuperar la colección de Chroma para {collection_name}: {e}")
        return ""
    
    # Realizar una consulta usando el texto de la pregunta
    try:
        results = collection.query(
            query_texts=[question_text],  # Usar el texto de la pregunta como parte de la consulta
            n_results=10  # Recuperar solo los fragmentos más relevantes
        )
        print(f"Se han recuperado {len(results['documents'])} documentos relacionados con la pregunta.")
    except Exception as e:
        print(f"Error en la consulta a Chroma: {e}")
        return ""

    # Unir todo el contenido en un solo texto
    documents = results.get('documents', [])
    if not documents:
        print(f"No se encontraron documentos en Chroma para la pregunta '{question_text}' en el PDF {pdf_id}")
        return ""

    # Aplanar la lista de documentos si es necesario y unir en un solo string
    pdf_content = " ".join([item for sublist in documents for item in (sublist if isinstance(sublist, list) else [sublist])])
    print(f"Contenido recuperado relacionado con la pregunta (primeros 500 caracteres): {pdf_content[:500]}")

    return pdf_content

import json
@app.route('/check_test_answer', methods=['POST'])
def check_test_answer():
    try:
        # Obtener los parámetros del POST
        pdf_id = request.form.get('pdf_id')
        question = request.form.get('question')
        user_answer = request.form.get('user_answer')
        chat = ChatDeepInfra(model="meta-llama/Meta-Llama-3.1-8B-Instruct")  # Crear una instancia de ChatDeepInfra

        # Verificar si la pregunta está presente
        if not question:
            return jsonify({'correctness': 'error', 'explanation': 'Pregunta no enviada o es None.'}), 400

        # Deserializar la pregunta desde JSON
        question = json.loads(question)  # Convertir JSON en un diccionario de Python

        # 1. Preparar el prompt para determinar la respuesta correcta
        system_correct = (
            "Eres un asistente que determina la respuesta correcta a una pregunta de opción múltiple "
            "basada en el contexto proporcionado. Devuelve solo la opción correcta sin explicaciones adicionales."
        )

        # Formatear las opciones en una lista
        options_correct = "".join("- " + choice + "\n" for choice in question["choices"])
        human_correct = f'Pregunta: {question["question"]}\nOpciones:\n{options_correct}'

        # Crear el prompt para la respuesta correcta
        prompt_correct = ChatPromptTemplate.from_messages(
            [("system", system_correct), ("human", human_correct)]
        )

        # Obtener la respuesta correcta
        response_correct = prompt_correct | chat
        correct_answer = response_correct.invoke({}).content.strip()

        if not correct_answer:
            return jsonify({"correctness": "error", "explanation": "No se pudo obtener una respuesta correcta para la pregunta."}), 500

        # 2. Preparar el prompt para obtener la explicación de la respuesta
        system_explanation = (
            "Eres un asistente que proporciona una explicación detallada de por qué una respuesta es correcta o incorrecta."
        )
        human_explanation = f'Pregunta: {question["question"]}\nRespuesta correcta: {correct_answer}'

        # Crear el prompt para la explicación
        prompt_explanation = ChatPromptTemplate.from_messages(
            [("system", system_explanation), ("human", human_explanation)]
        )

        # Obtener la explicación
        response_explanation = prompt_explanation | chat
        explanation = response_explanation.invoke({}).content.strip()

        # 3. Comparar la respuesta del usuario con la respuesta correcta
        if user_answer.lower() in correct_answer.lower():
            final_explanation = (
                f"Sí, la respuesta es correcta. La respuesta correcta es '{correct_answer}'.\n"
                f"Explicación: {explanation}"
            )
            return jsonify({
                'correctness': 'correct',
                'explanation': final_explanation,
                'correct_answer': correct_answer
            }), 200
        else:
            final_explanation = (
                f"No, la respuesta es incorrecta. La respuesta correcta es '{correct_answer}', "
                f"no '{user_answer}'.\nExplicación: {explanation}"
            )
            return jsonify({
                'correctness': 'incorrect',
                'explanation': final_explanation,
                'correct_answer': correct_answer
            }), 200

    except Exception as e:
        print(f"Error en check_test_answer: {e}")
        return jsonify({'correctness': 'error', 'explanation': f"Error: {str(e)}"}), 500


#PDF
from flask import Flask, request, jsonify, send_file
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import os
# Simulación de base de datos de preguntas
questions_db = {}

@app.route('/download_test_pdf', methods=['GET'])
def download_test_pdf():
    pdf_id = request.args.get('pdf_id')
    questions = questions_db.get(pdf_id, [])
    
    pdf_path = f"/tmp/{pdf_id}_test.pdf"
    generate_pdf(questions, pdf_path)
    
    return send_file(pdf_path, as_attachment=True)

def generate_pdf(questions, filepath):
    c = canvas.Canvas(filepath, pagesize=letter)
    c.drawString(100, 750, "Preguntas Generadas")
    
    y = 700
    for i, question in enumerate(questions):
        c.drawString(100, y, f"{i+1}. {question['question']}")
        y -= 20
        for j, choice in enumerate(question['choices']):
            c.drawString(120, y, f"{chr(65 + j)}. {choice}")
            y -= 20
        y -= 10
    
    c.save()

# Ruta para renderizar la página test.html
@app.route('/test.html')
def test_page1():
    pdf_id = request.args.get('pdf_id')
    # Renderizamos la página test.html y pasamos el pdf_id a la plantilla
    return render_template('test.html', pdf_id=pdf_id)

@app.route('/login')
def login_google():
    redirect_uri = url_for('callback', _external=True)
    print("Redirigiendo")
    print(redirect_uri)
    return google.authorize_redirect(redirect_uri)



@app.route('/callback')
def callback():
    token = google.authorize_access_token()
    session['google_token'] = token
    user_info = google.get('https://www.googleapis.com/oauth2/v1/userinfo').json()

    user = User.query.filter_by(email=user_info['email']).first()
    if not user:
        # Si el usuario no existe, verifica si el nombre de usuario está tomado
        existing_user = User.query.filter_by(username=user_info['name']).first()
        if existing_user:
            # Si el nombre de usuario ya existe, modifica el nombre de usuario
            base_username = user_info['name']
            counter = 1
            new_username = f"{base_username}{counter}"
            while User.query.filter_by(username=new_username).first():
                counter += 1
                new_username = f"{base_username}{counter}"
            user_info['name'] = new_username

        user = User(
            username=user_info['name'], 
            email=user_info['email'], 
            google_id=user_info['id'],
            subscription_type='free'  # Inicializar con 'free' u otro valor según tus necesidades
        )
        db.session.add(user)
        db.session.commit()

    login_user(user)
    flash('Autenticación exitosa. ¡Bienvenido!', 'success')
    return redirect(url_for('app_index'))


@app.route('/subscribe')
@login_required
def subscribe():
    if current_user.subscription_type == 'paid':
        flash('Ya tienes una suscripción activa.', 'info')
        return redirect(url_for('index'))
    
    # Verificar si el usuario ya ha usado un trial o si su suscripción está pausada
    if has_used_trial(current_user.stripe_customer_id):
        # Redirigir a un enlace de pago sin trial
        payment_link = "https://buy.stripe.com/4gw0417Po5bTeCQaEG"  # Enlace de pago sin trial
        flash("Ya has utilizado tu período de prueba o tu suscripción está pausada. Puedes suscribirte con un plan pago.", 'info')
    else:
        # Redirigir a un enlace de pago con trial
        payment_link = "https://buy.stripe.com/4gwaIF3z8cElbqE3cc"  # Enlace de pago con trial
    
    return redirect(payment_link)


def has_used_trial(stripe_customer_id):
    """
    Función para verificar si un usuario ha utilizado un trial basado en el historial de suscripciones en Stripe.
    Devuelve True si el usuario ya ha usado un trial o si la suscripción está pausada.
    """
    if not stripe_customer_id:
        return False  # El usuario no tiene un stripe_customer_id, es un nuevo usuario

    # Obtener suscripciones previas del cliente en Stripe
    subscriptions = stripe.Subscription.list(customer=stripe_customer_id)

    # Si no hay suscripciones, el usuario no ha usado un trial
    if not subscriptions['data']:
        return False  # Usuario nuevo, puede usar el trial

    # Verificar si alguna suscripción anterior tenía un trial o está pausada
    for sub in subscriptions['data']:
        if sub.trial_end and sub.status in ['trialing', 'active', 'past_due', 'paused', 'canceled']:
            return True  # Ya ha usado un trial o la suscripción está pausada

    return False  # No ha usado un trial previamente ni tiene la suscripción pausada



@app.route('/', methods=['POST'])
def stripe_webhook():
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get('Stripe-Signature')
    endpoint_secret = os.getenv('STRIPE_ENDPOINT_SECRET')  # Usa una variable de entorno para el secreto del webhook

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except ValueError as e:
        # Invalid payload
        return jsonify({'error': str(e)}), 400
    except stripe.error.SignatureVerificationError as e:
        # Invalid signature
        return jsonify({'error': str(e)}), 400

    # Handle the event types
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        handle_checkout_session(session)
    elif event['type'] == 'customer.subscription.created' or event['type'] == 'customer.subscription.updated':
        subscription = event['data']['object']
        handle_subscription_update(subscription)
    elif event['type'] == 'customer.subscription.deleted':
        subscription = event['data']['object']
        handle_subscription_cancellation(subscription)
    elif event['type'] == 'invoice.payment_failed':
        invoice = event['data']['object']
        handle_payment_failed(invoice)
    elif event['type'] == 'customer.subscription.updated':
        subscription = event['data']['object']
        handle_subscription_update(subscription)

    return '', 200


def handle_checkout_session(session):
    customer_email = session.get('customer_details', {}).get('email')
    stripe_customer_id = session.get('customer')  # Obtener el Stripe customer ID
    user = User.query.filter_by(email=customer_email).first()
    
    if user:
        user.subscription_type = 'paid'
        user.subscription_start = datetime.now(timezone.utc)
        user.stripe_subscription_id = session.get('subscription')
        user.stripe_customer_id = stripe_customer_id  # Guardar el customer_id en la base de datos
        db.session.commit()


def handle_subscription_cancellation(subscription):
    user = User.query.filter_by(stripe_subscription_id=subscription.id).first()
    if user:
        user.subscription_type = 'free'
        user.stripe_subscription_id = None
        db.session.commit()

def handle_payment_failed(invoice):
    # Obtener el ID de cliente y buscar al usuario
    customer_id = invoice['customer']
    user = User.query.filter_by(stripe_customer_id=customer_id).first()
    
    if user:
        # Actualizar la suscripción del usuario a 'free' o notificar sobre el fallo de pago
        user.subscription_type = 'free'
        db.session.commit()
        # Aquí puedes enviar una notificación al usuario si lo deseas


def handle_subscription_update(subscription):
    customer_id = subscription['customer']
    user = User.query.filter_by(stripe_customer_id=customer_id).first()
    
    if user:
        # Evitar sobrescribir el estado si ya está marcado para cancelarse
        if user.subscription_type == 'canceled_pending':
            return
        
        if subscription['status'] == 'trialing':
            user.subscription_type = 'trial'
        elif subscription['status'] == 'active':
            user.subscription_type = 'paid'
        elif subscription['status'] == 'past_due':
            user.subscription_type = 'past_due'
        elif subscription['status'] == 'canceled':
            user.subscription_type = 'canceled'
        elif subscription['status'] == 'paused':
            user.subscription_type = 'paused'

        user.stripe_customer_id = customer_id
        db.session.commit()



@app.route('/cancel_subscription', methods=['POST'])
@login_required
def cancel_subscription():
    user = current_user
    if user.stripe_subscription_id:
        try:
            response = stripe.Subscription.modify(
                user.stripe_subscription_id,
                cancel_at_period_end=True
            )
            print(f"Stripe modify response: {response}")
            user.subscription_type = 'canceled_pending'
            db.session.commit()
            print(f"Subscription marked as canceled_pending for user: {user.email}")
        except stripe.error.StripeError as e:
            print(f"Error during subscription cancellation: {e}")
    else:
        print("No active subscription found to cancel.")

    return redirect(url_for('app_index'))



@app.route('/select_exam', methods=['POST'])
@login_required
def select_exam():
    if current_user.subscription_type not in ['trial', 'paid', 'free']:
        flash('Necesitas una suscripción activa para acceder a los exámenes.', 'warning')
        return redirect(url_for('app_index'))
    exam_type = request.form.get('exam_type')
    if not exam_type:
        return "No se ha seleccionado ningún examen", 400
    
    return render_template('speciality.html', exam_type=exam_type)

def format_solutions(solutions_text):
    solutions_raw = solutions_text.split("\n\n")
    formatted_solutions = []

    for raw_solution in solutions_raw:
        title_match = re.search(r'^\*\*(.*?)\*\*', raw_solution)
        title = title_match.group(1) if title_match else "Solución"
        text = re.sub(r'^\*\*(.*?)\*\*', '', raw_solution).strip()

        formatted_solutions.append({
            "title": title,
            "text": text,
            "note": None
        })

    return formatted_solutions


@app.route('/generate_exam', methods=['POST'])
def generate_exam():
    # Obtener los valores ingresados en el formulario
    segmento = request.form['segmento']
    asignatura = request.form['asignatura']
    num_items = int(request.form['num_items'])

    # Inicializar el modelo de chat
    chat = ChatDeepInfra(model="meta-llama/Meta-Llama-3.1-8B-Instruct", max_tokens=4000)
    results = []

    # Configuración de Elasticsearch con el cloud_id proporcionado
    es = Elasticsearch(
        cloud_id="julia:d2VzdHVzMi5henVyZS5lbGFzdGljLWNsb3VkLmNvbSQyYzM3NDIxODU0MWI0NzFlODYzMjNjNzZiNWFiZjA3MSQ5Nzk5YTRkZTEyYzg0NTU5OTlkOGVjMWMzMzM1MGFmZg==",
        basic_auth=("elastic", "VlXvDov4WtoFcBfEgFfOL6Zd")
    )

    # Recuperar documentos relevantes usando el segmento ingresado
    print(f"Recuperando documentos para el segmento: {segmento}")
    relevant_docs = retrieve_documents(segmento, es, "exam_questions_sel", 20)

    # Verificar los documentos recuperados
    if not relevant_docs:
        print("No se recuperaron documentos de Elasticsearch.")
    else:
        print(f"Documentos recuperados: {len(relevant_docs)}")

    # Extraer el contexto
    context = extract_relevant_context(relevant_docs)
    print(f"Contexto extraído: {context[:200]}...")  # Muestra los primeros 200 caracteres del contexto

    reintentos = 0
    max_reintentos = 5  # Límite máximo de reintentos
    questions_generated = 0

    while questions_generated < num_items and reintentos < max_reintentos:
        try:
            print(f"Generando preguntas. Reintento: {reintentos + 1}")
            # Generar preguntas usando la función generate_questions
            questions = generate_questions(chat, context, num_items - questions_generated, segmento, asignatura)

            # Verificar las preguntas generadas
            if not questions:
                print("No se generaron preguntas.")
            else:
                print(f"Preguntas generadas por la IA: {len(questions)}")

            # Validar preguntas generadas
            valid_questions = []
            for question in questions:
                # Añadir manualmente la asignatura y segmento a cada pregunta
                question['subject'] = asignatura
                question['topic'] = segmento

                if validate_question(question):
                    valid_questions.append(question)
                else:
                    print(f"Pregunta inválida: {question}")

            # Agregar preguntas válidas a los resultados
            results.extend(valid_questions)
            questions_generated = len(results)

            print(f"Preguntas válidas generadas hasta ahora: {questions_generated} de {num_items}")

            # Si no se alcanzó el número requerido de preguntas, incrementar reintentos
            if questions_generated < num_items:
                print(f"No se generaron suficientes preguntas válidas. Reintento {reintentos + 1}...")
                reintentos += 1

        except Exception as e:
            print(f"Error al generar preguntas: {str(e)}")
            reintentos += 1

    if questions_generated < num_items:
        print(f"Advertencia: No se pudieron generar todas las preguntas válidas. Se generaron {questions_generated} de {num_items}.")

    # Guardar las preguntas generadas en la base de datos antes de que el usuario responda
    for question in results:
        user_question = UserQuestion(
            user_id=current_user.id,
            question=question['question'],
            user_answer=None,  # No hay respuesta aún
            correct_answer=None,  # La respuesta correcta se verificará después
            is_correct=False,  # Esto se actualizará al comprobar la respuesta del usuario
            subject=question['subject'],  # Asignatura
            topic=question['topic']  # Segmento
        )
        db.session.add(user_question)

    # Confirmar los cambios en la base de datos
    db.session.commit()

    # Incrementa el contador de preguntas para el usuario actual
    current_user.increment_questions()

    # Renderizar las preguntas en el HTML (quiz.html)
    return render_template('quiz.html', questions=results)




# Función para validar preguntas
def validate_question(question):
    """
    Verifica que la pregunta tenga los campos necesarios y estén correctamente formateados.
    """
    if not question:
        return False
    if 'question' not in question or not question['question']:
        return False
    if 'choices' not in question or not question['choices']:
        return False
    if len(question['choices']) < 2:  # Asegurar que haya al menos dos opciones
        return False
    return True


@app.route('/chat', methods=['POST'])
def chat():
    user_message = request.json['message']
    chat = ChatDeepInfra(model="meta-llama/Meta-Llama-3.1-8B-Instruct", max_tokens=4000)
    system_text = "Eres un asistente de examen que proporciona respuestas generales a preguntas relacionadas con el examen. Responde en brasileño"
    human_text = user_message
    prompt = ChatPromptTemplate.from_messages([("system", system_text), ("human", human_text)])
    
    response = prompt | chat
    response_msg = response.invoke({})
    response_text = response_msg.content
    
    return jsonify({"response": response_text})


from models import UserQuestion  # Asegúrate de importar el modelo UserQuestion que se creó anteriormente
from flask_login import current_user

@app.route('/check', methods=['POST'])
def check():
    data = request.get_json()
    
    # Verificar si se recibieron datos
    if not data:
        return jsonify({"error": "No se recibieron datos"}), 400
    
    questions = data.get('questions')
    user_answers = data.get('answers')

    if not questions or not user_answers:
        return jsonify({"error": "Faltan preguntas o respuestas"}), 400

    chat = ChatDeepInfra(model="meta-llama/Meta-Llama-3.1-8B-Instruct", max_tokens=4000)
    results = []

    for i, question in enumerate(questions):
        question_name = f'question_{i+1}'
        user_answer = user_answers.get(question_name)

        if not user_answer:
            results.append({
                'question': question,
                'selected_option': None,
                'correct': "incorrect",
                'explanation': "No se proporcionó ninguna respuesta"
            })
            continue

        try:
            correctness, explanation, correct_answer = check_answer(question, user_answer, chat)

            # Actualizar la pregunta existente en la base de datos con la respuesta del usuario
            user_question = UserQuestion.query.filter_by(user_id=current_user.id, question=question['question']).first()
            if user_question:
                user_question.user_answer = user_answer
                user_question.correct_answer = correct_answer
                user_question.is_correct = (correctness == "correct")
                db.session.commit()  # Confirmar cambios en la base de datos

            results.append({
                'question': question,
                'selected_option': user_answer,
                'correct': correctness,
                'explanation': explanation
            })
        except Exception as e:
            results.append({
                'question': question,
                'selected_option': user_answer,
                'correct': "error",
                'explanation': f"Error al procesar la respuesta: {str(e)}"
            })

    return jsonify(results)





from collections import defaultdict

@app.route('/saved_questions')
@login_required
def saved_questions():
    user_questions = UserQuestion.query.filter_by(user_id=current_user.id).all()

    # Agrupar las preguntas por asignatura y tema
    user_questions_by_subject = defaultdict(lambda: defaultdict(list))

    for question in user_questions:
        user_questions_by_subject[question.subject][question.topic].append(question)

    return render_template('saved_questions.html', user_questions_by_subject=user_questions_by_subject)



@app.route('/checkout')
def checkout():
    return render_template('checkout.html')

@app.route('/payment')
def payment():
    return render_template('payment.html')

@app.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': 'Test Product',
                    },
                    'unit_amount': 2000,  # Amount in cents
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=url_for('success', _external=True),
            cancel_url=url_for('cancel', _external=True),
        )
        return jsonify(id=checkout_session.id)
    except Exception as e:
        return jsonify(error=str(e)), 400


# Webhook route to handle Stripe events
import stripe

@app.route('/', methods=['POST'])
def webhook():
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get('Stripe-Signature')
    endpoint_secret = 'whsec_xpqBGgt4EGordrpUfEvwR3OFOgSgKIFm'  # Asegúrate de que esta sea la clave secreta correcta

    print("Payload recibido:", payload)  # Imprimir el payload recibido
    print("Cabecera de firma recibida:", sig_header)  # Imprimir la cabecera de firma recibida

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )
        print("Firma validada exitosamente.")
    except ValueError as e:
        # Payload inválido
        print("Error: Payload inválido:", e)
        return '', 400
    except stripe.error.SignatureVerificationError as e:
        # Firma inválida
        print("Error de verificación de firma:", e)
        print("Cabecera de firma esperada:", endpoint_secret)  # Imprimir la clave de firma esperada para comparación
        return '', 400

    # Manejar el evento (por ejemplo, un pago completado)
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        handle_checkout_session(session)

    return '', 200

@app.route('/charge', methods=['POST'])
def charge():
    # `stripeToken` is obtained from the form submission
    token = request.form['stripeToken']

    try:
        # Use Stripe's library to make requests...
        charge = stripe.Charge.create(
            amount=2000,  # $20.00
            currency='usd',
            description='Example charge',
            source=token,
        )
        return render_template('success.html', amount=20)
    except stripe.error.StripeError as e:
        # Handle error
        return str(e)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001) 