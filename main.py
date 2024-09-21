from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
from decorators import pro_required
# from exani import questions_exani, check_answer_exani, generate_new_questions_exani
from baccaulareat import generate_solutions_bac, retrieve_documents_bac, extract_relevant_context_bac
# from enem import generate_questions, check_answer, retrieve_documents, extract_relevant_context
from langchain_community.chat_models import ChatDeepInfra
from selectividad import generate_questions, check_answer, retrieve_documents, extract_relevant_context, process_questions
from study_guide_generator import generate_study_guide_from_pdf, save_progress, load_progress
import os
import tempfile
import os
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, current_user, login_user, logout_user, login_required
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
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
from datetime import datetime, timedelta
import io
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
from PyPDF2 import PdfReader
import tempfile
import os
import logging
from werkzeug.utils import secure_filename
import os

# Configuración de Azure AI Search
SEARCH_SERVICE_ENDPOINT = os.getenv("SEARCH_SERVICE_ENDPOINT")
SEARCH_API_KEY = os.getenv("SEARCH_API_KEY")
INDEX_NAME = os.getenv("INDEX_NAME")
search_client = SearchClient(endpoint=SEARCH_SERVICE_ENDPOINT,
                             index_name=INDEX_NAME,
                             credential=AzureKeyCredential(SEARCH_API_KEY))
app = Flask(__name__)
load_dotenv()

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
app.config['PREFERRED_URL_SCHEME'] = 'https'

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
    redirect_uri='https://aihelpstudy.com/callback',
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
#Empieza aqui lo de los pdfs y tipo test de pdfs

import re
def normalize_pdf_id(filename):
    # Reemplaza cualquier carácter no permitido por un guion bajo o guion
    return re.sub(r'[^A-Za-z0-9_\-]', '_', filename)

