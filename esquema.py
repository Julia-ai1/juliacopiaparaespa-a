import PyPDF2
import plotly.graph_objects as go
import re
import json5
from openai import OpenAI
import openai
import os

# Configura tu clave de OpenAI
openai.api_key = os.getenv("OPENAI_API_KEY")

def leer_archivo(ruta_archivo):
    contenido = ""
    if ruta_archivo.endswith('.pdf'):
        with open(ruta_archivo, 'rb') as f:
            lector = PyPDF2.PdfReader(f)
            for pagina in lector.pages:
                texto_pagina = pagina.extract_text()
                if texto_pagina:
                    contenido += texto_pagina
    else:
        with open(ruta_archivo, 'r', encoding='utf-8') as f:
            contenido = f.read()
    return contenido

def obtener_estructura_jerarquica(texto):
    # Limitar el texto para evitar exceder los límites de tokens
    max_length = 15000
    if len(texto) > max_length:
        texto = texto[:max_length]
        print("El texto ha sido truncado para ajustarse al límite de tokens.")

    # Crear el prompt
    prompt = f"""
Eres un asistente inteligente que ayuda a crear esquemas de estudio. Tienes acceso al siguiente texto:

\"\"\"
{texto}
\"\"\"

Tu tarea es extraer los conceptos clave y organizarlos en una estructura jerárquica adecuada para un esquema de estudio. Incluye resúmenes detallados en diferentes niveles. Proporciona la estructura en formato JSON válido, donde cada elemento tiene los siguientes campos:

- "nombre": nombre del concepto
- "descripcion": resumen breve del concepto
- "subconceptos": lista de subconceptos (puede estar vacía)

Ejemplo de formato:

[
  {{
    "nombre": "Segunda Guerra Mundial",
    "descripcion": "Conflicto global que tuvo lugar entre 1939 y 1945.",
    "subconceptos": [
      {{
        "nombre": "Etapas",
        "descripcion": "Principales fases del conflicto.",
        "subconceptos": [
          {{
            "nombre": "Invasión de Polonia",
            "descripcion": "Alemania invade Polonia en 1939.",
            "subconceptos": []
          }}
        ]
      }},
      {{
        "nombre": "Países Involucrados",
        "descripcion": "Naciones que participaron en el conflicto.",
        "subconceptos": [
          {{
            "nombre": "Alemania",
            "descripcion": "País liderado por Adolf Hitler.",
            "subconceptos": [
              {{
                "nombre": "Operación Barbarroja",
                "descripcion": "Invasión alemana a la Unión Soviética en 1941.",
                "subconceptos": []
              }}
            ]
          }}
        ]
      }}
    ]
  }}
]

Proporciona únicamente el JSON sin explicación adicional. Asegúrate de que el JSON sea válido y bien formado.
"""
    client = OpenAI(api_key=openai.api_key)
    try:
        # Llamada a la API de OpenAI
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Eres un asistente experto en generar esquemas de estudio."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=1500,
            temperature=0.7
        )
        respuesta = response['choices'][0]['message']['content'].strip()

    except Exception as e:
        print("Error al generar la estructura jerárquica:", e)
        return None

    # Imprimir la respuesta generada para depuración
    print("Estructura jerárquica generada:\n", respuesta)

    return respuesta

def limpiar_json(respuesta):
    # Eliminar texto antes y después del JSON
    pattern = r'\[.*\]'
    match = re.search(pattern, respuesta, re.DOTALL)
    if match:
        json_str = match.group(0)
        return json_str
    else:
        print("No se encontró un JSON válido en la respuesta.")
        return None

def parsear_json_a_listas(data, parent_name='', labels=None, parents=None, descriptions=None):
    if labels is None:
        labels = []
    if parents is None:
        parents = []
    if descriptions is None:
        descriptions = []

    for elemento in data:
        nombre = elemento.get('nombre', '')
        descripcion = elemento.get('descripcion', '')
        labels.append(nombre)
        parents.append(parent_name if parent_name else "")
        descriptions.append(descripcion)
        subconceptos = elemento.get('subconceptos', [])
        if subconceptos:
            parsear_json_a_listas(subconceptos, parent_name=nombre, labels=labels, parents=parents, descriptions=descriptions)
    return labels, parents, descriptions

def generar_esquema_interactivo(labels, parents, descriptions):
    fig = go.Figure(go.Treemap(
        labels=labels,
        parents=parents,
        hovertext=descriptions,
        hoverinfo="label+text",
        textinfo="label",
        marker=dict(
            colorscale='Blues',
            line=dict(width=2)
        )
    ))

    fig.update_layout(
        title='Esquema de Estudio Interactivo',
        title_x=0.5,
        margin=dict(t=50, l=25, r=25, b=25)
    )

    # Generar el HTML del gráfico
    fig_html = fig.to_html(full_html=False)
    return fig_html
