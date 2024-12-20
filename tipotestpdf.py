import os
import logging
import re
import random
from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename
from elasticsearch import Elasticsearch
from langchain_community.document_loaders import PyPDFLoader
from langchain.prompts import ChatPromptTemplate
from langchain_community.chat_models import ChatDeepInfra

# Initialize Elasticsearch
es = Elasticsearch(
        cloud_id="julia:d2VzdHVzMi5henVyZS5lbGFzdGljLWNsb3VkLmNvbSQyYzM3NDIxODU0MWI0NzFlODYzMjNjNzZiNWFiZjA3MSQ5Nzk5YTRkZTEyYzg0NTU5OTlkOGVjMWMzMzM1MGFmZg==",
        basic_auth=("elastic", "VlXvDov4WtoFcBfEgFfOL6Zd")
    )

# Configuration for file uploads
UPLOAD_FOLDER = 'uploads/'
ALLOWED_EXTENSIONS = {'pdf'}

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Check if the uploaded file is a PDF
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Verificar si el índice existe y crearlo si no
from elasticsearch import Elasticsearch

# Función para recuperar documentos aleatorios de Elasticsearch
def retrieve_random_documents(es, index_name, num_docs=5):
    print(f"Buscando {num_docs} documentos aleatorios en el índice {index_name}...")
    search_query = {
        "query": {"function_score": {"query": {"match_all": {}}, "random_score": {}}},
        "size": num_docs
    }
    try:
        response = es.search(index=index_name, body=search_query)
        documents = [
            {
                "content": hit["_source"].get("content", ""),
                "metadata": hit["_source"].get("metadata", {})
            }
            for hit in response['hits']['hits']
        ]
        print(f"Se recuperaron {len(documents)} documentos del índice {index_name}.")
        return documents
    except Exception as e:
        print(f"Error al recuperar documentos del índice {index_name}: {e}")
        return []

# Generate multiple-choice questions from the content
def generate_questions(chat, pdf_content, num_questions=5):
    system_text = f"Eres un asistente que genera preguntas de opción múltiple sobre el texto {pdf_content}. Debes generar {num_questions} preguntas con 4 opciones de respuesta cada una."
    
    human_text = f"Genera preguntas a partir del contenido del PDF:\n{pdf_content}"

    # Create the prompt
    prompt = ChatPromptTemplate.from_messages([("system", system_text), ("human", human_text)])
    response = prompt | chat
    response_msg = response.invoke({})
    response_text = response_msg.content.strip()

    # Process the questions generated by the model
    questions = process_questions(response_text)
    return questions

# Process questions generated by the model
def process_questions(response_text):
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

# Check if the user's answer is correct
def check_answer(question, user_answer, chat):
    try:
        question_text = question["question"].replace("{", "{{").replace("}", "}}")
        question_text = question_text.replace("$", "\\(").replace("$", "\\)")

        options = "\n".join([f"{chr(65 + i)}. {choice.replace('{', '{{').replace('}', '}}')}" for i, choice in enumerate(question["choices"])])

        # First message for getting the correct answer
        system_message = "Eres un asistente que evalúa respuestas de opción múltiple. Dada la pregunta y las opciones, determina la respuesta correcta."
        human_message = f"Pregunta: {question_text}\n\nOpciones:\n{options}"

        # Create prompt
        prompt = ChatPromptTemplate.from_messages([("system", system_message), ("human", human_message)])
        response = prompt | chat
        response_text = response.invoke({}).content.strip()

        # Match correct answer from response
        match = re.match(r"^(A|B|C|D|E)", response_text, re.IGNORECASE)
        if match:
            correct_answer_letter = match.group(1).upper()
            correct_answer_index = ord(correct_answer_letter) - 65
            correct_answer_text = question["choices"][correct_answer_index]
        else:
            correct_answer_letter = "A"
            correct_answer_text = question["choices"][0]

        # Second message to generate an explanation
        system_explanation = "Eres un asistente que proporciona una explicación detallada sobre por qué una respuesta es correcta o incorrecta."
        human_explanation = f"Pregunta: {question_text}\nRespuesta correcta: {correct_answer_letter}"

        prompt_explanation = ChatPromptTemplate.from_messages([("system", system_explanation), ("human", human_explanation)])
        response_explanation = prompt_explanation | chat
        explanation = response_explanation.invoke({}).content.strip()

        if user_answer.upper() == correct_answer_letter:
            return "correct", f"Sí, la respuesta es correcta. La respuesta correcta es '{correct_answer_letter}'.\nExplicación: {explanation}", correct_answer_text
        else:
            return "incorrect", f"No, la respuesta es incorrecta. La respuesta correcta es '{correct_answer_letter}', no '{user_answer}'.\nExplicación: {explanation}", correct_answer_text

    except Exception as e:
        logging.error(f"Error in check_answer: {e}")
        explanation = "Hubo un error al evaluar la respuesta."
        return "error", f"Error: {e}\n{explanation}", None

# Flask route to upload PDF
# Flask route para subir PDF y procesarlo
@app.route('/upload_test_pdf', methods=['POST'])
def upload_test_pdf():
    if 'pdfFile' not in request.files:
        return jsonify({"error": "No se ha seleccionado ningún archivo."}), 400

    pdf_file = request.files['pdfFile']
    if allowed_file(pdf_file.filename):
        filename = secure_filename(pdf_file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        pdf_file.save(filepath)

        # Procesar el PDF y crear el índice en Elasticsearch
        print(f"Subiendo y procesando el archivo PDF {filename}...")
        extract_and_index_pdf(filepath, filename, "test_pdf_index")
        return jsonify({"message": "PDF subido e indexado correctamente"}), 200
    else:
        return jsonify({"error": "Formato de archivo no válido. Por favor sube un archivo PDF."}), 400

# Flask route para generar preguntas desde el PDF
@app.route('/generate_test_questions', methods=['POST'])
def generate_test_questions():
    num_questions = int(request.form.get('num_questions', 5))
    pdf_id = request.form.get('pdf_id')
    
    # Recuperar documentos aleatorios del índice
    print(f"Generando preguntas basadas en el PDF {pdf_id}...")
    documents = retrieve_random_documents(es, "test_pdf_index")
    pdf_content = " ".join([doc['content'] for doc in documents])

    # Generar preguntas basadas en el contenido
    chat = ChatDeepInfra(model="meta-llama/Meta-Llama-3.1-8B-Instruct")
    questions = generate_questions(chat, pdf_content, num_questions)

    return jsonify({'questions': questions})

@app.route('/check_test_answer', methods=['POST'])
def check_test_answer():
    question = request.form.get('question')
    user_answer = request.form.get('user_answer')

    # Assume the question has been preloaded or stored in session
    chat = ChatDeepInfra(model="meta-llama/Meta-Llama-3.1-8B-Instruct")
    correctness, explanation, correct_answer = check_answer(question, user_answer, chat)

    return jsonify({
        'correctness': correctness,
        'explanation': explanation,
        'correct_answer': correct_answer
    })