# Modifica la lógica de subida del PDF
@app.route('/upload_pdf', methods=['POST'])
def upload_pdf():
    try:
        # Verificar si se ha enviado el archivo PDF
        if 'pdfFile' not in request.files:
            print("No se ha seleccionado ningún archivo.")
            return jsonify({"error": "No se ha seleccionado ningún archivo."}), 400

        pdf_file = request.files['pdfFile']
        user_id = current_user.id

        print(f"Archivo recibido: {pdf_file.filename}")
        print(f"Usuario: {user_id}")

        # Guardar el PDF temporalmente
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
            temp_pdf.write(pdf_file.read())
            temp_pdf_path = temp_pdf.name

        print(f"Archivo temporal guardado en: {temp_pdf_path}")

        # Normalizar el nombre del archivo para que sea una clave válida en Azure Search
        pdf_id = normalize_pdf_id(secure_filename(pdf_file.filename))
        print(f"Nombre del archivo normalizado para Azure Search (pdf_id): {pdf_id}")

        # Subir el PDF por páginas a Azure Search
        extract_and_store_in_azure_search(temp_pdf_path, pdf_id, user_id)

        # Eliminar el archivo temporal
        os.remove(temp_pdf_path)
        print("Archivo temporal eliminado.")

        return jsonify({"message": "PDF subido y procesado correctamente", "pdf_id": pdf_id}), 200
    
    except Exception as e:
        print(f"Error durante la carga del PDF: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/get_pdfs', methods=['GET'])
def get_pdfs():
    try:
        # Obtener el user_id desde los parámetros de la solicitud
        user_id = current_user.id

        if not user_id:
            return jsonify({'error': 'El user_id es necesario para filtrar los PDFs'}), 400

        # Realizar una consulta para obtener documentos en Azure AI Search filtrados por user_id
        search_results = search_client.search(search_text="*", filter=f"user_id eq '{user_id}'", top=100)

        # Crear un diccionario para almacenar los documentos únicos por pdf_id (nombre principal)
        pdfs = {}

        for result in search_results:
            # Agrupar por 'pdf_id' para mostrar solo el nombre principal del documento
            pdf_id = result.get('pdf_id', 'Desconocido')
            if pdf_id not in pdfs:
                pdfs[pdf_id] = {
                    'name': pdf_id,  # Usar el 'pdf_id' como el nombre del documento principal
                    'id': pdf_id  # El ID principal del PDF
                }

        # Convertir a lista para enviar al frontend
        return jsonify({'pdfs': list(pdfs.values())})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Función para verificar si el archivo es un PDF
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Función para leer el contenido de un PDF
def extract_pdf_content(pdf_path):
    reader = PdfReader(pdf_path)
    pdf_text = ""
    
    # Leer el contenido de cada página del PDF y concatenarlo en una sola cadena
    for page in reader.pages:
        pdf_text += page.extract_text()

    # Retornar el contenido completo sin dividirlo en fragmentos
    return pdf_text  # Devolvemos el texto completo del PDF en una sola cadena


@app.route('/ask_question', methods=['POST'])
@login_required
def ask_question():
    question = request.form.get('question')
    pdf_id = request.form.get('pdf_id')  # El `pdf_id` ahora se usa para agrupar fragmentos.
    user_id = current_user.id  # Obtener el `user_id` del usuario autenticado.

    if not pdf_id or not question:
        return jsonify({"error": "No se ha proporcionado un ID de PDF válido o la pregunta está vacía."}), 400

    try:
        # Realizar una búsqueda en Azure Cognitive Search para obtener fragmentos relevantes basados en `pdf_id`, `user_id`, y `question`
        results = search_client.search(
            search_text=question,  # El texto de la pregunta
            filter=f"pdf_id eq '{pdf_id}' and user_id eq '{str(user_id)}'",  # Convertir user_id a cadena
            top=10  # Limitar a los primeros 10 fragmentos relevantes
        )

        # Extraer los fragmentos relevantes
        fragments = [doc['content'] for doc in results]

        if not fragments:
            return jsonify({"answer": "No se encontraron fragmentos relevantes para esta pregunta."}), 200

        # Combinar los fragmentos recuperados
        combined_content = " ".join(fragments)
        
        # Generar una respuesta basada en los fragmentos combinados y la pregunta
        response = generate_response(combined_content, question)

        return jsonify(response), 200

    except Exception as e:
        logging.error(f"Error durante la búsqueda en Azure Search: {e}")
        return jsonify({"error": "Ocurrió un error durante la búsqueda."}), 500

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

# Add route for the PDF interaction page for test purposes
@app.route('/pdf_page')
def pdf_page():
    return render_template('pdf_chat.html')

@app.route('/test_pdf_page')
def test_pdf_page():
    return render_template('pdftest.html')


# Función modificada para extraer texto del PDF e indexarlo en Chroma
from PyPDF2 import PdfReader

def extract_and_store_in_azure_search(filepath, filename, user_id):
    logging.info(f"Iniciando la indexación del archivo por páginas: {filename}")

    # Leer el contenido completo del PDF
    reader = PdfReader(filepath)

    # Iterar sobre cada página del PDF
    for page_number, page in enumerate(reader.pages):
        # Extraer el contenido de la página
        pdf_text = page.extract_text()

        # Crear un documento por cada página con un fragment_id único
        document = {
            "pdf_id": filename,  # ID principal del PDF, compartido por todas las páginas
            "fragment_id": f"{filename}_page_{page_number}",  # ID único para cada página
            "content": pdf_text[:2000],  # Limitar el contenido de cada página si es necesario
            "user_id": str(user_id),
            "page_number": page_number
        }

        # Imprimir el documento para verificar su estructura
        logging.info(f"Documento a subir a Azure Search: {document}")

        # Subir el fragmento de la página a Azure Search
        try:
            result = search_client.upload_documents(documents=[document])
            logging.info(f"Página {page_number} del documento {filename} subida correctamente.")
        except Exception as e:
            logging.error(f"Error al subir la página {page_number} del documento {filename}: {e}")
            return None


# Ruta para subir y procesar un PDF
@app.route('/upload_pdf_test', methods=['POST'])
def upload_pdf_test():
    try:
        # Verificar si se ha enviado el archivo PDF
        if 'pdfFile' not in request.files:
            print("No se ha seleccionado ningún archivo.")
            return jsonify({"error": "No se ha seleccionado ningún archivo."}), 400

        pdf_file = request.files['pdfFile']
        user_id = current_user.id

        print(f"Archivo recibido: {pdf_file.filename}")
        print(f"Usuario: {user_id}")

        # Guardar el PDF temporalmente
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
            temp_pdf.write(pdf_file.read())
            temp_pdf_path = temp_pdf.name

        print(f"Archivo temporal guardado en: {temp_pdf_path}")

        # Normalizar el nombre del archivo para que sea una clave válida en Azure Search
        pdf_id = normalize_pdf_id(secure_filename(pdf_file.filename))
        print(f"Nombre del archivo normalizado para Azure Search (pdf_id): {pdf_id}")

        # Subir el PDF por páginas a Azure Search
        extract_and_store_in_azure_search(temp_pdf_path, pdf_id, user_id)

        # Eliminar el archivo temporal
        os.remove(temp_pdf_path)
        print("Archivo temporal eliminado.")

        return jsonify({"message": "PDF subido y procesado correctamente", "pdf_id": pdf_id}), 200
    
    except Exception as e:
        print(f"Error durante la carga del PDF: {str(e)}")
        return jsonify({"error": str(e)}), 500
import random


# Ruta para generar preguntas basadas en el PDF
import openai
questions_db = {}
openai.api_key = os.getenv("OPENAI_API_KEY")
@app.route('/generate_test_questions', methods=['POST'])
def generate_test_questions():
    num_questions = int(request.form.get('num_questions', 5))
    pdf_id = request.form.get('pdf_id')

    query_text = "Genera preguntas tipo test aleatoriamente del texto"
    pdf_content = retrieve_pdf_content_from_azure_search(pdf_id, query_text)

    if not pdf_content:
        return jsonify({"error": "No se encontraron fragmentos relevantes en el PDF."}), 404


    questions = generate_questions_test(pdf_content, num_questions)

    if not questions:
        return jsonify({"error": "Error al generar las preguntas."}), 500

    questions_db[pdf_id] = questions

    return jsonify({'questions': questions})

@app.route('/get_generated_questions', methods=['POST'])
def get_generated_questions():
    pdf_id = request.form.get('pdf_id')
    questions = questions_db.get(pdf_id)
    if not questions:
        return jsonify({"error": "No se encontraron preguntas para este PDF"}), 404

    return jsonify({"questions": questions})

from openai import OpenAI
openai.api_key = os.getenv("OPENAI_API_KEY")
# Inicializar el cliente de OpenAI
client = OpenAI(api_key=openai.api_key)

def generate_questions_test(pdf_content, num_questions):
    prompt = f"""Eres un asistente experto que genera preguntas de opción múltiple sobre el contenido proporcionado.
    Debes generar {num_questions} preguntas variadas, con 4 opciones de respuesta cada una, e indicar la respuesta correcta.
    Las preguntas deben estar relacionadas con el texto y cubrir diferentes temas.
    Formatea las preguntas de esta manera:

    Pregunta: [Enunciado de la pregunta]
    A) [Opción A]
    B) [Opción B]
    C) [Opción C]
    D) [Opción D]
    Respuesta correcta: [Letra de la opción correcta]

    Contenido del texto:
    {pdf_content}

    Por favor, proporciona solo las preguntas con sus opciones y respuestas correctas, sin información adicional.
    """

    try:
        # Cambiar a la nueva API
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Eres un asistente experto en generar preguntas tipo test."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=2000,
            temperature=0.7
        )

        # Ahora se usa model_dump() para extraer el resultado
        generated_text = response.model_dump()['choices'][0]['message']['content'].strip()
        print("generated_text")
        print(generated_text)
        questions = process_questions_test(generated_text)
        return questions

    except Exception as e:
        print(f"Error al generar preguntas: {e}")
        return None

