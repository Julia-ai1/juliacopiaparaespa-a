from flask import Flask, render_template, request, jsonify
from exani import generate_questions_exani, check_answer_exani, generate_new_questions_exani
from baccaulareat import generate_solutions_bac, retrieve_documents_bac, extract_relevant_context_bac
from langchain_community.chat_models import ChatDeepInfra
import os
import logging
from elasticsearch import Elasticsearch
from langchain.prompts import ChatPromptTemplate

app = Flask(__name__)

# Configuración de logging
logging.basicConfig(level=logging.INFO)

# Token de API
os.environ["DEEPINFRA_API_TOKEN"] = "gtnKXw1ytDsD7DmCSsv2vwdXSW7IBJ5H"

# Ruta inicial: Página principal para seleccionar el tipo de examen
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        # Dependiendo de la selección del usuario, se maneja el examen correspondiente
        return redirect('/select_exam')
    return render_template('index.html')

@app.route('/select_exam', methods=['POST'])
def select_exam():
    exam_type = request.form['exam_type']
    # Enviar el tipo de examen a la siguiente plantilla
    return render_template('speciality.html', exam_type=exam_type)

def format_solutions(solutions_text):
    solutions_raw = solutions_text.split("\n\n")
    formatted_solutions = []

    for raw_solution in solutions_raw:
        title_match = re.search(r'^\*\*(.*?)\*\*', raw_solution)
        title = title_match.group(1) if title_match else "Solución"
        text = re.sub(r'^\*\*(.*?)\*\*', '', raw_solution).strip()

        formatted_solutions.append({
            "title": title,
            "text": text,
            "note": None
        })

    return formatted_solutions

@app.route('/generate_exam', methods=['POST'])
def generate_exam():
    exam_type = request.form['exam_type']
    num_items = int(request.form['num_items'])
    chat = ChatDeepInfra(model="meta-llama/Meta-Llama-3-8B-Instruct", max_tokens=4000)

    if exam_type == "exani_ii":
        segmento = request.form['segmento']
        asignatura = request.form['asignatura']
        # Lógica para generar preguntas de EXANI-II
        questions = generate_questions_exani(chat, num_items, segmento, asignatura)
        return render_template('quiz.html', questions=questions)

    elif exam_type == "baccalaureat":
        speciality = request.form['speciality']
        # Lógica para generar soluciones de Baccalauréat
        es = Elasticsearch(
    cloud_id="d6ad8b393b364990a49e2dd896c25d44:dXMtY2VudHJhbDEuZ2NwLmNsb3VkLmVzLmlvJDEwNGY0NzdmMzJjNTQ3MmU4NDY5NmVlYTMwZDI0YzMzJDk2NTU5M2I5NGUxZDRhMjU5MDVlMTc5MmY0YzczZGI4",
    basic_auth=("elastic", "eUqFwSxXebwNHSEH1Bjq1zbM"))
        relevant_docs = retrieve_documents_bac(es, "general_texts", 20, speciality)
        context = extract_relevant_context_bac(relevant_docs)
        solutions = generate_solutions_bac(chat, context, num_items)
        solutions_as_items = [{'question': solution, 'choices': None} for solution in solutions.split('\n\n')]
        return render_template('solutions.html', solutions = solutions)



# Ruta para manejar las solicitudes del chat
@app.route('/chat', methods=['POST'])
def chat():
    user_message = request.json['message']
    chat = ChatDeepInfra(model="meta-llama/Meta-Llama-3-8B-Instruct", max_tokens=4000)
    system_text = "Eres un asistente de examen que proporciona respuestas generales a preguntas relacionadas con el examen."
    human_text = user_message
    prompt = ChatPromptTemplate.from_messages([("system", system_text), ("human", human_text)])
    
    response = prompt | chat
    response_msg = response.invoke({})
    response_text = response_msg.content
    
    return jsonify({"response": response_text})


@app.route('/check', methods=['POST'])
def check():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No se recibieron datos"}), 400
    
    questions = data.get('questions')
    user_answers = data.get('answers')

    if not questions or not user_answers:
        return jsonify({"error": "Faltan preguntas o respuestas"}), 400

    chat = ChatDeepInfra(model="meta-llama/Meta-Llama-3-8B-Instruct", max_tokens=4000)
    results = []

    for i, question in enumerate(questions):
        user_answer = user_answers.get(f'question_{i + 1}')
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


from flask import Flask, render_template, jsonify, request
import stripe

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/checkout')
def checkout():
    return render_template('checkout.html')

# Set your secret key. Remember to switch to your live secret key in production!
stripe.api_key = 'sk_test_51Pr14b2K3oWETT3EMYe9NiKElssrbGmCHpxdUefcuaXLRkKyya5neMrK4jDzd2qh7GUhYZRQT8wqDaiGB2qtg2Md00fbj6TZqF'

@app.route('/payment')
def payment():
    return render_template('payment.html')

@app.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': 'Test Product',
                    },
                    'unit_amount': 2000,  # Amount in cents
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=url_for('success', _external=True),
            cancel_url=url_for('cancel', _external=True),
        )
        return jsonify(id=checkout_session.id)
    except Exception as e:
        return jsonify(error=str(e)), 400

@app.route('/success')
def success():
    return "Payment successful!"

@app.route('/cancel')
def cancel():
    return "Payment canceled!"


# Webhook route to handle Stripe events
@app.route('/webhook', methods=['POST'])
def webhook():
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get('Stripe-Signature')
    event = None

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, 'whsec_kadVr7VrLiKchmegY3v29cVDXR7uRpYO'
        )
    except ValueError as e:
        # Invalid payload
        return '', 400
    except stripe.error.SignatureVerificationError as e:
        # Invalid signature
        return '', 400

    # Handle the event
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        handle_checkout_session(session)

    return '', 200

def handle_checkout_session(session):
    # Logic to fulfill the purchase or activate the subscription
    print('Payment was successful!')

@app.route('/charge', methods=['POST'])
def charge():
    # `stripeToken` is obtained from the form submission
    token = request.form['stripeToken']

    try:
        # Use Stripe's library to make requests...
        charge = stripe.Charge.create(
            amount=2000,  # $20.00
            currency='usd',
            description='Example charge',
            source=token,
        )
        return render_template('success.html', amount=20)
    except stripe.error.StripeError as e:
        # Handle error
        return str(e)


if __name__ == '__main__':
    app.run(port=5000, debug=True)

