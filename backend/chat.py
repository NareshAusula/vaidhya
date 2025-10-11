import os
import sqlite3
from datetime import datetime

# Use PostgreSQL for production (Render) or SQLite for local development
DATABASE_URL = os.environ.get('DATABASE_URL')

# For local development, you can force SQLite by setting this to False
USE_POSTGRES = os.environ.get('USE_POSTGRES', 'true').lower() == 'true'

if DATABASE_URL and USE_POSTGRES:
    try:
        import psycopg2
        print("✅ Using PostgreSQL database")
    except ImportError:
        print("⚠️ PostgreSQL driver not available. Using SQLite for local development.")
        DATABASE_URL = None
else:
    print("🔧 Using SQLite for local development")
    DATABASE_URL = None

def get_db_connection():
    if DATABASE_URL:
        # Production: Use PostgreSQL
        return psycopg2.connect(DATABASE_URL)
    else:
        # Local development: Use SQLite
        import sqlite3
        return sqlite3.connect("medical_bot.db")

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    
    if DATABASE_URL:
        # PostgreSQL syntax
        c.execute("""
            CREATE TABLE IF NOT EXISTS chat_logs (
                id SERIAL PRIMARY KEY,
                session_id TEXT,
                sender TEXT,
                message TEXT,
                timestamp TIMESTAMP
            )
        """)
    else:
        # SQLite syntax
        c.execute("""
            CREATE TABLE IF NOT EXISTS chat_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                sender TEXT,
                message TEXT,
                timestamp TEXT
            )
        """)
    
    conn.commit()
    conn.close()

def log_message(session_id, sender, message):
    conn = get_db_connection()
    c = conn.cursor()
    
    if DATABASE_URL:
        # PostgreSQL uses %s placeholders
        c.execute(
            "INSERT INTO chat_logs (session_id, sender, message, timestamp) VALUES (%s, %s, %s, %s)",
            (session_id, sender, message, datetime.utcnow())
        )
    else:
        # SQLite uses ? placeholders
        c.execute(
            "INSERT INTO chat_logs (session_id, sender, message, timestamp) VALUES (?, ?, ?, ?)",
            (session_id, sender, message, datetime.utcnow().isoformat())
        )
    
    conn.commit()
    conn.close()

def get_session_logs(session_id):
    conn = get_db_connection()
    c = conn.cursor()
    
    if DATABASE_URL:
        # PostgreSQL
        c.execute("SELECT sender, message, timestamp FROM chat_logs WHERE session_id=%s ORDER BY id", (session_id,))
    else:
        # SQLite
        c.execute("SELECT sender, message, timestamp FROM chat_logs WHERE session_id=? ORDER BY id", (session_id,))
    
    rows = c.fetchall()
    conn.close()
    return rows
