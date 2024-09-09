import os
import logging
import re
from elasticsearch import Elasticsearch
from langchain.prompts import ChatPromptTemplate
from langchain_community.chat_models import ChatDeepInfra
import random

# Configurar el índice en Elasticsearch
INDEX_NAME = "exam_questions_sel"

import re

import re

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
            print(f"Bloque de pregunta no válido: {question_text_block[:200]}")
            continue  # Saltar este bloque si no encuentra el formato esperado

        question_text = question_text_match.group(1).strip()

        # Extraer las opciones de respuesta. Permitimos varias formas de listar las opciones.
        options = re.findall(r"([A-D])\)\s*(.+)", question_text_block)

        if len(options) < 4:
            print(f"Pregunta con menos de 4 opciones: {question_text[:100]}...")
            continue  # Nos aseguramos de que la pregunta tenga al menos 4 opciones

        # Crear la estructura de la pregunta con las opciones
        question = {
            'question': question_text,
            'choices': [option[1].strip() for option in options]  # Almacenamos solo el texto de las opciones
        }
        questions.append(question)

    print(f"Preguntas procesadas correctamente: {len(questions)}")
    return questions




# Función para generar preguntas con IA
def generate_questions(chat, pdf_content, num_questions, segmento_asignatura, asignatura):
    system_text = f"""Eres un asistente que genera preguntas de opción múltiple para el segmento {segmento_asignatura} de la asignatura {asignatura}. 
    Debes proporcionar {num_questions} preguntas sobre el texto dado, y que la pregunta tenga sentido para resolverla, añadiendo tus conocimientos generales, con 4 opciones de respuesta cada una.  En caso de términos matemáticos, ponlos en formato LATEX y usa delimitadores LaTeX para matemáticas en línea `\\(...\\)`. 
    Usa el siguiente formato:

    Pregunta 1: ¿Cuál es la capital de Francia?
    A) Madrid.
    B) Paris.
    C) Berlín.
    D) Roma."""

    # Escapamos correctamente los corchetes si forman parte del texto
    escaped_pdf_content = pdf_content.replace("{", "{{").replace("}", "}}")
    escaped_pdf_content = escaped_pdf_content.replace("\\", "\\\\")  # Escapar backslashes para LaTeX
    if len(pdf_content.strip()) < 10:
        logging.warning("El contenido del PDF es insuficiente. Usando conocimiento general para generar preguntas.")
        human_text = f"El contenido del PDF es insuficiente. Genera preguntas sobre el segmento {segmento_asignatura} de la asignatura {asignatura} basándote en tu conocimiento general."
    else:
        human_text = f"Genera preguntas sobre el segmento {segmento_asignatura} de la asignatura {asignatura} a partir del contenido del PDF:\n{escaped_pdf_content}. AÑADE lo necesario para que las preguntas se puedan resolver. DEBES asegurarte de que cada pregunta incluya el contexto relevante como las definiciones de matrices y otros elementos importantes. Si el contenido no es suficiente, usa tu conocimiento general para generar preguntas coherentes."

    # Creación del prompt usando el contenido generado
    prompt = ChatPromptTemplate.from_messages([("system", system_text), ("human", human_text)])
    
    # Aquí invocamos el prompt en el modelo
    response = prompt | chat
    response_msg = response.invoke({})
    response_text = response_msg.content.strip()

    # Procesar las preguntas generadas por el modelo
    questions = process_questions(response_text)
    return questions


# Función para recuperar documentos de Elasticsearch
def retrieve_documents(query, es, index_name, num_docs=20):
    search_query = {
        "query": {
            "match": {
                "content": query  # Usamos la query como el segmento del examen que es una cadena de texto
            }
        },
        "size": num_docs  # Ajusta el tamaño según tus necesidades
    }
    
    try:
        response = es.search(index=index_name, body=search_query)
        documents = [
            {
                "page_content": hit["_source"].get("content", ""),
                "metadata": hit["_source"].get("metadata", {})
            }
            for hit in response["hits"]["hits"]
        ]
        random.shuffle(documents)  # Aleatoriza los documentos
        return documents[:5]  # Selecciona los primeros 5 documentos aleatorios
    except Exception as e:
        logging.error(f"Error al recuperar documentos: {e}")
        return []



# Función para extraer contexto relevante de los documentos recuperados
def extract_relevant_context(documents, max_length=1000):
    intro_end_patterns = [
        r"Ejercicio [\d]+",  
        r"instrucciones:",
        r"resolver los siguientes problemas:",
        r"resolver CUATRO de los ocho ejercicios",
        r"cada ejercicio completo puntuará"
    ]
    intro_end_regex = '|'.join(intro_end_patterns)
    keywords = ["calcular", "determinar", "resolver", "analizar", "discutir", "si"]
    question_patterns = [r"\b\d+\)", r"\b\d+\.", r"\b\d+\-\)"]

    relevant_text = []
    for doc in documents:
        content = doc['page_content']
        intro_end_match = re.search(intro_end_regex, content)
        if intro_end_match:
            content = content[intro_end_match.start():]  

        sentences = content.split('.')
        for sentence in sentences:
            if any(keyword in sentence.lower() for keyword in keywords) or any(re.search(pattern, sentence) for pattern in question_patterns):
                relevant_text.append(sentence.strip())
                if len('. '.join(relevant_text)) >= max_length:
                    return '. '.join(relevant_text)[:max_length]
    return '. '.join(relevant_text)[:max_length]