def process_questions_test(generated_text):
    questions = []
    lines = generated_text.strip().split('\n')
    question = {}

    for line in lines:
        line = line.strip()

        # Detecta el comienzo de una nueva pregunta
        if line.startswith('Pregunta'):
            if question:
                questions.append(question)
                question = {}
            question_text = line.replace('Pregunta', '').strip()
            question['question'] = question_text
            question['options'] = []  # Añadir lista vacía para las opciones

        # Añade las opciones a la pregunta
        elif line.startswith(('A)', 'B)', 'C)', 'D)')):
            option_text = line[2:].strip()
            question['options'].append(option_text)

        # Añade la respuesta correcta
        elif line.startswith('Respuesta correcta'):
            correct_answer = line.replace('Respuesta correcta:', '').strip()
            question['correct_answer'] = correct_answer

    # Añade la última pregunta procesada si no ha sido añadida antes
    if question:
        questions.append(question)

    return questions

# Asegúrate de definir 'retrieve_pdf_content_from_azure_search' o reemplázalo por tu propia lógica.

import re

def escape_query_string(query):
    """Escapa caracteres especiales en la cadena de consulta para Azure Search."""
    query = re.sub(r'[\+\-\&\|\!\(\)\{\}\[\]\^"~\*\?:\\\/]', ' ', query)  # Reemplazar caracteres no válidos
    return query

def limit_characters(text, max_characters=5000):
    """Limitar el contenido a un número máximo de caracteres"""
    if len(text) > max_characters:
        return text[:max_characters]
    return text

def retrieve_pdf_content_from_azure_search(pdf_id, query_text, max_characters=8000):
    try:
        # Limpiar el query_text antes de la búsqueda
        query_text = escape_query_string(query_text)

        # Realizar una búsqueda en Azure Cognitive Search para obtener fragmentos relevantes
        results = search_client.search(
            search_text=query_text,  # El texto de la pregunta o consulta
            filter=f"pdf_id eq '{pdf_id}'",  # Filtrar por ID del PDF
            top=10,  # Limitar el número de fragmentos devueltos
            query_type="full"  # Buscar coincidencias completas
        )

        # Verificar si se han recuperado resultados
        relevant_fragments = []
        current_length = 0
        
        for result in results:
            content = result.get('content', '')
            if content:
                # Solo agregar contenido si todavía estamos por debajo del límite de caracteres
                if current_length + len(content) <= max_characters:
                    relevant_fragments.append(content)
                    current_length += len(content)
                else:
                    # Si agregar este fragmento excedería el límite, solo agregar una parte del mismo
                    remaining_chars = max_characters - current_length
                    relevant_fragments.append(content[:remaining_chars])
                    break

        # Si no se encuentra contenido relevante
        if not relevant_fragments:
            logging.info(f"No se encontraron resultados relevantes para el pdf_id: {pdf_id} y la consulta: {query_text}")
            return ""

        # Concatenar los fragmentos obtenidos en un solo bloque de texto
        pdf_content = " ".join(relevant_fragments)
        logging.info(f"Contenido recuperado de Azure Search (primeros 500 caracteres): {pdf_content[:500]}")
        return pdf_content
    
    except Exception as e:
        logging.error(f"Error al buscar contenido en Azure Search: {e}")
        return ""


import json

@app.route('/check_test_answer', methods=['POST'])
def check_test_answer():
    try:
        # Obtener los parámetros del POST
        pdf_id = request.form.get('pdf_id')
        question = request.form.get('question')
        user_answer = request.form.get('user_answer')

        # Logging para depuración
        print(f"PDF ID recibido: {pdf_id}")
        print(f"Pregunta recibida: {question}")
        print(f"Respuesta del usuario recibida: {user_answer}")

        # Verificar si la pregunta está presente
        if not question:
            print("Error: No se ha enviado una pregunta.")
            return jsonify({'correctness': 'error', 'explanation': 'Pregunta no enviada o es None.'}), 400

        # Deserializar la pregunta desde JSON
        question_data = json.loads(question)

        # Recuperar el contexto del PDF desde Azure Cognitive Search
        query_text = question_data["question"]
        pdf_content = retrieve_pdf_content_from_azure_search(pdf_id, query_text)

        if not pdf_content:
            print(f"Error: No se encontró contenido relevante en el PDF para esta pregunta (pdf_id: {pdf_id}).")
            return jsonify({"error": "No se encontró contenido relevante en el PDF para esta pregunta."}), 404

        # Preparar el prompt para determinar la respuesta correcta en función del contexto
        prompt_correct = f"""
        Eres un asistente que determina la respuesta correcta a una pregunta de opción múltiple
        basada en el contexto proporcionado. 
        Pregunta: {question_data['question']}
        Opciones:
        {"".join(f"{chr(65+i)}) {option}\n" for i, option in enumerate(question_data['options']) )}
        Contexto del PDF:
        {pdf_content}
        """

        # Crear la solicitud a la API de OpenAI para determinar la respuesta correcta
        response_correct = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Determina la respuesta correcta."},
                {"role": "user", "content": prompt_correct}
            ]
        )

        # Acceder correctamente al contenido del mensaje
        correct_answer = response_correct.choices[0].message.content.strip()

        if not correct_answer:
            return jsonify({"correctness": "error", "explanation": "No se pudo obtener una respuesta correcta."}), 500

        # Preparar el prompt para obtener la explicación de la respuesta correcta
        prompt_explanation = f"""
        Eres un asistente que proporciona una explicación concisa y clara de por qué una respuesta es correcta o incorrecta
        basada en el contexto proporcionado.
        Pregunta: {question_data['question']}
        Respuesta correcta: {correct_answer}
        Contexto del PDF:
        {pdf_content}
        """

        # Crear la solicitud a la API de OpenAI para obtener la explicación
        response_explanation = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Proporciona una explicación detallada."},
                {"role": "user", "content": prompt_explanation}
            ]
        )

        # Acceder correctamente al contenido del mensaje
        explanation = response_explanation.choices[0].message.content.strip()

        # Comparar la respuesta del usuario con la respuesta correcta
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
    redirect_uri = url_for('callback', _external=True, _scheme='https')
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
        payment_link = "https://buy.stripe.com/dR6eYV7Po7k1cuI6op"  # Enlace de pago sin trial
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

    # Si no hay suscripciones, el usuario no ha usadso un trial
    if not subscriptions['data']:
        return False  # Usuario nuevo, puede usar el trial

    # Verificar si alguna suscripción anterior tenía un trial o está pausada
    for sub in subscriptions['data']:
        if sub.trial_end and sub.status in ['trialing', 'trial', 'active', 'past_due', 'paused', 'canceled']:
            return True  # Ya ha usado un trial o la suscripción está pausada

    return False  # No ha usado un trial previamente ni tiene la suscripción pausada



