import json
import re
import os
from openai import OpenAI

# Configura tu clave de OpenAI
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def generar_ruta_aprendizaje(tema, conocimientos_previos):
    """
    Genera una ruta de aprendizaje personalizada utilizando GPT-3.5-turbo o GPT-4.
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
    try:
        # Llamada a la API de OpenAI
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # o "gpt-3.5-turbo" si prefieres
            messages=[
                {"role": "system", "content": "Eres un experto en generar contenido educativo."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=1000,
            temperature=0.7
        )
        ruta_text = response.choices[0].message.content.strip()

        # Extraer el JSON de la respuesta
        json_match = re.search(r'\{[\s\S]*\}', ruta_text)
        if json_match:
            ruta_json_str = json_match.group(0)
            try:
                ruta_json = json.loads(ruta_json_str)
                return ruta_json
            except json.JSONDecodeError as e:
                print("Error al parsear JSON:", e)
                return {"error": "No se pudo generar la ruta de aprendizaje. Por favor, intenta nuevamente."}
        else:
            print("No se encontró JSON en la respuesta.")
            return {"error": "No se pudo generar la ruta de aprendizaje. Por favor, intenta nuevamente."}

    except Exception as e:
        print("Error al generar la ruta de aprendizaje:", e)
        return {"error": f"Hubo un error al generar la ruta de aprendizaje: {str(e)}"}

def generate_response(context, question):
    """
    Genera una respuesta basada en un contexto y una pregunta.
    """
    prompt = f"""
You are an intelligent assistant. You have access to the following context:
{context}

Based on the context above, please answer the following question:
{question}

Please make sure your response is relevant to the context.
"""
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # o "gpt-3.5-turbo" si prefieres
            messages=[
                {"role": "system", "content": "You are an intelligent assistant providing accurate and relevant answers."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=1000,
            temperature=0.7
        )
        return response.choices[0].message.content.strip()

    except Exception as e:
        print("Error al generar respuesta:", e)
        return f"Error al generar respuesta: {str(e)}"

def generar_detalle_subtema(subtema):
    """
    Genera una explicación detallada y didáctica sobre un subtema.
    """
    context = f"El tema a explicar es: {subtema}"
    question = "Proporciona una explicación detallada y didáctica sobre este tema, incluyendo conceptos clave, ejemplos y aplicaciones prácticas."
    
    detalle = generate_response(context, question)
    print("Detalle generado:", detalle)  # Para debugging
    return detalle
