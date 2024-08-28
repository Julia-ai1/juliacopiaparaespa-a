from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, current_user, login_user, logout_user, login_required
from exani import generate_questions_exani, check_answer_exani, generate_new_questions_exani
from baccaulareat import generate_solutions_bac, retrieve_documents_bac, extract_relevant_context_bac
from enem import generate_questions, check_answer, retrieve_documents, extract_relevant_context
from langchain_community.chat_models import ChatDeepInfra
import os
from datetime import datetime, timezone
import logging
from models import db, User
import stripe
from elasticsearch import Elasticsearch
from flask_caching import Cache
from langchain.prompts import ChatPromptTemplate

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Cache configuration
app.config['CACHE_TYPE'] = 'simple'
db.init_app(app)
migrate = Migrate(app, db)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Código para crear las tablas en el contexto de la aplicación
with app.app_context():
    db.create_all()

# Token de API
os.environ["DEEPINFRA_API_TOKEN"] = "gtnKXw1ytDsD7DmCSsv2vwdXSW7IBJ5H"

# Set your secret key. Remember to switch to your live secret key in production!
stripe.api_key = 'sk_test_51Pr14b2K3oWETT3EMYe9NiKElssrbGmCHpxdUefcuaXLRkKyya5neMrK4jDzd2qh7GUhYZRQT8wqDaiGB2qtg2Md00fbj6TZqF'

@app.route('/')
def landing():
    return render_template('landing.html')

