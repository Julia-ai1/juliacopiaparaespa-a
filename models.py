from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from datetime import datetime, timezone

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), index=True, unique=True)
    email = db.Column(db.String(120), index=True, unique=True)
    password_hash = db.Column(db.String(255))
    subscription_type = db.Column(db.String(20), default='free')
    subscription_start = db.Column(db.DateTime)
    stripe_customer_id = db.Column(db.String(255))
    stripe_subscription_id = db.Column(db.String(255))
    questions_asked = db.Column(db.Integer, default=0)
    google_id = db.Column(db.String(255), unique=True)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def increment_questions(self):
        self.questions_asked += 1
        if self.subscription_type == 'free' and self.questions_asked > 50:
            return False
        return True

class UserQuestion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    question = db.Column(db.Text, nullable=False)
    user_answer = db.Column(db.Text, nullable=True)  # Permitir NULL
    correct_answer = db.Column(db.Text, nullable=True)
    is_correct = db.Column(db.Boolean, default=False)
    date_answered = db.Column(db.DateTime, default=datetime.utcnow)
    subject = db.Column(db.String(50), nullable=False)
    topic = db.Column(db.String(50), nullable=False)


    user = db.relationship('User', backref='questions')