@app.route('/', methods=['POST'])
def stripe_webhook():
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get('Stripe-Signature')
    endpoint_secret = "whsec_kLfD8vN65B47s55VkehEjBdxg6CK2llW" # Usa una variable de entorno para el secreto del webhook

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
            # Verificar si hay un método de pago asociado
            if subscription.get('default_payment_method'):
                user.subscription_type = 'paid'
            else:
                user.subscription_type = 'paused'
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

 # Ajusta los modelos según tu aplicación
import random
import urllib.parse

@app.route('/generate_exam', methods=['POST'])
def generate_exam():
    segmento = request.form['segmento']
    asignatura = request.form['asignatura']
    num_items = int(request.form['num_items'])

    # Configuración de Elasticsearch con tus credenciales
    es = Elasticsearch(
        cloud_id="julia:d2VzdHVzMi5henVyZS5lbGFzdGljLWNsb3VkLmNvbSQyYzM3NDIxODU0MWI0NzFlODYzMjNjNzZiNWFiZjA3MSQ5Nzk5YTRkZTEyYzg0NTU5OTlkOGVjMWMzMzM1MGFmZg==",
        basic_auth=("elastic", "VlXvDov4WtoFcBfEgFfOL6Zd")
    )

    # Recuperar documentos relevantes usando el segmento ingresado
    print(f"Recuperando documentos para el segmento: {segmento}")
    relevant_docs = retrieve_documents(segmento, es, "exam_questions_sel", 20)
    if not relevant_docs:
        print("No se recuperaron documentos relevantes.")
        return jsonify({"error": "No se recuperaron documentos."})

    context = extract_relevant_context(relevant_docs)
    print(f"Contexto extraído: {context[:500]}")  # Muestra el contenido del contexto

    results = []
    reintentos = 0
    max_reintentos = 5
    questions_generated = 0

    while questions_generated < num_items and reintentos < max_reintentos:
        try:
            # Crear el prompt para GPT-4o-mini
            system_text = (
                f"Eres un asistente que genera preguntas de matemáticas para el segmento '{segmento}' sobre la asignatura '{asignatura}'. "
                f"Usa el siguiente contexto para generar preguntas tipo test con opciones y respuestas claras. Si no tienes suficiente contexto, utiliza conocimientos generales."
            )

            human_text = (
                f"A continuación tienes el contexto:\n"
                f"{context}\n\n"
                f"Genera {num_items} preguntas tipo test, cada una con 4 opciones de respuesta y señala cuál es la correcta. Las preguntas deben estar relacionadas con el tema '{segmento}'."
            )
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_text},
                    {"role": "user", "content": human_text}
                ],
                max_tokens=2000,
                temperature=0.7
            )

            # Procesar las preguntas
            questions = process_questions(response.choices[0].message.content)
            print(f"Preguntas generadas: {questions}")

            # Validar y almacenar las preguntas
            valid_questions = [q for q in questions if validate_question(q)]
            results.extend(valid_questions)
            questions_generated = len(results)

            if questions_generated < num_items:
                reintentos += 1
        except Exception as e:
            print(f"Error generando preguntas: {e}")
            reintentos += 1

    if questions_generated < num_items:
        print(f"Advertencia: No se generaron suficientes preguntas ({questions_generated}/{num_items}).")

    # Guardar preguntas y mostrar
    for question in results:
        print(f"Pregunta guardada: {question}")  # Imprimir las preguntas antes de guardarlas
        user_question = UserQuestion(
            user_id=current_user.id,
            question=question['question'],
            subject=asignatura,
            topic=segmento
        )
        db.session.add(user_question)

    db.session.commit()
    current_user.increment_questions()

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
            # Añadir prints para depurar respuestas
            print(f"Verificando pregunta: {question}")
            print(f"Respuesta del usuario: {user_answer}")
            correctness, explanation, correct_answer = check_answer(question, user_answer)

            print(f"Correcta: {correctness}, Explicación: {explanation}, Respuesta correcta: {correct_answer}")

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
            print(f"Error al verificar respuesta: {e}")
            results.append({
                'question': question,
                'selected_option': user_answer,
                'correct': "error",
                'explanation': f"Error al procesar la respuesta: {str(e)}"
            })

    return jsonify(results)



