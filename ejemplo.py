import openai

openai.api_key = "sk-Ih-9O47lbt5zz6qkYD31-Ylwd4AS18Qj2PPfQycSgST3BlbkFJqO8CRe-viu01Zuf2Msdc5s3vUxLl1jFapzPSXuLkgA"

response = openai.ChatCompletion.create(
    model="gpt-4",  # También puedes usar "gpt-4o-mini"
    messages=[
        {"role": "system", "content": "Eres un asistente experto en generar preguntas tipo test."},
        {"role": "user", "content": "Genera una pregunta de prueba."}
    ]
)

# Procesar y mostrar la respuesta
print(response['choices'][0]['message']['content'])