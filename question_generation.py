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

def generate_questions(chat, prompt_text, num_questions):
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

def check_answer(question, user_answer, chat):
    try:
        # Preparar el contenido de la pregunta y las opciones
        question_text = question["question"].replace("{", "{{").replace("}", "}}") 
         # Escapamos las llaves
        # Reemplazar $...$ por \( ... \) para inline math
        question_text = question_text.replace("$", "\\(").replace("$", "\\)")
    
        options = "\n".join([f"{chr(65 + i)}. {choice.replace('{', '{{').replace('}', '}}')}" for i, choice in enumerate(question["choices"])])  # Escapamos las llaves en las opciones
    
        # Primer mensaje para obtener la respuesta correcta
        system_message = """Eres un asistente que evalúa respuestas de opción múltiple. Dada la pregunta y las opciones, determina la respuesta correcta. 
        Tu respuesta debe comenzar con la letra de la opción correcta (A, B, C, D o E) seguida de una breve explicación. Si se trata de una matriz, usa notación LaTeX para representarla."""
    
        human_message = f"Pregunta: {question_text}\n\nOpciones:\n{options}"
    
        # Generar el prompt para el modelo de chat
        prompt = ChatPromptTemplate.from_messages([("system", system_message), ("human", human_message)])
        response = prompt | chat
        response_text = response.invoke({}).content.strip()
    
        # Intentar extraer la respuesta correcta (A, B, C, D o E)
        match = re.match(r"^(A|B|C|D|E)", response_text, re.IGNORECASE)
        if match:
            correct_answer_letter = match.group(1).upper()  # Letra de la opción correcta
            correct_answer_index = ord(correct_answer_letter) - 65  # Convierte la letra en índice numérico (A=0, B=1, ...)
            correct_answer_text = question["choices"][correct_answer_index]  # El texto de la opción correcta
        else:
            # Si no se puede determinar la respuesta correcta, usar una opción predeterminada
            correct_answer_letter = "A"
            correct_answer_text = question["choices"][0]  # Primera opción como predeterminada
    
        # Segundo mensaje para obtener la explicación
        system_explanation = """Eres un asistente que proporciona una explicación detallada de por qué una respuesta es correcta o incorrecta. 
        Proporcione una explicación que también incluya términos matemáticos en formato LaTeX si es necesario."""
        human_explanation = f"Pregunta: {question_text}\nRespuesta correcta: {correct_answer_letter}"
    
        # Generar el prompt para la explicación
        prompt_explanation = ChatPromptTemplate.from_messages([("system", system_explanation), ("human", human_explanation)])
        response_explanation = prompt_explanation | chat
        explanation = response_explanation.invoke({}).content.strip()
    
        # Comparar la respuesta del usuario con la respuesta correcta
        if user_answer.upper() == correct_answer_letter:
            return "correct", f"Sí, la respuesta es correcta. La respuesta correcta es '{correct_answer_letter}'.\nExplicación: {explanation}", correct_answer_text
        else:
            return "incorrect", f"No, la respuesta es incorrecta. La respuesta correcta es '{correct_answer_letter}', no '{user_answer}'.\nExplicación: {explanation}", correct_answer_text

    except Exception as e:
        # Capturar errores y proporcionar al menos una explicación
        logging.error(f"Error en check_answer: {e}")
        explanation = "Se ha producido un error al evaluar la respuesta, pero aquí tienes una explicación general basada en el contexto."
        return "error", f"Error al evaluar la respuesta: {e}\nExplicación: {explanation}", None