@app.route('/chat', methods=['POST'])
def chat():
    user_message = request.json['message']
    chat = ChatDeepInfra(model="meta-llama/Meta-Llama-3.1-8B-Instruct", max_tokens=4000)
    system_text = "Eres un asistente de examen que proporciona respuestas generales a preguntas relacionadas con el examen. Responde en español"
    human_text = user_message
    prompt = ChatPromptTemplate.from_messages([("system", system_text), ("human", human_text)])
    
    response = prompt | chat
    response_msg = response.invoke({})
    response_text = response_msg.content
    
    return jsonify({"response": response_text})




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
# main.py

from werkzeug.utils import secure_filename
from models import db, User, UserQuestion, UserProgress
from study_generator import (
    extract_text_from_pdf,
    extract_topics_from_pdf,
    filter_chunks_by_topics,
    generate_study_guide_from_content,
    save_study_session,
    load_study_session,
    extract_specific_topic_content
)
import tempfile
import os
import traceback
import json
from io import BytesIO
import pdfkit  # Importar pdfkit para generar PDFs
import markdown
import logging

# Configurar el logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Ruta para servir la página de la guía de estudio
@app.route('/study_guide_page')
@login_required
def study_guide_page():
    return render_template('study_guide.html')

# Ruta para extraer los temas del PDF
@app.route('/get_pdf_topics', methods=['POST'])
@login_required
def get_pdf_topics():
    if 'file' not in request.files:
        logger.info("No se encontró un archivo PDF en la solicitud.")
        return jsonify({"error": "No se encontró un archivo PDF"}), 400

    file = request.files['file']
    filename = secure_filename(file.filename)
    if filename == '':
        logger.info("No se seleccionó ningún archivo.")
        return jsonify({"error": "No se seleccionó un archivo"}), 400

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = os.path.join(temp_dir, filename)
            file.save(pdf_path)

            topics = extract_topics_from_pdf(pdf_path)
            
            # Imprimir los temas extraídos
            logger.info(f"Temas extraídos del PDF {filename}: {topics}")

            return jsonify({"topics": topics})

    except Exception as e:
        traceback.print_exc()
        logger.error(f"Error al extraer temas del PDF: {e}")
        return jsonify({"error": str(e)}), 500

# Ruta para iniciar el estudio con los temas seleccionados
# main.py

@app.route('/start_study', methods=['POST'])
@login_required
def start_study():
    """
    Ruta para iniciar una sesión de estudio basada en un PDF y temas seleccionados.
    """
    if 'file' not in request.files:
        logger.info("No se encontró un archivo PDF en la solicitud.")
        return jsonify({"error": "No se encontró un archivo PDF"}), 400

    file = request.files['file']
    filename = secure_filename(file.filename)
    if filename == '':
        logger.info("No se seleccionó ningún archivo.")
        return jsonify({"error": "No se seleccionó un archivo"}), 400

    selected_topics_json = request.form.get('selected_topics', '[]')
    try:
        selected_topics = json.loads(selected_topics_json)
    except json.JSONDecodeError:
        logger.error("Formato JSON inválido para 'selected_topics'.")
        return jsonify({"error": "Formato JSON inválido para 'selected_topics'."}), 400

    # Limpiar los temas seleccionados: eliminar espacios y comas al final
    selected_topics = [topic.strip().rstrip(',') for topic in selected_topics if topic.strip()]

    # Filtrar los temas para asegurarse de que solo los válidos están seleccionados
    pattern = re.compile(r'^(Unidad|Tema|Capítulo|Sección|Lección)\s+\d+(\.\d+)*[:.]\s+.*', re.IGNORECASE)
    selected_topics = [topic for topic in selected_topics if pattern.match(topic)]

    if not selected_topics:
        logger.info("No se seleccionaron temas válidos.")
        return jsonify({"error": "No se seleccionaron temas válidos."}), 400

    # Imprimir los temas seleccionados después de la limpieza
    logger.info(f"Temas seleccionados después de la limpieza: {selected_topics}")

    student_profile_json = request.form.get('student_profile', '{}')
    try:
        student_profile = json.loads(student_profile_json)
    except json.JSONDecodeError:
        logger.error("Formato JSON inválido para 'student_profile'.")
        return jsonify({"error": "Formato JSON inválido para 'student_profile'."}), 400

    # Validar intereses
    if not student_profile.get('interests'):
        student_profile['interests'] = ['Matemáticas']  # Valor predeterminado
    else:
        # Eliminar cadenas vacías y espacios
        student_profile['interests'] = [interest for interest in student_profile['interests'] if interest.strip()]
        if not student_profile['interests']:
            student_profile['interests'] = ['Matemáticas']

    # Imprimir el perfil del estudiante
    logger.info(f"Perfil del estudiante: {student_profile}")

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = os.path.join(temp_dir, filename)
            file.save(pdf_path)

            # Extraer los chunks del PDF
            pdf_chunks = extract_text_from_pdf(pdf_path)
            logger.info(f"Chunks extraídos del PDF: {len(pdf_chunks)}")
            logger.debug(f"Contenido de pdf_chunks: {[chunk.page_content[:100] for chunk in pdf_chunks]}")  # Mostrar los primeros 100 caracteres de cada chunk

            # Filtrar los chunks que corresponden a los temas seleccionados
            selected_chunks = filter_chunks_by_topics(pdf_chunks, selected_topics)
            logger.info(f"Chunks seleccionados para los temas: {len(selected_chunks)}")
            logger.debug(f"Contenido de selected_chunks: {[chunk.page_content[:100] for chunk in selected_chunks]}")  # Mostrar los primeros 100 caracteres

            if not selected_chunks:
                logger.info("No se encontraron secciones correspondientes a los temas seleccionados.")
                return jsonify({"error": "No se encontraron secciones correspondientes a los temas seleccionados."}), 400

            # Inicializar el progreso y el contenido generado
            progress = [False] * len(selected_chunks)
            guide_content = [None] * len(selected_chunks)

            # Guardar la sesión de estudio
            save_study_session(current_user.id, selected_chunks, progress, guide_content)
            logger.info("Sesión de estudio guardada correctamente.")

            # Generar la guía de estudio para cada chunk seleccionado
            guides = []
            for i, chunk in enumerate(selected_chunks):
                if i >= len(selected_topics):
                    logger.warning(f"Más chunks seleccionados que temas. Chunk index: {i}")
                    break
                topic_title = selected_topics[i]
                topic_content = extract_specific_topic_content(chunk, topic_title)
                if topic_content:
                    generated_guide = generate_study_guide_from_content(topic_content, student_profile)
                    if generated_guide['guide'] != 'Error al generar la guía de estudio después de varios intentos.':
                        guides.append(generated_guide)
                    else:
                        logger.error(f"Error al generar la guía para el tema: {topic_title}")
                else:
                    logger.info(f"No se pudo extraer el contenido para el tema: {topic_title}")

            if not guides:
                logger.info("No se generaron guías de estudio para los temas seleccionados.")
                return jsonify({"error": "No se generaron guías de estudio para los temas seleccionados."}), 500

            # Combinar las guías generadas
            combined_guide = {
                'guide': '\n\n'.join([guide['guide'] for guide in guides if guide['guide']]),
                'progress': [guide['progress'] for guide in guides],
                'guide_content': [guide['guide_content'] for guide in guides],
                'current_chunk_index': 0,
                'total_chunks': len(guides)
            }

            # Guardar el progreso actualizado
            updated_progress = [True] * len(selected_chunks)
            updated_guide_content = [guide['guide'] for guide in guides]
            save_study_session(current_user.id, selected_chunks, updated_progress, updated_guide_content)
            logger.info("Progreso y contenido de la guía actualizados correctamente.")

            return jsonify(combined_guide)

    except Exception as e:
        traceback.print_exc()
        logger.error(f"Error al iniciar el estudio: {e}")
        return jsonify({"error": str(e)}), 500