failed_questions=[]
# Función para verificar si la respuesta del usuario es correcta

import re
import logging
from langchain.prompts import ChatPromptTemplate

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

        # Imprimir mensajes de sistema y usuario
        print(f"System message enviado: {system_message}")
        print(f"Human message enviado: {human_message}")

        # Generar el prompt para el modelo de chat
        prompt = ChatPromptTemplate.from_messages([("system", system_message), ("human", human_message)])
        response = prompt | chat
        response_text = response.invoke({}).content.strip()

        # Imprimir la respuesta del modelo de IA
        print(f"Respuesta del modelo de IA: {response_text}")

        # Intentar extraer la respuesta correcta (A, B, C, D o E)
        match = re.match(r"^(A|B|C|D|E)", response_text, re.IGNORECASE)
        if match:
            correct_answer_letter = match.group(1).upper()  # Letra de la opción correcta (A=0, B=1, C=2, D=3, E=4)
            print(f"Letra de la respuesta correcta: {correct_answer_letter}")
            correct_answer_index = ord(correct_answer_letter) - 65  # Convierte la letra en índice numérico (A=0, B=1, ...)
            correct_answer_text = question["choices"][correct_answer_index]  # El texto de la opción correcta
        else:
            # Si no se puede determinar la respuesta correcta, usar una opción predeterminada
            correct_answer_letter = "A"
            correct_answer_text = question["choices"][0]  # Primera opción como predeterminada
            print(f"No se pudo determinar la respuesta correcta, se usará la opción predeterminada: {correct_answer_text}")

        # Segundo mensaje para obtener la explicación
        system_explanation = """Eres un asistente que proporciona una explicación detallada de por qué una respuesta es correcta o incorrecta. 
        Proporcione una explicación que también incluya términos matemáticos en formato LaTeX si es necesario."""
        human_explanation = f"Pregunta: {question_text}\nRespuesta correcta: {correct_answer_letter}"

        # Imprimir mensajes de sistema y usuario para la explicación
        print(f"System message para la explicación enviado: {system_explanation}")
        print(f"Human message para la explicación enviado: {human_explanation}")

        # Generar el prompt para la explicación
        prompt_explanation = ChatPromptTemplate.from_messages([("system", system_explanation), ("human", human_explanation)])
        response_explanation = prompt_explanation | chat
        explanation = response_explanation.invoke({}).content.strip()

        # Imprimir la explicación proporcionada por el modelo
        print(f"Explicación proporcionada por el modelo: {explanation}")

        # Comparar la respuesta del usuario con la respuesta correcta
        if user_answer.upper() == correct_answer_letter:
            print(f"Respuesta del usuario es correcta: {user_answer}")
            return "correct", f"Sí, la respuesta es correcta. La respuesta correcta es '{correct_answer_letter}'.\nExplicación: {explanation}", correct_answer_text
        else:
            print(f"Respuesta del usuario es incorrecta: {user_answer}")
            return "incorrect", f"No, la respuesta es incorrecta. La respuesta correcta es '{correct_answer_letter}', no '{user_answer}'.\nExplicación: {explanation}", correct_answer_text

    except Exception as e:
        # Capturar errores y proporcionar al menos una explicación
        logging.error(f"Error en check_answer: {e}")
        print(f"Error en check_answer: {e}")
        explanation = "Se ha producido un error al evaluar la respuesta, pero aquí tienes una explicación general basada en el contexto."
        return "error", f"Error al evaluar la respuesta: {e}\nExplicación: {explanation}", None

# Función para preguntar y evaluar las respuestas del usuario
def ask_questions(questions, chat):
    if not questions:
        logging.warning("No hay preguntas para mostrar, verifica la generación de preguntas.")
        return

    # Iteramos por cada pregunta generada
    for question in questions:
        print(question["question"])
        for i, choice in enumerate(question["choices"]):
            print(f"{i+1}. {choice}")

        # Recibir la respuesta del usuario
        user_answer = input("Ingresa tu respuesta (ejemplo: A, B, C, D, E): ").strip().upper()
        logging.info("Respuesta ingresada: " + user_answer)

        # Verificar si la respuesta es válida (A, B, C, D o E)
        if user_answer not in ["A", "B", "C", "D", "E"]:
            print("Respuesta no válida, por favor ingresa una opción válida como A, B, C, D, E.")
            continue

        # Convertir la respuesta del usuario en el índice correspondiente
        user_answer_index = ord(user_answer) - 65
        
        # Evaluar la respuesta usando check_answer
        correctness, explanation = check_answer(question, question["choices"][user_answer_index], chat)
        
        # Mostrar la explicación proporcionada por la IA
        print(explanation)
        
        # Verificar si la respuesta es correcta o incorrecta
        if correctness == "incorrect":
            failed_questions.append(question)
            print("Respuesta incorrecta")
        else:
            print("Respuesta correcta")