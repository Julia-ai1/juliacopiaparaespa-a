# ruta_aprendizaje.py
import json
import re
import openai
import json
import os
from openai import OpenAI

# Configura tu clave de OpenAI
openai.api_key = os.getenv("OPENAI_API_KEY")

def generar_ruta_aprendizaje(tema, conocimientos_previos):
    """
    Genera una ruta de aprendizaje personalizada utilizando GPT-4-o Mini.
    """
    # Crear el prompt
    prompt = f"""
Eres un experto en educación que crea rutas de aprendizaje personalizadas.
Tema: "{tema}"
Conocimientos previos: "{conocimientos_previos}"
Genera una lista de subtemas importantes que el estudiante debe aprender.
Proporciona la ruta **solo** en formato JSON válido y sin texto adicional, siguiendo exactamente esta estructura:
{{
    "tema_principal": "{tema}",
    "subtemas": [
        {{"nombre": "Subtema 1"}},
        {{"nombre": "Subtema 2"}}
    ]
}}
Responde únicamente con el JSON. No incluyas explicaciones, texto adicional, bloques de código ni comillas alrededor del JSON.
"""
    client = OpenAI(api_key=openai.api_key)
    try:
        # Llamada a la API de OpenAI
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Eres un experto en generar contenido educativo."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=1000,
            temperature=0.7
        )
        ruta_text = response['choices'][0]['message']['content'].strip()

        # Extraer el JSON de la respuesta
        json_match = re.search(r'\{[\s\S]*\}', ruta_text)
        if json_match:
            ruta_json_str = json_match.group(0)
            try:
                ruta_json = json.loads(ruta_json_str)
            except json.JSONDecodeError as e:
                print("Error al parsear JSON:", e)
                ruta_json = {"error": "No se pudo generar la ruta de aprendizaje. Por favor, intenta nuevamente."}
        else:
            print("No se encontró JSON en la respuesta.")
            ruta_json = {"error": "No se pudo generar la ruta de aprendizaje. Por favor, intenta nuevamente."}

    except Exception as e:
        print("Error al generar la ruta de aprendizaje:", e)
        ruta_json = {"error": "Hubo un error al generar la ruta de aprendizaje. Por favor, intenta nuevamente."}

    return ruta_json


def generate_response(context, question):
    """
    Genera una respuesta basada en un contexto y una pregunta utilizando GPT-4-o Mini.
    """
    prompt = f"""
You are an intelligent assistant. You have access to the following context:
{context}

Based on the context above, please answer the following question:
{question}

Please make sure your response is relevant to the context.
"""

    try:
        # Llamada a la API de OpenAI
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an intelligent assistant providing accurate and relevant answers."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=1000,
            temperature=0.7
        )
        answer_text = response['choices'][0]['message']['content'].strip()

    except Exception as e:
        print("Error al generar respuesta:", e)
        answer_text = "No se pudo generar una respuesta adecuada debido a un error."

    return answer_text


def generar_detalle_subtema(subtema):
    """
    Genera una explicación detallada y didáctica sobre un subtema utilizando GPT-4-o Mini.
    """
    context = ""  # Puedes agregar contexto adicional si lo tienes
    question = f"Proporciona una explicación detallada y didáctica sobre el siguiente subtema: {subtema}"

    detalle = generate_response(context, question)

    return detalle