# Ruta para obtener la siguiente sección de la guía
@app.route('/next_section', methods=['GET'])
@login_required
def next_section():
    try:
        selected_chunks, progress, guide_content = load_study_session(current_user.id)

        if selected_chunks is None:
            logger.info("No hay una sesión de estudio activa.")
            return jsonify({"error": "No hay una sesión de estudio activa."}), 400

        # Determinar el siguiente chunk no completado
        next_chunk_index = next((i for i, completed in enumerate(progress) if not completed), None)

        if next_chunk_index is None:
            logger.info("Ya has completado todas las secciones.")
            return jsonify({"message": "Ya has completado todas las secciones."})

        chunk = selected_chunks[next_chunk_index]
        # Obtener el título del tema actual
        lines = chunk.page_content.split('\n')
        topic_title = next((line for line in lines if line.strip().lower().startswith('tema ')), "Tema")

        topic_content = extract_specific_topic_content(chunk, topic_title)
        if not topic_content:
            logger.info(f"No se pudo extraer el contenido para el tema: {topic_title}")
            return jsonify({"error": f"No se pudo extraer el contenido para el tema: {topic_title}"}), 400

        # Cargar el perfil del estudiante si es necesario
        student_profile = {}  # Puedes cargar el perfil del estudiante si es necesario

        # Generar la guía de estudio para el siguiente chunk
        generated_guide = generate_study_guide_from_content(topic_content, student_profile)
        logger.info(f"Siguiente sección generada: {generated_guide}")

        # Actualizar el progreso y el contenido generado
        progress[next_chunk_index] = True
        guide_content[next_chunk_index] = generated_guide['guide']

        # Guardar el progreso actualizado
        save_study_session(current_user.id, selected_chunks, progress, guide_content)

        return jsonify(generated_guide)

    except Exception as e:
        traceback.print_exc()
        logger.error(f"Error al obtener la siguiente sección: {e}")
        return jsonify({"error": str(e)}), 500

# Ruta para marcar la sección actual como completada
@app.route('/mark_section_complete', methods=['POST'])
@login_required
def mark_section_complete():
    try:
        selected_chunks, progress, guide_content = load_study_session(current_user.id)

        if selected_chunks is None:
            logger.info("No hay una sesión de estudio activa.")
            return jsonify({"error": "No hay una sesión de estudio activa."}), 400

        # Encontrar el índice del chunk actual
        current_chunk_index = next((i for i, completed in enumerate(progress) if not completed), None)
        logger.info(f"Índice del chunk actual: {current_chunk_index}")

        if current_chunk_index is not None:
            # Marcar el chunk actual como completado
            progress[current_chunk_index] = True
            logger.info(f"Marcar chunk {current_chunk_index} como completado.")

            # Guardar el progreso actualizado
            save_study_session(current_user.id, selected_chunks, progress, guide_content)

            return jsonify({"status": "success"})
        else:
            logger.info("Ya has completado todas las secciones.")
            return jsonify({"message": "Ya has completado todas las secciones."})

    except Exception as e:
        traceback.print_exc()
        logger.error(f"Error al marcar la sección como completada: {e}")
        return jsonify({"error": str(e)}), 500

# Ruta para descargar la guía completa en PDF
from flask import send_file
from io import BytesIO
from xhtml2pdf import pisa
import markdown2

