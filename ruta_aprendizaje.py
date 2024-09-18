# ruta_aprendizaje.py
import json
import re
from langchain_community.chat_models import ChatDeepInfra
def generar_ruta_aprendizaje(tema, conocimientos_previos):
    # Inicializar el modelo de lenguaje
    chat = ChatDeepInfra(model="meta-llama/Meta-Llama-3.1-8B-Instruct", max_tokens=1000)

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
        {{
            "nombre": "Subtema 1"
        }},
        {{
            "nombre": "Subtema 2"
        }}
    ]
}}
Responde únicamente con el JSON. No incluyas explicaciones, texto adicional, bloques de código ni comillas alrededor del JSON.
"""

    # Invocar el modelo
    response = chat.invoke(prompt)

    # Verificar el tipo de la respuesta y extraer el texto
    if hasattr(response, 'content'):
        ruta_text = response.content.strip()
    elif hasattr(response, 'text'):
        ruta_text = response.text.strip()
    else:
        # Si no tiene 'content' ni 'text', es posible que sea una cadena de texto directa
        ruta_text = str(response).strip()

    print("Texto de la ruta:", ruta_text)

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

    return ruta_json

def generate_response(context, question):
    # Aquí se asume que estás usando un modelo de DeepInfra para generar la respuesta
    chat = ChatDeepInfra(model="meta-llama/Meta-Llama-3.1-8B-Instruct", max_tokens=1000)

    # Prompt actualizado con el contexto y la pregunta
    prompt = f"""
    You are an intelligent assistant. You have access to the following context:
    {context}
    
    Based on the context above, please answer the following question:
    {question}
    
    Please make sure your response is relevant to the context.
    """

    # Invoca la API de DeepInfra para obtener la respuesta
    print("Generando respuesta...")
    print(prompt)
    response = chat.invoke(prompt)  # Realizamos la invocación del modelo

    # Verificar el tipo de la respuesta para extraer el texto
    if isinstance(response, dict):
        answer_text = response.get('answer', 'No se pudo generar una respuesta adecuada.')
    elif hasattr(response, 'text'):
        answer_text = response.text
    elif hasattr(response, 'content'):
        answer_text = response.content.decode('utf-8') if isinstance(response.content, bytes) else response.content
    else:
        answer_text = "No se pudo generar una respuesta adecuada debido a un formato de respuesta desconocido."

    # Imprimir la respuesta generada para debugging
    print("Respuesta generada: ", answer_text)

    # Devolver la respuesta en formato texto
    return answer_text.strip()

def generar_detalle_subtema(subtema):
    # Generar el detalle del subtema utilizando la función generate_response
    context = ""  # Puedes agregar contexto adicional si lo tienes
    question = f"Proporciona una explicación detallada y didáctica sobre el siguiente subtema: {subtema}"

    detalle = generate_response(context, question)

    return detalle

