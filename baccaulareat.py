from flask import Flask, render_template, request, jsonify
import os
import re
import random
import logging
from elasticsearch import Elasticsearch
from langchain.prompts import ChatPromptTemplate
from langchain_community.chat_models import ChatDeepInfra

app = Flask(__name__)

# Configuración de logging
logging.basicConfig(level=logging.INFO)

# Configurar el índice en Elasticsearch
INDEX_NAME = "general_texts"

# Token de API
os.environ["DEEPINFRA_API_TOKEN"] = "gtnKXw1ytDsD7DmCSsv2vwdXSW7IBJ5H"
def extract_relevant_context_bac(documents, max_length=500):
    intro_end_patterns = [
        r"Exercice [\d]+",  
        r"instructions:",
        r"résoudre les problèmes suivants:",
        r"résoudre QUATRE des huit exercices",
        r"chaque exercice complet comptera"
    ]
    intro_end_regex = '|'.join(intro_end_patterns)
    keywords = ["calculer", "déterminer", "résoudre", "analyser", "discuter", "si"]
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

def count_words(text):
    words = text.split()
    return len(words)

def generate_solutions_bac(chat, pdf_content, num_solutions):
    escaped_pdf_content = pdf_content.replace("{", "{{").replace("}", "}}")
    system_text = f"""Vous êtes un assistant spécialisé dans le baccalauréat d'accès à l'université en France. Je veux que vous génériez des exercices avec des solutions détaillées pour les examens à partir du contexte fourni {escaped_pdf_content}. Assurez-vous que les solutions soient complètes et détaillées, expliquant chaque étape du processus de résolution.

Veuillez générer {num_solutions} solutions d'exercices d'examen, en veillant à inclure suffisamment de contexte dans chaque énoncé de l'exercice."""
    human_text = f"Générez des énoncés d'exercices avec la structure décrite à partir du contenu du PDF:\n{escaped_pdf_content}. Assurez-vous que chaque solution inclue le contexte pertinent comme les définitions des concepts importants et d'autres éléments clés. Si le contenu n'est pas suffisant, utilisez vos connaissances générales pour générer des solutions cohérentes."
    input_text = system_text + human_text
    input_word_count = count_words(input_text)
    print(f"Number of words in the input: {input_word_count}")
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_text),
        ("human", human_text)
    ])
    prompt_input = {
        "pdf_content": escaped_pdf_content,
        "num_solutions": num_solutions,
    }
    response = prompt | chat
    response_msg = response.invoke(prompt_input)
    response_text = response_msg.content

    return response_text
def retrieve_documents_bac(es, index_name, num_docs=20, directory_selected=None):
    search_query_match = {
        "query": {
            "match": {
                "metadata.directory": directory_selected
            }
        },
        "size": num_docs * 2  
    }

    response = es.search(index=index_name, body=search_query_match)

    documents = [
        {
            "page_content": hit["_source"]["content"],
            "metadata": hit["_source"]["metadata"]
        }
        for hit in response['hits']['hits']
    ]

    random.shuffle(documents)

    return documents[:num_docs]

@app.route('/', methods=['GET', 'POST'])
def index():
    directories = [
        "SPÉCIALITÉ MATHÉMATIQUES",
        "SPÉCIALITÉ HISTOIRE-GÉOGRAPHIE, GÉOPOLITIQUE ET SCIENCES POLITIQUES",
        "SPÉCIALITÉ PHYSIQUES-CHIMIE",
        "SPÉCIALITÉ BIOCHIMIE-BIOLOGIE BAC TECHNOLOGIQUE STL",
        "SPÉCIALITÉ NUMÉRIQUE ET SCIENCES INFORMATIQUES BAC GÉNÉRAL",
        "SPÉCIALITÉ HUMANITÉS, LITTÉRATURE ET PHILOSOPHIE"
    ]

    if request.method == 'POST':
        directory_selected = request.form['directory']
        num_solutions = int(request.form['num_solutions'])
        es = Elasticsearch()

        relevant_docs = retrieve_documents_bac(es, INDEX_NAME, 20, directory_selected)
        context = extract_relevant_context(relevant_docs)
        solutions = generate_solutions_bac(chat, context, num_solutions)

        return render_template('solutions.html', solutions=solutions)

    return render_template('index.html', directories=directories)
@app.route('/solutions', methods=['POST'])
def solutions():
    solutions = request.form['solutions']
    return render_template('solutions.html', solutions=solutions)

if __name__ == '__main__':
    chat = ChatDeepInfra(model="meta-llama/Meta-Llama-3-8B-Instruct", max_tokens=4000)
    app.run(debug=True)
