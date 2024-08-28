from flask import render_template, request, jsonify
import os
import re
import random
import logging
from elasticsearch import Elasticsearch
from langchain.prompts import ChatPromptTemplate
from langchain_community.chat_models import ChatDeepInfra

# Configuración de logging
logging.basicConfig(level=logging.INFO)

# Configurar el índice en Elasticsearch
INDEX_NAME = "general_texts_enempdfs"

# Token de API
os.environ["DEEPINFRA_API_TOKEN"] = "gtnKXw1ytDsD7DmCSsv2vwdXSW7IBJ5H"

def extract_relevant_context(documents, max_length=500):
    intro_end_patterns = [
        r"Ejercicio [\d]+",  # Captura los títulos de los ejercicios
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
            content = content[intro_end_match.start():]  # Incluir desde el inicio del ejercicio

        sentences = content.split('.')
        for sentence in sentences:
            if any(keyword in sentence.lower() for keyword in keywords) or any(re.search(pattern, sentence) for pattern in question_patterns):
                relevant_text.append(sentence.strip())
                if len('. '.join(relevant_text)) >= max_length:
                    return '. '.join(relevant_text)[:max_length]
    return '. '.join(relevant_text)[:max_length]

import re

def process_questions(response_text):
    questions = []
    
    # Dividir el texto en bloques de preguntas basándose en un patrón de "Questão"
    question_blocks = re.split(r"(?=\*\*Questão \d+\*\*)", response_text.strip())
    
    for block in question_blocks:
        if not block.strip():
            continue
        
        # Extraer el texto de la pregunta
        question_match = re.match(r"\*\*Questão \d+\*\*\s*(.*?)(?=\n[A-E]\)|\Z)", block, re.DOTALL)
        
        if question_match:
            question_text = question_match.group(1).strip()
            
            # Buscar las opciones en el formato específico
            options = re.findall(r"([A-E])\)\s*(.+?)(?=\n[A-E]\)|\Z)", block, re.DOTALL)
            
            if options:
                # Crear una lista con las opciones
                choices = [option[1].strip() for option in options]
                
                # Añadir la pregunta y sus opciones a la lista de preguntas
                questions.append({'question': question_text, 'choices': choices})
    
    return questions



def count_words(text):
    words = text.split()
    return len(words)

def generate_questions(chat, pdf_content, num_questions):
    escaped_pdf_content = pdf_content.replace("{", "{{").replace("}", "}}")
    system_text = f"""Eres un asistente en portugués (brasil) que genera preguntas de opción múltiple. En caso de términos matemáticos, ponlos en formato LATEX. Quiero que me generes preguntas con una estructura y contenido similar a las preguntas proporcionadas en el siguiente contexto {escaped_pdf_content}. Coge la estructura, incluyendo en la pregunta inicial TODO el texto para formular la pregunta y las posibles opciones, como en el siguiente formato, empezando estrictamente así:

Questão 95: No programa do balé Parade, apresentado em 18 de maio de 1917, foi empregada publicamente, pela primeira vez, a palavra sur-realisme. Pablo Picasso desenhou o cenário e a indumentária, cujo efeito foi tão surpreendente que se sobrepôs à coreografia. A música de Erik Satie era uma mistura de jazz, música popular e sons reais tais como tiros de pistola, combinados com as imagens do balé de Charlie Chaplin, caubóis e vilões, mágica chinesa e Ragtime... da cena muitas vezes demonstram as condições cotidianas de um determinado grupo social, como se pode observar na descrição acima do balé Parade, o qual reflete
A) a falta de diversidade cultural na sua proposta estética.
B) a alienação dos artistas em relação às tensões da Segunda Guerra Mundial.
C) uma disputa cênica entre as linguagens das artes visuais, do figurino e da música.
D) as inovações tecnológicas nas partes cênicas, musicais, coreográficas e de figurino.
E) uma narrativa com encadeamentos claramente lógicos e lineares.

Por favor, genera {num_questions} preguntas, asegurándote de incluir suficiente contexto en cada enunciado."""
    
    human_text = f"Genera preguntas con la estructura descrita a partir del contenido del PDF:\n{escaped_pdf_content}. Asegúrate de que cada pregunta incluya el contexto relevante como las definiciones de matrices y otros elementos importantes. Si el contenido no es suficiente, usa tu conocimiento general para generar preguntas coherentes."
    
    input_text = system_text + human_text
    input_word_count = count_words(input_text)
    print(f"Number of words in the input: {input_word_count}")

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_text),
        ("human", human_text)
    ])
    
    prompt_input = {
        "pdf_content": escaped_pdf_content,
        "num_questions": num_questions,
    }
    
    response = prompt | chat
    response_msg = response.invoke(prompt_input)
    response_text = response_msg.content
    print(f"Prompt: {response_text}")

    questions = process_questions(response_text)
    return questions

