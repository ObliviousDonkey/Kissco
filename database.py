try:
    import pysqlite3 as sqlite3
except ImportError:
    import sqlite3
import sqlite_vec
import numpy as np
from sentence_transformers import SentenceTransformer
from typing import List, Tuple, Optional
import time

# Constants
DB_PATH = "doppelganger.db"
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"

# Initialize the embedding model
# Note: In a real bot, we'd probably initialize this once in the main loop or as a singleton
_model = None

def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _model

def get_connection():
    db = sqlite3.connect(DB_PATH)
    try:
        db.enable_load_extension(True)
        sqlite_vec.load(db)
        db.enable_load_extension(False)
    except AttributeError:
        # Some environments (like MacOS default sqlite3) might not have enable_load_extension
        # If pysqlite3 is installed, it should work.
        pass
    return db

def init_db():
    db = get_connection()
    cursor = db.cursor()

    # Standard tables
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            opted_in BOOLEAN NOT NULL DEFAULT FALSE,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)

    # Virtual table for vector search
    # vec0 virtual tables store embeddings and allow for efficient KNN search.
    # We use 384 dimensions for all-MiniLM-L6-v2.
    cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS vec_messages USING vec0(
            message_id INTEGER PRIMARY KEY,
            embedding float[384]
        )
    """)

    db.commit()
    db.close()

def opt_in_user(user_id: int):
    db = get_connection()
    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO users (id, opted_in) VALUES (?, TRUE)
        ON CONFLICT(id) DO UPDATE SET opted_in = TRUE
    """, (user_id,))
    db.commit()
    db.close()

def is_user_opted_in(user_id: int) -> bool:
    db = get_connection()
    cursor = db.cursor()
    cursor.execute("SELECT opted_in FROM users WHERE id = ?", (user_id,))
    result = cursor.fetchone()
    db.close()
    return result[0] if result else False

def add_message(user_id: int, content: str):
    # Strict check: Zero data is stored unless a user has opted_in = True.
    if not is_user_opted_in(user_id):
        return

    # Generate embedding
    embedding = get_model().encode(content)

    db = get_connection()
    cursor = db.cursor()
    try:
        # Insert into messages table
        cursor.execute("INSERT INTO messages (user_id, content) VALUES (?, ?)", (user_id, content))
        message_id = cursor.lastrowid

        # Insert into vec_messages virtual table
        cursor.execute(
            "INSERT INTO vec_messages(message_id, embedding) VALUES (?, ?)",
            (message_id, sqlite_vec.serialize_float32(embedding))
        )
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Error adding message: {e}")
    finally:
        db.close()

def get_relevant_messages(user_id: int, query: str, limit: int = 15) -> List[str]:
    if not is_user_opted_in(user_id):
        return []

    # Generate embedding for query
    query_embedding = get_model().encode(query)

    db = get_connection()
    cursor = db.cursor()

    # Perform KNN search
    # We join with the messages table to get the content
    # Note: sqlite-vec syntax for KNN search
    try:
        cursor.execute("""
            SELECT m.content
            FROM vec_messages v
            JOIN messages m ON v.message_id = m.id
            WHERE m.user_id = ?
              AND v.embedding MATCH ?
              AND k = ?
            ORDER BY distance
        """, (user_id, sqlite_vec.serialize_float32(query_embedding), limit))

        results = [row[0] for row in cursor.fetchall()]
    except Exception as e:
        print(f"Error querying relevant messages: {e}")
        results = []
    finally:
        db.close()
    return results

def forget_user(user_id: int):
    db = get_connection()
    cursor = db.cursor()
    try:
        # Delete from vec_messages
        cursor.execute("""
            DELETE FROM vec_messages
            WHERE message_id IN (SELECT id FROM messages WHERE user_id = ?)
        """, (user_id,))

        # Delete from messages
        cursor.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))

        # Delete from users
        cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))

        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Error forgetting user: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized.")

    # Simple test
    test_user = 12345
    opt_in_user(test_user)
    print(f"User {test_user} opted in: {is_user_opted_in(test_user)}")

    add_message(test_user, "I love pizza!")
    add_message(test_user, "Python is my favorite language.")
    add_message(test_user, "Discord bots are fun to build.")

    relevant = get_relevant_messages(test_user, "tell me about coding", limit=2)
    print(f"Relevant messages: {relevant}")

    forget_user(test_user)
    print(f"User {test_user} opted in after forget: {is_user_opted_in(test_user)}")
    print(f"Relevant messages after forget: {get_relevant_messages(test_user, 'pizza')}")