@app.route('/app')
def app_index():
    if current_user.is_authenticated:
        subscription_type = current_user.subscription_type
        questions_asked = current_user.questions_asked
    else:
        subscription_type = None
        questions_asked = 0

    return render_template('index.html', subscription_type=subscription_type, questions_asked=questions_asked)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        new_user = User(username=username, email=email, subscription_type='free')
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        login_user(new_user)
        print(f"Usuario registrado: {username}, Email: {email}")
        return redirect(url_for('subscribe'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        
        if user is None or not user.check_password(password):
            flash('Usuario o contraseña incorrectos', 'danger')
            print(f"Fallo en inicio de sesión: Usuario {username} no encontrado o contraseña incorrecta.")
            return redirect(url_for('login'))

        login_user(user)
        flash('Has iniciado sesión correctamente', 'success')
        print(f"Inicio de sesión exitoso para: {username}")
        return redirect(url_for('app_index'))

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Has cerrado sesión', 'success')
    return redirect(url_for('index'))

@app.route('/subscribe')
@login_required
def subscribe():
    if current_user.subscription_type == 'paid':
        flash('Ya tienes una suscripción activa.', 'info')
        return redirect(url_for('index'))

    payment_link = "https://buy.stripe.com/test_28o8xO2p8aXmeeA8wx"  # Tu enlace de pago real de Stripe
    return redirect(payment_link)

@app.route('/webhook', methods=['POST'])
def stripe_webhook():
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get('Stripe-Signature')
    endpoint_secret = 'whsec_iEQcZb38URJgh3gLtkmkWnRWm2BMA72e'

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except stripe.error.SignatureVerificationError as e:
        return jsonify({'error': str(e)}), 400

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        handle_checkout_session(session)
    elif event['type'] == 'customer.subscription.deleted':
        subscription = event['data']['object']
        handle_subscription_cancellation(subscription)
    
    return '', 200

def handle_checkout_session(session):
    customer_email = session.get('customer_details', {}).get('email')
    user = User.query.filter_by(email=customer_email).first()
    if user:
        user.subscription_type = 'paid'
        user.subscription_start = datetime.now(timezone.utc)
        user.stripe_subscription_id = session.get('subscription')
        db.session.commit()

def handle_subscription_cancellation(subscription):
    user = User.query.filter_by(stripe_subscription_id=subscription.id).first()
    if user:
        user.subscription_type = 'free'
        user.stripe_subscription_id = None
        db.session.commit()

@app.route('/cancel_subscription', methods=['POST'])
@login_required
def cancel_subscription():
    user = current_user
    if user.stripe_subscription_id:
        try:
            stripe.Subscription.delete(user.stripe_subscription_id)
            user.subscription_type = 'free'
            user.stripe_subscription_id = None
            db.session.commit()
            flash('Tu suscripción ha sido cancelada exitosamente. Ahora tienes una cuenta gratuita.', 'success')
        except stripe.error.StripeError as e:
            flash(f'Ocurrió un error al cancelar tu suscripción: {str(e)}', 'danger')
    return redirect(url_for('index'))

@app.route('/select_exam', methods=['POST'])
@login_required
def select_exam():
    if current_user.subscription_type != 'paid':
        flash('Necesitas una suscripción activa para acceder a los exámenes.', 'warning')
        return redirect(url_for('index'))
    exam_type = request.form.get('exam_type')
    if not exam_type:
        return "No se ha seleccionado ningún examen", 400
    
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
    chat = ChatDeepInfra(model="meta-llama/Meta-Llama-3.1-8B-Instruct", max_tokens=4000)

    if exam_type == "exani_ii":
        segmento = request.form['segmento']
        asignatura = request.form['asignatura']
        questions = generate_questions_exani(chat, num_items, segmento, asignatura)

        # Incrementa el contador de preguntas para el usuario actual
        current_user.increment_questions()
        db.session.commit()  # Asegúrate de guardar los cambios en la base de datos

        return render_template('quiz.html', questions=questions)

    elif exam_type == "baccalaureat":
        speciality = request.form['speciality']
        es = Elasticsearch(
            cloud_id="d6ad8b393b364990a49e2dd896c25d44:dXMtY2VudHJhbDEuZ2NwLmNsb3VkLmVzLmlvJDEwNGY0NzdmMzJjNTQ3MmU4NDY5NmVlYTMwZDI0YzMzJDk2NTU5M2I5NGUxZDRhMjU5MDVlMTc5MmY0YzczZGI4",
            basic_auth=("elastic", "eUqFwSxXebwNHSEH1Bjq1zbM"))
        relevant_docs = retrieve_documents_bac(es, "general_texts", 20, speciality)
        context = extract_relevant_context_bac(relevant_docs)
        solutions = generate_solutions_bac(chat, context, num_items)
        solutions_as_items = [{'question': solution, 'choices': None} for solution in solutions.split('\n\n')]

        # Incrementa el contador de preguntas para el usuario actual
        current_user.increment_questions()
        db.session.commit()  # Asegúrate de guardar los cambios en la base de datos

        return render_template('solutions.html', solutions=solutions_as_items)

    elif exam_type == "enem":
        cuaderno_seleccionado = request.form['cuaderno']
        es = Elasticsearch(
            cloud_id="d6ad8b393b364990a49e2dd896c25d44:dXMtY2VudHJhbDEuZ2NwLmNsb3VkLmVzLmlvJDEwNGY0NzdmMzJjNTQ3MmU4NDY5NmVlYTMwZDI0YzMzJDk2NTU5M2I5NGUxZDRhMjU5MDVlMTc5MmY0YzczZGI4",
            basic_auth=("elastic", "eUqFwSxXebwNHSEH1Bjq1zbM"))
        relevant_docs = retrieve_documents(es, "general_texts_enempdfs", 20, cuaderno_seleccionado)
        context = extract_relevant_context(relevant_docs)
        questions = generate_questions(chat, context, num_items)

        # Incrementa el contador de preguntas para el usuario actual
        current_user.increment_questions()
        db.session.commit()  # Asegúrate de guardar los cambios en la base de datos

        return render_template('quiz.html', questions=questions)

@app.route('/chat', methods=['POST'])
def chat():
    user_message = request.json['message']
    chat = ChatDeepInfra(model="meta-llama/Meta-Llama-3.1-8B-Instruct", max_tokens=4000)
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
    print("Datos recibidos del frontend:", data)  # Imprimir los datos recibidos

    if not data:
        print("Error: No se recibieron datos.")
        return jsonify({"error": "No se recibieron datos"}), 400
    
    questions = data.get('questions')
    user_answers = data.get('answers')

    if not questions or not user_answers:
        print("Error: Faltan preguntas o respuestas.")
        return jsonify({"error": "Faltan preguntas o respuestas"}), 400

    chat = ChatDeepInfra(model="meta-llama/Meta-Llama-3.1-8B-Instruct", max_tokens=4000)
    results = []

    for i, question in enumerate(questions):
        question_name = f'question_{i+1}'
        user_answer = user_answers.get(question_name)
        
        print(f"Procesando {question_name}: respuesta seleccionada = {user_answer}")  # Imprimir respuesta seleccionada
        
        if not user_answer:
            print(f"{question_name} sin respuesta seleccionada.")
            results.append({
                'question': question,
                'selected_option': None,
                'correct': "incorrect",
                'explanation': "No se proporcionó ninguna respuesta"
            })
            continue

        if 'enem' in question.get('metadata', {}).get('source', ''):
            correctness, explanation = check_answer(question, user_answer, chat)
        else:
            correctness, explanation = check_answer_exani(question, user_answer, chat)
        
        print(f"Resultado de {question_name}: correcto = {correctness}, explicación = {explanation}")  # Imprimir resultados

        results.append({
            'question': question,
            'selected_option': user_answer,
            'correct': correctness,
            'explanation': explanation
        })

    return jsonify(results)

@app.route('/checkout')
def checkout():
    return render_template('checkout.html')

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


# Webhook route to handle Stripe events
import stripe

@app.route('/webhook', methods=['POST'])
def webhook():
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get('Stripe-Signature')
    endpoint_secret = 'whsec_iEQcZb38URJgh3gLtkmkWnRWm2BMA72e'  # Asegúrate de que esta sea la clave secreta correcta

    print("Payload recibido:", payload)  # Imprimir el payload recibido
    print("Cabecera de firma recibida:", sig_header)  # Imprimir la cabecera de firma recibida

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )
        print("Firma validada exitosamente.")
    except ValueError as e:
        # Payload inválido
        print("Error: Payload inválido:", e)
        return '', 400
    except stripe.error.SignatureVerificationError as e:
        # Firma inválida
        print("Error de verificación de firma:", e)
        print("Cabecera de firma esperada:", endpoint_secret)  # Imprimir la clave de firma esperada para comparación
        return '', 400

    # Manejar el evento (por ejemplo, un pago completado)
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        handle_checkout_session(session)

    return '', 200

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
    app.run(host='0.0.0.0', port=5000, debug=True)


