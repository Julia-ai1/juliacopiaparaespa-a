import PyPDF2
import plotly.graph_objects as go
import re
import json5
from openai import OpenAI
import logging
import os
from typing import Optional, Tuple, List, Any, Dict

# Configurar logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class EsquemaGenerator:
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("OpenAI API key is required")
        self.client = OpenAI(api_key=api_key)
        
    def leer_archivo(self, ruta_archivo: str) -> str:
        """Lee el contenido de un archivo PDF o TXT."""
        try:
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
            
            if not contenido.strip():
                raise ValueError("El archivo está vacío")
                
            return contenido
            
        except Exception as e:
            logger.error(f"Error al leer el archivo {ruta_archivo}: {str(e)}")
            raise

    def obtener_estructura_jerarquica(self, texto: str) -> Optional[str]:
        """Genera una estructura jerárquica a partir del texto usando OpenAI."""
        try:
            # Limitar el texto para evitar exceder los límites de tokens
            max_length = 15000
            if len(texto) > max_length:
                texto = texto[:max_length]
                logger.warning(f"Texto truncado a {max_length} caracteres")

            prompt = self._crear_prompt(texto)
            
            response = self.client.chat.completions.create(
                model="gpt-40-mini",  # Corregido de gpt-4o-mini a gpt-4
                messages=[
                    {"role": "system", "content": "Eres un asistente experto en generar esquemas de estudio."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=1500,
                temperature=0.7
            )
            
            # Corregido el acceso a la respuesta según la estructura actual de la API
            respuesta = response.choices[0].message.content.strip()
            
            if not respuesta:
                raise ValueError("OpenAI no devolvió una respuesta válida")
                
            return respuesta

        except Exception as e:
            logger.error(f"Error en la generación de estructura jerárquica: {str(e)}")
            raise

    def _crear_prompt(self, texto: str) -> str:
        """Crea el prompt para la API de OpenAI."""
        return f"""
Eres un asistente inteligente que ayuda a crear esquemas de estudio. Tienes acceso al siguiente texto:

\"\"\"\n{texto}\n\"\"\"

Tu tarea es extraer los conceptos clave y organizarlos en una estructura jerárquica adecuada para un esquema de estudio. 
Incluye resúmenes detallados en diferentes niveles. Proporciona la estructura en formato JSON válido, donde cada elemento tiene los siguientes campos:

- "nombre": nombre del concepto
- "descripcion": resumen breve del concepto
- "subconceptos": lista de subconceptos (puede estar vacía)

Proporciona únicamente el JSON sin explicación adicional. Asegúrate de que el JSON sea válido y bien formado.
"""

    def limpiar_json(self, respuesta: str) -> Optional[str]:
        """Limpia y valida el JSON de la respuesta."""
        try:
            # Eliminar texto antes y después del JSON
            pattern = r'\[.*\]'
            match = re.search(pattern, respuesta, re.DOTALL)
            if not match:
                raise ValueError("No se encontró un JSON válido en la respuesta")
                
            json_str = match.group(0)
            
            # Validar que sea JSON válido
            json5.loads(json_str)  # Si esto falla, levantará una excepción
            
            return json_str
            
        except Exception as e:
            logger.error(f"Error al limpiar JSON: {str(e)}")
            raise

    def parsear_json_a_listas(self, data: List[Dict]) -> Tuple[List[str], List[str], List[str]]:
        """Convierte la estructura JSON en listas para el treemap."""
        labels = []
        parents = []
        descriptions = []
        
        def _parsear_recursivo(elementos, parent_name=''):
            for elemento in elementos:
                nombre = elemento.get('nombre', '')
                if not nombre:
                    logger.warning("Encontrado elemento sin nombre")
                    continue
                    
                descripcion = elemento.get('descripcion', '')
                labels.append(nombre)
                parents.append(parent_name if parent_name else "")
                descriptions.append(descripcion)
                
                subconceptos = elemento.get('subconceptos', [])
                if subconceptos:
                    _parsear_recursivo(subconceptos, nombre)
        
        try:
            _parsear_recursivo(data)
            return labels, parents, descriptions
        except Exception as e:
            logger.error(f"Error al parsear JSON a listas: {str(e)}")
            raise

    def generar_esquema_interactivo(self, labels: List[str], parents: List[str], descriptions: List[str]) -> str:
        """Genera el HTML del esquema interactivo usando Plotly."""
        try:
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

            return fig.to_html(full_html=False)
            
        except Exception as e:
            logger.error(f"Error al generar esquema interactivo: {str(e)}")
            raise