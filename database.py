import sqlite3
import os
import logging

DB_PATH = 'users.db'

def init_db():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        username TEXT,
        registered INTEGER DEFAULT 0,
        status TEXT DEFAULT 'Free',
        deposited INTEGER DEFAULT 0,
        vip INTEGER DEFAULT 0,
        deposit_message_id INTEGER
    )
        ''')
        
        # Add deposit_message_id column if it doesn't exist
        c.execute("PRAGMA table_info(users)")
        columns = [col[1] for col in c.fetchall()]
        if 'deposit_message_id' not in columns:
            c.execute('ALTER TABLE users ADD COLUMN deposit_message_id INTEGER')
        
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Database initialization error: {e}")
    finally:
        if conn:
            conn.close()

def get_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE id = ?', (user_id,))
    user = c.fetchone()
    conn.close()
    return user

def create_user(user_id, username):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute('INSERT INTO users (id, username, registered) VALUES (?, ?, 0)', 
                 (user_id, username))
        conn.commit()
    except sqlite3.IntegrityError:
        # User already exists
        pass
    finally:
        conn.close()

def update_user_status(user_id, status):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE users SET status = ? WHERE id = ?', (status, user_id))
    conn.commit()
    conn.close()

def mark_deposited(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE users SET deposited = 1, vip = 1, status = "VIP" WHERE id = ?', (user_id,))
    conn.commit()
    conn.close()

def update_deposit_message_id(user_id, message_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE users SET deposit_message_id = ? WHERE id = ?', (message_id, user_id))
    conn.commit()
    conn.close()

def get_deposit_message_id(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT deposit_message_id FROM users WHERE id = ?', (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

def get_all_users():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT id FROM users')
    users = [row[0] for row in c.fetchall()]
    conn.close()
    return users

def get_user_count():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM users')
    count = c.fetchone()[0]
    conn.close()
    return count

def reset_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE users SET status = "Free", deposited = 0, vip = 0 WHERE id = ?', (user_id,))
    conn.commit()
    conn.close()

def mark_user_registered(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE users SET registered = 1 WHERE id = ?', (user_id,))
    conn.commit()
    conn.close()

def is_user_registered(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT registered FROM users WHERE id = ?', (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else False
