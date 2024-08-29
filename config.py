import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'mysecretkey')
    SQLALCHEMY_DATABASE_URI = 'mssql+pyodbc://julia:c1d2Papa1236.,@juliaai.database.windows.net/juliadatabase?driver=ODBC+Driver+17+for+SQL+Server'

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    STRIPE_PUBLIC_KEY = os.environ.get('STRIPE_PUBLIC_KEY', 'tu_clave_publica_de_stripe')
    STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY', 'tu_clave_secreta_de_stripe')
