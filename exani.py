from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_login import current_user, login_required
import os
import re
from langchain.prompts import ChatPromptTemplate
from langchain_community.chat_models import ChatDeepInfra
from models import db

app = Flask(__name__)

# Token de API
os.environ["DEEPINFRA_API_TOKEN"] = "gtnKXw1ytDsD7DmCSsv2vwdXSW7IBJ5H"

# Almacena las preguntas fallidas globalmente para la sesión
failed_questions = []

def process_questions(response_text):
    questions = []
    question_blocks = re.split(r"Pregunta \d+:", response_text)

    for block in question_blocks[1:]:
        block = block.strip()
        lines = block.split('\n')
        question_text = ''
        options = []
        capture_options = False
        for line in lines:
            line = line.strip()
            if re.match(r"^[A-C1-3]\)", line) or re.match(r"^[A-C1-3]\.", line):
                options.append(line)
                capture_options = True
            elif capture_options and re.match(r"^\d+\.", line):
                options.append(line)
            else:
                if capture_options:
                    continue
                question_text += ' ' + line

        question_text = question_text.strip()
        choices = [re.sub(r"^[A-C1-3][)\.\s]*", '', option).strip() for option in options]

        if question_text and choices:
            questions.append({'question': question_text, 'choices': choices})

    return questions

def generate_questions_exani(chat, num_questions, segmento_asignatura, asignatura):
    system_text = (
        "Eres un asistente especializado en la generación de exámenes EXANI_II en inglés. "
        f"Debes proporcionar {num_questions} preguntas de opción múltiple para el segmento {segmento_asignatura} "
        f"de la asignatura {asignatura}, añadiendo tus conocimientos generales, con 3 opciones de respuesta cada una. "
        "Debe asegurarte que una de las opciones sea la CORRECTA. Por otro lado, debe estar todo el contexto en la pregunta. "
        "Usa el siguiente formato:\n\n"
        "Pregunta 1: [Insertar pregunta aqui]\n"
        "A) [Insertar respuesta aquí].\n"
        "B) [Insertar respuesta aquí].\n"
        "C) [Insertar respuesta aquí]."
    )

    human_text = (
        f"Genera preguntas para un examen EXANI_II sobre el segmento {segmento_asignatura} de la asignatura {asignatura}. "
        "Asegúrate de que cada pregunta incluya todo el contexto relevante como las definiciones de conceptos clave y otros elementos importantes."
    )

    prompt = ChatPromptTemplate.from_messages([("system", system_text), ("human", human_text)])
    prompt_input = {
        "num_questions": num_questions,
        "segmento_asignatura": segmento_asignatura,
        "asignatura": asignatura,
    }

    response = prompt | chat
    response_msg = response.invoke(prompt_input)
    response_text = response_msg.content

    questions = process_questions(response_text)
    return questions


import re
import logging
from some_chat_library import ChatPromptTemplate  # Reemplaza con la biblioteca de chat que estés utilizando