@app.route('/download_guide_pdf/<int:guide_id>', methods=['GET'])
@login_required
def download_guide_pdf(guide_id):
    try:
        # Cargar el progreso y el contenido generado del usuario
        user_progress = db.session.query(UserProgress).filter_by(user_id=current_user.id, id=guide_id).first()

        if not user_progress or not user_progress.guide_content:
            return jsonify({"error": "No hay contenido de guía para descargar."}), 400

        # Convertir el contenido de la guía de Markdown a HTML
        full_guide_markdown = user_progress.guide_content
        full_guide_html = markdown2.markdown(full_guide_markdown)

        # Estilos básicos para hacer el PDF visualmente atractivo
        styles = """
        <style>
            body {
                font-family: Arial, sans-serif;
                margin: 20px;
            }
            h1, h2, h3 {
                color: #333;
            }
            h1 {
                font-size: 24px;
                font-weight: bold;
            }
            h2 {
                font-size: 20px;
                margin-top: 20px;
            }
            h3 {
                font-size: 16px;
                margin-top: 15px;
            }
            p {
                font-size: 14px;
                line-height: 1.6;
                color: #555;
            }
            ul, ol {
                margin-left: 20px;
            }
            li {
                margin-bottom: 5px;
            }
            .highlight {
                background-color: #f0f0f0;
                padding: 10px;
                border-left: 4px solid #007BFF;
                margin-bottom: 15px;
            }
        </style>
        """

        # Combinar el estilo con el contenido HTML generado
        full_html = f"<html><head>{styles}</head><body>{full_guide_html}</body></html>"

        # Generar el PDF desde el HTML
        pdf_file = BytesIO()
        pisa.CreatePDF(BytesIO(full_html.encode('utf-8')), dest=pdf_file)
        pdf_file.seek(0)

        # Enviar el archivo PDF
        return send_file(pdf_file, as_attachment=True, download_name='guia_de_estudio.pdf', mimetype='application/pdf')

    except Exception as e:
        print(f"Error al descargar la guía en PDF: {e}")
        return jsonify({"error": str(e)}), 500

# main.py
from fpdf import FPDF
import io


