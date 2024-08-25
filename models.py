from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()  # No pasar la aplicación aquí

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    subscription_type = db.Column(db.String(20), default='free')
    questions_asked = db.Column(db.Integer, default=0)
    subscription_start = db.Column(db.DateTime, default=datetime.utcnow)
    stripe_subscription_id = db.Column(db.String(50))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def reset_questions(self):
        self.questions_asked = 0

    def can_ask_question(self):
        if self.subscription_type == 'free' and self.questions_asked >= 50:
            return False
        return True

    def increment_questions(self):
        if self.subscription_type == 'free':
            self.questions_asked += 1
