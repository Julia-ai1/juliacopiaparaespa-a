from main import app, db
from sqlalchemy import text, inspect
import logging

# Configurar el logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate():
    with app.app_context():
        inspector = inspect(db.engine)
        with db.engine.connect() as conn:
            try:
                # Modificar tipos de columnas existentes en 'user_progress'
                alter_statements = [
                    "ALTER TABLE user_progress MODIFY selected_chunks TEXT NOT NULL;",
                    "ALTER TABLE user_progress MODIFY progress_data TEXT NOT NULL;",
                    "ALTER TABLE user_progress MODIFY guide_content TEXT NOT NULL;",
                ]
                
                for stmt in alter_statements:
                    conn.execute(text(stmt))
                    logger.info(f"Ejecutado correctamente: {stmt}")

            except Exception as e:
                logger.error(f"Error al ejecutar alteraciones de columna: {e}")

            # Verificar si la columna 'timestamp' ya existe en 'user_progress'
            columns = inspector.get_columns('user_progress')
            column_names = [column['name'] for column in columns]
            if 'timestamp' not in column_names:
                try:
                    add_timestamp_stmt = "ALTER TABLE user_progress ADD COLUMN timestamp DATETIME DEFAULT CURRENT_TIMESTAMP;"
                    conn.execute(text(add_timestamp_stmt))
                    logger.info(f"Ejecutado correctamente: {add_timestamp_stmt}")
                except Exception as e:
                    logger.error(f"Error al agregar columna 'timestamp': {e}")
            else:
                logger.info("La columna 'timestamp' ya existe. Se omite su adición.")
            
            # Verificar si las columnas 'topic', 'level', y 'created_at' existen en 'user_question'
            columns = inspector.get_columns('user_question')
            column_names = [column['name'] for column in columns]

            if 'topic' not in column_names:
                try:
                    add_topic_stmt = "ALTER TABLE user_question ADD COLUMN topic VARCHAR(50) NOT NULL;"
                    conn.execute(text(add_topic_stmt))
                    logger.info(f"Ejecutado correctamente: {add_topic_stmt}")
                except Exception as e:
                    logger.error(f"Error al agregar columna 'topic' en 'user_question': {e}")

            if 'level' not in column_names:
                try:
                    add_level_stmt = "ALTER TABLE user_question ADD COLUMN level VARCHAR(50) NOT NULL;"
                    conn.execute(text(add_level_stmt))
                    logger.info(f"Ejecutado correctamente: {add_level_stmt}")
                except Exception as e:
                    logger.error(f"Error al agregar columna 'level' en 'user_question': {e}")

            if 'created_at' not in column_names:
                try:
                    add_created_at_stmt = "ALTER TABLE user_question ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP;"
                    conn.execute(text(add_created_at_stmt))
                    logger.info(f"Ejecutado correctamente: {add_created_at_stmt}")
                except Exception as e:
                    logger.error(f"Error al agregar columna 'created_at' en 'user_question': {e}")

            # Verificar si hay restricciones de clave foránea para 'user_id' en 'user_progress'
            fk_constraints = inspector.get_foreign_keys('user_progress')
            foreign_key_names = [fk['name'] for fk in fk_constraints if 'user_id' in fk['constrained_columns']]

            if foreign_key_names:
                for fk_name in foreign_key_names:
                    try:
                        # Eliminar restricciones de clave foránea existentes
                        drop_fk_stmt = f"ALTER TABLE user_progress DROP FOREIGN KEY {fk_name};"
                        conn.execute(text(drop_fk_stmt))
                        logger.info(f"Ejecutado correctamente: {drop_fk_stmt}")
                    except Exception as e:
                        logger.error(f"Error al eliminar restricción de clave foránea: {e}")
            
            # Eliminar índices únicos en 'user_id', si existen
            indexes = inspector.get_indexes('user_progress')
            unique_indexes = [idx for idx in indexes if idx['unique'] and 'user_id' in idx['column_names']]
            if unique_indexes:
                for index in unique_indexes:
                    try:
                        drop_index_stmt = f"DROP INDEX {index['name']};"
                        conn.execute(text(drop_index_stmt))
                        logger.info(f"Ejecutado correctamente: {drop_index_stmt}")
                    except Exception as e:
                        logger.error(f"Error al eliminar índice único: {e}")

            # Agregar la nueva restricción de clave foránea para 'user_id'
            try:
                add_fk_stmt = """
                ALTER TABLE user_progress
                ADD CONSTRAINT fk_user_id
                FOREIGN KEY (user_id) REFERENCES user(id)
                ON DELETE CASCADE
                ON UPDATE CASCADE;
                """
                conn.execute(text(add_fk_stmt))
                logger.info(f"Ejecutado correctamente: {add_fk_stmt.strip()}")
            except Exception as e:
                logger.error(f"Error al agregar nueva restricción de clave foránea: {e}")

if __name__ == "__main__":
    migrate()