@app.route('/view_guides', methods=['GET'])
@login_required
def view_guides():
    try:
        # Obtener las guías guardadas del usuario
        user_guides = db.session.query(UserProgress).filter_by(user_id=current_user.id).all()

        if not user_guides:
            flash('No se encontraron guías guardadas.', 'info')
            return render_template('view_guides.html', guides=[])

        return render_template('view_guides.html', guides=user_guides)

    except Exception as e:
        print(f"Error al consultar las guías de estudio: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/view_guide/<int:guide_id>', methods=['GET'])
@login_required
@pro_required
def view_guide(guide_id):
    try:
        # Consultar la guía por su ID y asegurarse de que pertenece al usuario actual
        user_progress = db.session.query(UserProgress).filter_by(id=guide_id, user_id=current_user.id).first()

        if not user_progress:
            flash('No se encontró la guía solicitada o no tienes acceso a ella.', 'danger')
            return redirect(url_for('view_guides'))

        # Renderizar la plantilla view_guide.html con los datos de la guía
        return render_template('view_guide.html', guide=user_progress)

    except Exception as e:
        print(f"Error al consultar la guía de estudio: {e}")
        return jsonify({"error": str(e)}), 500


# en este caso preguntas para cualquier edad
from models import db, UserQuestion, User
from question_generation import (
    validate_question,
    generate_questions1,
    check_answer1
)
from werkzeug.security import generate_password_hash, check_password_hash


# Configurar el modelo de chat
from langchain_community.chat_models import ChatDeepInfra
chat_model = ChatDeepInfra(model="meta-llama/Meta-Llama-3.1-8B-Instruct", max_tokens=4000)


@app.route('/generate_any_age_exam', methods=['GET', 'POST'])
@login_required
@pro_required
def generate_any_age_exam():
    if request.method == 'POST':
        # Obtener los valores ingresados en el formulario
        nivel = request.form.get('nivel')
        asignatura = request.form.get('asignatura')
        topic = request.form.get('topic')
        num_items = int(request.form.get('num_items', 0))

        if not nivel or not asignatura or not topic or num_items <= 0:
            return "Datos de formulario inválidos.", 400

        # Generar el prompt basado en el nivel, la asignatura y el tema
        prompt_text = f"""Eres un asistente que genera preguntas de opción múltiple para el segmento '{topic}' de la asignatura '{asignatura}' en el nivel '{nivel}'.
        Aclaración: 1 de primaria corresponde a la edad de seis años, 2 primaria 7, y así sucesivamente, hasta 1 de la eso, que es 12 años.
        Debes proporcionar {num_items} preguntas sobre el tema dado, que sean adecuadas para el nivel educativo seleccionado, añadiendo tus conocimientos generales, con 4 opciones de respuesta cada una. 
        En caso de términos matemáticos, ponlos en formato LATEX y usa delimitadores LaTeX para matemáticas en línea `\\(...\\)`. 
        Usa el siguiente formato:
        Pregunta 1: ¿Cuál es la capital de Francia?
        A) Madrid.
        B) París.
        C) Berlín.
        D) Roma.
        """
        print("prompt")
        print(prompt_text)
        # Generar preguntas utilizando el módulo separado
        questions = generate_questions1(chat_model, prompt_text, num_items)

        # Validar y preparar las preguntas generadas
        results = []
        for question in questions:
            # Añadir manualmente la asignatura, segmento y nivel a cada pregunta
            question['subject'] = asignatura
            question['topic'] = topic
            question['level'] = nivel

            if validate_question(question):
                results.append(question)
            else:
                logging.warning(f"Pregunta inválida: {question}")

        questions_generated = len(results)
        reintentos = 0
        max_reintentos = 5

        # Intentar generar más preguntas si no se alcanzó el número requerido
        while questions_generated < num_items and reintentos < max_reintentos:
            additional_questions = generate_questions1(chat_model, prompt_text, num_items - questions_generated)
            for question in additional_questions:
                question['subject'] = asignatura
                question['topic'] = topic
                question['level'] = nivel

                if validate_question(question):
                    results.append(question)
                    questions_generated += 1

                    if questions_generated == num_items:
                        break

            reintentos += 1

        if questions_generated < num_items:
            logging.warning(f"No se pudieron generar todas las preguntas válidas. Se generaron {questions_generated} de {num_items}.")

        # Guardar las preguntas generadas en la base de datos
        for question in results:
            user_question = UserQuestion(
                user_id=current_user.id,
                question=question['question'],
                user_answer=None,  # No hay respuesta aún
                correct_answer=None,  # La respuesta correcta se verificará después
                is_correct=False,  # Esto se actualizará al comprobar la respuesta del usuario
                subject=question['subject'],  # Asignatura
                topic=question['topic'],  # Segmento
                level=question['level']  # Nivel Educativo
            )
            db.session.add(user_question)

        # Confirmar los cambios en la base de datos
        db.session.commit()

        # Incrementa el contador de preguntas para el usuario actual
        current_user.increment_questions()

        # Renderizar las preguntas en el HTML (quiz.html)
        return render_template('quiz.html', questions=results)

    # Si es GET, renderiza el formulario de generación de exámenes
    return render_template('exam_form.html')


from esquema import leer_archivo, obtener_estructura_jerarquica, limpiar_json, parsear_json_a_listas, generar_esquema_interactivo
import json5
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'pdf', 'txt'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
@app.route('/esquema', methods=['GET', 'POST'])
@login_required
@pro_required
def esquema():
    if request.method == 'POST':
        # Verificar si el archivo está en la solicitud
        if 'file' not in request.files:
            flash('No se seleccionó ningún archivo')
            return redirect(request.url)
        file = request.files['file']
        if file.filename == '':
            flash('No se seleccionó ningún archivo')
            return redirect(request.url)
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            ruta_archivo = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(ruta_archivo)
            # Procesar el archivo y generar el esquema
            texto = leer_archivo(ruta_archivo)
            conceptos_json = obtener_estructura_jerarquica(texto)

            # Limpiar el JSON
            conceptos_json = limpiar_json(conceptos_json)
            if not conceptos_json:
                flash("No se pudo generar el esquema debido a un JSON inválido.")
                return redirect(request.url)
            else:
                try:
                    data = json5.loads(conceptos_json)
                    labels, parents, descriptions = parsear_json_a_listas(data)
                    esquema_html = generar_esquema_interactivo(labels, parents, descriptions)
                    print(esquema_html)
                    return render_template('esquema.html', esquema_html=esquema_html)
                except Exception as e:
                    print(f"Error al procesar el JSON: {e}")
                    flash("No se pudo generar el esquema debido a un error en el procesamiento del JSON.")
                    return redirect(request.url)
        else:
            flash('Archivo no permitido. Solo se permiten archivos PDF o TXT.')
            return redirect(request.url)
    else:
        return render_template('subir_esquema.html')


# Ruta API para recibir texto o imágenes
# backend/main.py
import os
import uuid
import base64
import tempfile
from image_processing import  analyze_document, query_gpt4  # Importar las funciones desde processing.py


# Ruta para la página de chat
@app.route('/chat1')
def chat1():
    return render_template('chat.html')

# Ruta API para recibir texto o imágenes
# Ruta API para recibir texto o imágenes
@app.route('/api/chat', methods=['POST'])
@pro_required
def chat_api():
    data = request.json
    text_input = data.get('text')
    image_base64 = data.get('image_base64')

    try:
        if image_base64:
            # Generar un nombre único para la imagen
            filename = f"{uuid.uuid4()}.jpg"

            # Decodificar la imagen de base64
            header, encoded = image_base64.split(",", 1)
            image_bytes = base64.b64decode(encoded)

            # Guardar la imagen en un archivo temporal
            with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as temp_image:
                temp_image.write(image_bytes)
                temp_image_path = temp_image.name

            # Analizar la imagen y obtener el texto extraído
            extracted_text = analyze_document(temp_image_path)

            # Eliminar el archivo temporal
            os.remove(temp_image_path)

            # Consultar GPT-4 con el texto extraído
            gpt_response = query_gpt4(f"Describe esta imagen basándote en el siguiente texto: {extracted_text}")
        elif text_input:
            # Si se envía texto, usar GPT-4 directamente
            gpt_response = query_gpt4(text_input)
        else:
            return jsonify({"error": "Debes enviar texto o una imagen"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"gpt_response": gpt_response})

from ruta_aprendizaje import generar_ruta_aprendizaje, generar_detalle_subtema

@app.route('/ruta', methods=['GET', 'POST'])
@pro_required
def ruta():
    if request.method == 'POST':
        tema = request.form['tema']
        conocimientos_previos = request.form['conocimientos']
        ruta_personalizada = generar_ruta_aprendizaje(tema, conocimientos_previos)
        return render_template('ruta.html', ruta=ruta_personalizada)
    else:
        return render_template('ruta.html')

@app.route('/detalle_subtema', methods=['POST'])
def detalle_subtema():
    subtema = request.json.get('subtema')
    if subtema:
        detalle = generar_detalle_subtema(subtema)
        return jsonify({'detalle': detalle})
    else:
        return jsonify({'error': 'No se proporcionó el subtema'}), 400


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8001)