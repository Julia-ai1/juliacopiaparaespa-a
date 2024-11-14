# decorators.py

from functools import wraps
from flask import abort, flash, redirect, url_for
from flask_login import current_user

def pro_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash("Debes iniciar sesión para acceder a esta página.", "warning")
            return redirect(url_for('login'))
        if current_user.subscription_type not in ['paid', 'trial', 'canceled_pending', 'free']:
            flash("Esta función está disponible solo para usuarios Pro.", "danger")
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function
