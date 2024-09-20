import os
import logging
import re
import openai
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
import random
from dotenv import load_dotenv
load_dotenv()

# Configurar el cliente de OpenAI
openai.api_key = os.getenv("OPENAI_API_KEY")
client = openai

# Configurar el cliente de Azure Cognitive Search
SEARCH_SERVICE_ENDPOINT = os.getenv("SEARCH_SERVICE_ENDPOINT")
SEARCH_API_KEY = os.getenv("SEARCH_API_KEY")
INDEX_NAME = "exam_questions_sel"

# Crear cliente de Azure Cognitive Search
search_client = SearchClient(
    endpoint=SEARCH_SERVICE_ENDPOINT,
    index_name=INDEX_NAME,
    credential=AzureKeyCredential(SEARCH_API_KEY)
)

# Función para procesar preguntas
def process_questions(response_text):
    questions = []
    question_blocks = re.split(r"(\*\*Pregunta|\bPregunta\b|\bPregunta \d+\b|Pregunta\s+\d+:)", response_text, flags=re.IGNORECASE)

    for i in range(1, len(question_blocks), 2):
        question_text_block = question_blocks[i] + question_blocks[i + 1]
        question_text_match = re.search(r"(.*?)(?=\n[A-D]\))", question_text_block, re.DOTALL)
        if not question_text_match:
            print(f"Bloque de pregunta no válido: {question_text_block[:200]}")
            continue

        question_text = question_text_match.group(1).strip()
        options = re.findall(r"([A-D])\)\s*(.+)", question_text_block)

        if len(options) < 4:
            print(f"Pregunta con menos de 4 opciones: {question_text[:100]}...")
            continue

        question = {
            'question': question_text,
            'choices': [option[1].strip() for option in options]
        }
        questions.append(question)

    print(f"Preguntas procesadas correctamente: {len(questions)}")
    return questions

# Función para generar preguntas con GPT-4o-mini
def generate_questions(pdf_content, num_questions, segmento_asignatura, asignatura):
    system_text = f"""Eres un asistente que genera preguntas de opción múltiple para el segmento {segmento_asignatura} de la asignatura {asignatura}. 
    Debes proporcionar {num_questions} preguntas sobre el texto dado, y que la pregunta tenga sentido para resolverla, añadiendo tus conocimientos generales, con 4 opciones de respuesta cada una. En caso de términos matemáticos, ponlos en formato LATEX y usa delimitadores LaTeX para matemáticas en línea `\\(...\\)`."""

    human_text = f"Genera preguntas sobre el segmento {segmento_asignatura} de la asignatura {asignatura} a partir del contenido del PDF:\n{pdf_content}"

    response = client.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_text},
            {"role": "user", "content": human_text}
        ],
        max_tokens=2000,
        temperature=0.7
    )

    response_text = response.choices[0].message["content"].strip()
    questions = process_questions(response_text)
    return questions

# Función para recuperar documentos de Azure Cognitive Search
import random

def retrieve_documents(query, search_client, num_docs=20):
    """
    Recupera documentos relevantes usando Azure Cognitive Search basándose en la consulta proporcionada.

    Args:
        query (str): La consulta de búsqueda.
        search_client (SearchClient): Instancia del cliente de búsqueda de Azure.
        num_docs (int, optional): Número máximo de documentos a recuperar. Por defecto es 20.

    Returns:
        list: Lista de documentos recuperados con contenido y metadatos.
    """
    try:
        response = search_client.search(search_text=query, top=num_docs)
        documents = [
            {
                "page_content": result.get("content", ""),
                "metadata": result.get("metadata", {})
            }
            for result in response
        ]
        random.shuffle(documents)
        return documents[:5]  # Retorna 5 documentos aleatorios de los recuperados
    except Exception as e:
        print(f"Error al recuperar documentos: {e}")
        return []


# Función para extraer contexto relevante de los documentos recuperados
def extract_relevant_context(documents, max_length=1000):
    relevant_text = []
    for doc in documents:
        content = doc['page_content']
        sentences = content.split('.')
        for sentence in sentences:
            if len('. '.join(relevant_text)) >= max_length:
                return '. '.join(relevant_text)[:max_length]
            relevant_text.append(sentence.strip())
    return '. '.join(relevant_text)[:max_length]

# Función para verificar si la respuesta del usuario es correcta
def check_answer(question, user_answer):
    """
    Evalúa la respuesta del usuario a una pregunta de opción múltiple, determina la respuesta correcta
    utilizando GPT-4o-mini y proporciona una explicación detallada.

    Args:
        question (dict): Diccionario que contiene la pregunta y las opciones. Ejemplo:
                         {
                             "question": "¿Cuál es la derivada de $f(x) = x^2$?",
                             "choices": [
                                 "A. $2x$",
                                 "B. $x$",
                                 "C. $x^2$",
                                 "D. $2$",
                                 "E. Ninguna de las anteriores"
                             ]
                         }
        user_answer (str): Respuesta proporcionada por el usuario (por ejemplo, "A").

    Returns:
        tuple: Una tupla que contiene el estado ("correct", "incorrect", "error"), la explicación, y el texto de la respuesta correcta.
    """
    try:
        # Preparar el contenido de la pregunta y las opciones
        question_text = question["question"].replace("{", "{{").replace("}", "}}") 
        question_text = question_text.replace("$", "\\(").replace("$", "\\)")

        # Formatear las opciones y escapar las llaves
        options = "\n".join([f"{chr(65 + i)}. {choice.replace('{', '{{').replace('}', '}}')}" 
                             for i, choice in enumerate(question["choices"])])

        system_correct = (
            "You are an assistant that determines the correct answer to a multiple-choice question "
            "based on the provided context. Return only the correct option without any additional explanations."
        )

        human_correct = f"Question: {question_text}\n\nOptions:\n{options}"

        response_correct = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_correct},
                {"role": "user", "content": human_correct}
            ]
        )

        correct_answer = response_correct.choices[0].message.content.strip()

        system_explanation = (
            "You are an assistant that provides a detailed explanation of why an answer is correct or incorrect."
        )

        human_explanation = f"Question: {question_text}\nCorrect Answer: {correct_answer}"

        response_explanation = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_explanation},
                {"role": "user", "content": human_explanation}
            ]
        )

        explanation = response_explanation.choices[0].message.content.strip()

        if user_answer.lower() in correct_answer.lower():
            return "correct", explanation, correct_answer
        else:
            return "incorrect", explanation, correct_answer

    except Exception as e:
        logging.error(f"Error en check_answer: {e}")
        return "error", f"Error al procesar la respuesta: {e}", None