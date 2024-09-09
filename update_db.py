from main import app, db
from sqlalchemy import text

# Ejecutar dentro del contexto de la aplicación Flask
with app.app_context():
    # Conectar y ejecutar las consultas SQL
    with db.engine.connect() as conn:
        conn.execute(text('ALTER DATABASE nombre_base_datos CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;'))

    print("Columnas 'subject' y 'topic' añadidas con éxito.")

