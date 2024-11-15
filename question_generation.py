# question_generation.py
from openai import OpenAI
import re
import logging
import openai
import os
from langchain.prompts import ChatPromptTemplate
from langchain_community.chat_models import ChatDeepInfra
openai.api_key = os.getenv("OPENAI_API_KEY")

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

def process_questions(response_text):
    questions = []

    # Dividir el texto en bloques que representen preguntas. Soportamos varios formatos de pregunta.
    question_blocks = re.split(r"(\*\*Pregunta|\bPregunta\b|\bPregunta \d+\b|Pregunta\s+\d+:)", response_text, flags=re.IGNORECASE)
    
    # Recorremos cada bloque después de la división
    for i in range(1, len(question_blocks), 2):
        question_text_block = question_blocks[i] + question_blocks[i + 1]  # Combina la etiqueta de pregunta con el texto que le sigue

        # Extraer el texto de la pregunta. Toma todo lo que esté antes de las opciones (A), (B), etc.
        question_text_match = re.search(r"(.*?)(?=\n[A-D]\))", question_text_block, re.DOTALL)
        if not question_text_match:
            logging.warning(f"Bloque de pregunta no válido: {question_text_block[:200]}")
            continue  # Saltar este bloque si no encuentra el formato esperado

        question_text = question_text_match.group(1).strip()

        # Extraer las opciones de respuesta. Permitimos varias formas de listar las opciones.
        options = re.findall(r"([A-D])\)\s*(.+)", question_text_block)

        if len(options) < 4:
            logging.warning(f"Pregunta con menos de 4 opciones: {question_text[:100]}...")
            continue  # Nos aseguramos de que la pregunta tenga al menos 4 opciones

        # Crear la estructura de la pregunta con las opciones
        question = {
            'question': question_text,
            'choices': [option[1].strip() for option in options]  # Almacenamos solo el texto de las opciones
        }
        questions.append(question)

    logging.info(f"Preguntas procesadas correctamente: {len(questions)}")
    return questions

def generate_questions1(prompt_text, num_questions):
    """
    Genera preguntas utilizando el modelo GPT-4-o Mini basado en el prompt proporcionado.
    """
    client = OpenAI(api_key=openai.api_key)
    try:
        response = client.chat.completions.create(
            model="gpt-4-o-mini",  # Cambia según el modelo que uses
            messages=[
                {"role": "user", "content": prompt_text}
            ],
            max_tokens=1000,
            temperature=0.7,
        )
        # Procesar el texto de la respuesta
        response_text = response['choices'][0]['message']['content']
        questions = process_questions(response_text)
        return questions
    except Exception as e:
        logging.error(f"Error en generate_questions1: {e}")
        return []

def check_answer1(question, user_answer):
    """
    Verifica si la respuesta del usuario es correcta utilizando OpenAI GPT.
    """
    try:
        # Crear el prompt para verificar la respuesta correcta
        correct_prompt = (
            f"Pregunta: {question['question']}\n"
            f"Opciones:\n" +
            "\n".join(f"- {choice}" for choice in question['choices']) +
            "\nDevuelve solo la opción correcta."
        )

        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": correct_prompt}],
            max_tokens=100,
        )
        correct_answer = response['choices'][0]['message']['content'].strip()

        if user_answer.lower() in correct_answer.lower():
            return "correct", f"Correcto. La respuesta es '{correct_answer}'."
        else:
            return "incorrect", f"Incorrecto. La respuesta correcta es '{correct_answer}'."
    except Exception as e:
        logging.error(f"Error en check_answer1: {e}")
        return "error", "No se pudo verificar la respuesta."