def check_answer(question, user_answer, chat):
    try:
        # Primer prompt para obtener la respuesta correcta
        system_prompt = """Você é um assistente que avalia perguntas de múltipla escolha. Dada a pergunta e as opções, determine a resposta correta. Sua resposta deve começar com a letra da opção correta (A, B, C, D ou E) seguida por uma explicação breve."""

        question_text = question["question"]
        options = "".join(f"- {chr(65 + i)}. {choice}\n" for i, choice in enumerate(question["choices"]))

        prompt_text = f"""Pergunta: {question_text}\n
        Opções:
        {options}"""

        prompt = ChatPromptTemplate.from_messages([("system", system_prompt), ("user", prompt_text)])
        response = prompt | chat
        response_text = response.invoke({}).content

        # Extract the correct answer from the response
        match = re.match(r"^(A|B|C|D|E)", response_text.strip(), re.IGNORECASE)
        if match:
            correct_answer = match.group(1).upper()
        else:
            raise ValueError("Não foi possível determinar a resposta correta a partir do modelo.")

        # Segundo prompt para obter a explicação da resposta
        system_explanation = "Você é um assistente que fornece uma explicação detalhada de por que uma resposta está correta ou incorreta."

        human_explanation = f'Pergunta: {question_text}\nResposta correta: {correct_answer}'

        prompt_explanation = ChatPromptTemplate.from_messages(
            [("system", system_explanation), ("human", human_explanation)]
        )

        response_explanation = prompt_explanation | chat
        explanation = response_explanation.invoke({}).content.strip()

        # Comparar a resposta do usuário com a resposta correta
        if user_answer.lower() in correct_answer.lower():
            return "correct", f"Sim, a resposta está correta. A resposta correta é '{correct_answer}'.\nExplicação: {explanation}"
        else:
            return "incorrect", f"Não, a resposta está incorreta. A resposta correta é '{correct_answer}', não '{user_answer}'.\nExplicação: {explanation}"

    except Exception as e:
        logging.error(f"Erro em check_answer: {e}")
        return "error", f"Erro ao avaliar a resposta: {e}"


def retrieve_documents(es, index_name, num_docs=20, cuaderno_seleccionado=None):
    search_query = {
        "query": {
            "bool": {
                "must": [
                    {"match_all": {}}
                ],
                "filter": [
                    {"wildcard": {"metadata.source": f"*{cuaderno_seleccionado}*"}}
                ] if cuaderno_seleccionado else []
            }
        },
        "size": num_docs * 2  # Recuperar más documentos para asegurar suficientes después del filtrado
    }

    print(f"search_query: {search_query}")  # Debug
    response = es.search(index=index_name, body=search_query)
    documents = [
        {
            "page_content": hit["_source"]["content"],
            "metadata": hit["_source"]["metadata"]
        }
        for hit in response["hits"]["hits"]
    ]
    print(f"Retrieved {len(documents)} documents")  # Debug
    for doc in documents:
        print(f"Documento: {doc['metadata']}")

    # Filtrar los documentos de las primeras 10 páginas
    filtered_documents = [
        doc for doc in documents if int(doc['metadata'].get('page', 0)) > 10
    ]
    print(f"Filtered documents count: {len(filtered_documents)}")
    for doc in filtered_documents:
        print(f"Documento: {doc['metadata']}")

    # Aleatorizar los documentos
    random.shuffle(filtered_documents)

    # Limitar el número de documentos a devolver
    return filtered_documents[:num_docs]