def check_answer(question, user_answer, chat):
    """
    Evalúa la respuesta del usuario a una pregunta de opción múltiple, determina la respuesta correcta
    utilizando un modelo de chat y proporciona una explicación detallada.

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
        chat (object): Instancia del modelo de chat que se utilizará para generar las respuestas.

    Returns:
        tuple: Una tupla que contiene el estado ("correct", "incorrect", "error") y el mensaje con la explicación.
    """
    try:
        # Configurar el registro de logs (si aún no lo has hecho en otra parte de tu aplicación)
        logging.basicConfig(level=logging.ERROR, filename='app.log', 
                            format='%(asctime)s - %(levelname)s - %(message)s')

        # Preparar el contenido de la pregunta y las opciones
        question_text = question["question"].replace("{", "{{").replace("}", "}}") 
        # Escapamos las llaves para evitar conflictos en formatos como .format()

        # Reemplazar $...$ por \( ... \) para inline math en LaTeX
        question_text = question_text.replace("$", "\\(").replace("$", "\\)")

        # Formatear las opciones, escapando las llaves
        options = "\n".join([f"{chr(65 + i)}. {choice.replace('{', '{{').replace('}', '}}')}" 
                             for i, choice in enumerate(question["choices"])])

        # Mensaje del sistema para determinar la respuesta correcta en inglés
        system_correct = (
            "You are an assistant that determines the correct answer to a multiple-choice question "
            "based on the provided context. Return only the correct option without any additional explanations. Do it in English."
        )

        human_correct = f"Question: {question_text}\n\nOptions:\n{options}"

        # Imprimir mensajes de sistema y usuario (para depuración)
        print(f"System message enviado: {system_correct}")
        print(f"Human message enviado: {human_correct}")

        # Generar el prompt para determinar la respuesta correcta
        prompt_correct = ChatPromptTemplate.from_messages(
            [("system", system_correct), ("human", human_correct)]
        )
        response_correct = prompt_correct | chat
        correct_answer = response_correct.invoke({}).content.strip()

        # Imprimir la respuesta correcta obtenida (para depuración)
        print(f"Respuesta correcta obtenida: {correct_answer}")

        if not correct_answer:
            print("No se pudo obtener una respuesta correcta para la pregunta.")
            return "error", "No se pudo obtener una respuesta correcta para la pregunta."

        # Intentar extraer la letra de la respuesta correcta (A, B, C, D o E)
        match = re.match(r"^(A|B|C|D|E)", correct_answer, re.IGNORECASE)
        if match:
            correct_answer_letter = match.group(1).upper()
            print(f"Letra de la respuesta correcta: {correct_answer_letter}")
            correct_answer_index = ord(correct_answer_letter) - 65
            correct_answer_text = question["choices"][correct_answer_index]
        else:
            # Si no se puede determinar la letra de la respuesta correcta, usar una opción predeterminada
            correct_answer_letter = "A"
            correct_answer_text = question["choices"][0]
            print(f"No se pudo determinar la letra de la respuesta correcta, se usará la opción predeterminada: {correct_answer_text}")

        # Mensaje del sistema para la explicación en inglés
        system_explanation = (
            "You are an assistant that provides a detailed explanation of why an answer is correct or incorrect. Respond in English."
        )

        human_explanation = f"Question: {question_text}\nCorrect Answer: {correct_answer_letter}"

        # Imprimir mensajes de sistema y usuario para la explicación (para depuración)
        print(f"System message para la explicación enviado: {system_explanation}")
        print(f"Human message para la explicación enviado: {human_explanation}")

        # Generar el prompt para la explicación
        prompt_explanation = ChatPromptTemplate.from_messages(
            [("system", system_explanation), ("human", human_explanation)]
        )
        response_explanation = prompt_explanation | chat
        explanation = response_explanation.invoke({}).content.strip()

        # Imprimir la explicación proporcionada por el modelo (para depuración)
        print(f"Explicación proporcionada por el modelo: {explanation}")

        # Comparar la respuesta del usuario con la respuesta correcta usando la lógica especificada
        if user_answer.lower() in correct_answer.lower():
            final_explanation = (
                f"Yes, the answer is correct. The correct answer is '{correct_answer}'.\n"
                f"Explanation: {explanation}"
            )
            print(f"Respuesta del usuario es correcta: {user_answer}")
            return "correct", final_explanation
        else:
            final_explanation = (
                f"No, the answer is incorrect. The correct answer is '{correct_answer}', "
                f"no '{user_answer}'.\nExplanation: {explanation}"
            )
            print(f"Respuesta del usuario es incorrecta: {user_answer}")
            return "incorrect", final_explanation

    except Exception as e:
        # Capturar errores y proporcionar al menos una explicación
        logging.error(f"Error en check_answer_exani: {e}")
        print(f"Error en check_answer_exani: {e}")
        explanation = "An error occurred while evaluating the answer, but here is a general explanation based on the context."
        return "error", f"Error evaluating the answer: {e}\nExplanation: {explanation}"


    
def generate_new_questions_exani(failed_questions, chat):
    new_questions = []
    for question in failed_questions:
        choices_str = "\n".join([f"- {choice}" for choice in question["choices"]])
        system = (
            "Genera una nueva pregunta de opción múltiple relacionada con la siguiente pregunta y sus opciones:\n"
            f"{question['question']}\n"
            "Opciones:\n"
            f"{choices_str}. Usa el siguiente formato.\n"
            "Pregunta 1: [Insertar aqui pregunta]\n"
            "A) [Insertar aqui respuesta].\n"
            "B) [Insertar aqui respuesta].\n"
            "C) [Insertar aqui respuesta]."
        )

        human = "Generar nueva pregunta"

        prompt = ChatPromptTemplate.from_messages(
            [("system", system), ("human", human)]
        )

        response = prompt | chat
        response_text = response.invoke({}).content
        new_questions += process_questions(response_text)

    return new_questions

@app.route('/', methods=['GET', 'POST'])
@login_required
def index():
    if request.method == 'POST':
        if not current_user.can_ask_question():
            flash('Has alcanzado el límite de preguntas para este mes. Por favor, actualiza tu suscripción.', 'danger')
            return redirect(url_for('index'))

        segmento_asignatura = request.form['segmento_asignatura']
        asignatura = request.form['asignatura']
        num_questions = int(request.form['num_questions'])

        chat = ChatDeepInfra(model="meta-llama/Meta-Llama-3-8B-Instruct", max_tokens=4000)
        questions = generate_questions_exani(chat, num_questions, segmento_asignatura, asignatura)

        # Incrementar el contador de preguntas después de generarlas
        current_user.increment_questions(len(questions))
        db.session.commit()

        return render_template('quiz.html', questions=questions)

    return render_template('index.html')

@app.route('/check', methods=['POST'])
def check():
    data = request.get_json()  # Usamos get_json para obtener los datos JSON
    if not data:
        return jsonify({"error": "No se recibieron datos"}), 400
    
    questions = data.get('questions')
    user_answers = data.get('answers')

    if not questions or not user_answers:
        return jsonify({"error": "Faltan preguntas o respuestas"}), 400

    chat = ChatDeepInfra(model="meta-llama/Meta-Llama-3-8B-Instruct", max_tokens=4000)
    results = []

    for i, question in enumerate(questions):
        user_answer = user_answers.get(f'question_{i}')
        if not user_answer:
            results.append({
                'question': question,
                'selected_option': None,
                'correct': "incorrect",
                'explanation': "No se proporcionó ninguna respuesta"
            })
            continue

        correctness, explanation = check_answer_exani(question, user_answer, chat)
        results.append({
            'question': question,
            'selected_option': user_answer,
            'correct': correctness,
            'explanation': explanation
        })

    return jsonify(results)


if __name__ == '__main__':
    app.run(debug=True)
