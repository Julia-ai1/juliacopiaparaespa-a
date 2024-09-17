# question_generation.py

import re
import logging
from langchain.prompts import ChatPromptTemplate
from langchain_community.chat_models import ChatDeepInfra

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

def generate_questions1(chat, prompt_text, num_questions):
    """
    Genera preguntas utilizando el modelo de chat basado en el prompt proporcionado.

    Args:
        chat: Instancia del modelo de chat.
        prompt_text: Texto del prompt para generar preguntas.
        num_questions: Número de preguntas a generar.

    Returns:
        List de diccionarios con las preguntas generadas.
    """
    system_text = prompt_text

    prompt = ChatPromptTemplate.from_messages([("system", system_text), ("human", "")])

    try:
        response = prompt | chat
        response_msg = response.invoke({})
        response_text = response_msg.content.strip()

        # Procesar las preguntas generadas por el modelo
        questions = process_questions(response_text)
        return questions

    except Exception as e:
        logging.error(f"Error en generate_questions: {e}")
        return []

def check_answer1(question, user_answer, chat):
    system_correct = (
        "Eres un asistente que determina la respuesta correcta a una pregunta de opción múltiple "
        "basada en el contexto proporcionado. Devuelve solo la opción correcta sin explicaciones adicionales.Hazlo en inglés"
    )

    options_correct = "".join("- " + choice + "\n" for choice in question["choices"])

    human_correct = f'Pregunta: {question["question"]}\nOpciones:\n{options_correct}'

    prompt_correct = ChatPromptTemplate.from_messages(
        [("system", system_correct), ("human", human_correct)]
    )

    response_correct = prompt_correct | chat
    correct_answer = response_correct.invoke({}).content.strip()

    if not correct_answer:
        return "error", "No se pudo obtener una respuesta correcta para la pregunta."

    system_explanation = (
        "Eres un asistente que proporciona una explicación detallada de por qué una respuesta es correcta o incorrecta. Responde en inglés"
    )

    human_explanation = f'Pregunta: {question["question"]}\nRespuesta correcta: {correct_answer}'

    prompt_explanation = ChatPromptTemplate.from_messages(
        [("system", system_explanation), ("human", human_explanation)]
    )

    response_explanation = prompt_explanation | chat
    explanation = response_explanation.invoke({}).content.strip()

    if user_answer.lower() in correct_answer.lower():
        final_explanation = (
            f"Yes, the answer is correct. The correct answer is '{correct_answer}'.\n"
            f"Explanation: {explanation}"
        )
        return "correct", final_explanation
    else:
        final_explanation = (
            f"No, the answer is incorrect. The correct answer is '{correct_answer}', "
            f"no '{user_answer}'.\nExplanation: {explanation}"
        )
        return "incorrect", final_explanation
