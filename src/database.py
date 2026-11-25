import sqlite3
from typing import Optional, List, Dict, Any
from cryptography.fernet import Fernet
from src.config import DATABASE_PATH, ENCRYPTION_KEY

_cipher = Fernet(ENCRYPTION_KEY)

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db() -> None:
    """Initializes the database schema."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_sessions (
                user_id INTEGER PRIMARY KEY,
                phone TEXT NOT NULL,
                encrypted_session TEXT NOT NULL,
                auto_save_ttl INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

def encrypt_session(session_str: str) -> str:
    """Encrypts a Telethon StringSession string using Fernet."""
    return _cipher.encrypt(session_str.encode("utf-8")).decode("utf-8")

def decrypt_session(encrypted_str: str) -> str:
    """Decrypts an encrypted session string back to Telethon StringSession."""
    return _cipher.decrypt(encrypted_str.encode("utf-8")).decode("utf-8")

def save_user_session(user_id: int, phone: str, session_str: str) -> None:
    """Saves or updates an encrypted user session in the database."""
    encrypted = encrypt_session(session_str)
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO user_sessions (user_id, phone, encrypted_session, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                phone = excluded.phone,
                encrypted_session = excluded.encrypted_session,
                updated_at = CURRENT_TIMESTAMP
        """, (user_id, phone, encrypted))
        conn.commit()

def get_user_session(user_id: int) -> Optional[Dict[str, Any]]:
    """Retrieves and decrypts a user session."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM user_sessions WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if not row:
            return None
        
        decrypted = decrypt_session(row["encrypted_session"])
        return {
            "user_id": row["user_id"],
            "phone": row["phone"],
            "session_str": decrypted,
            "auto_save_ttl": bool(row["auto_save_ttl"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"]
        }

def delete_user_session(user_id: int) -> bool:
    """Deletes a user session (logout)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
        conn.commit()
        return cursor.rowcount > 0

def get_all_active_users() -> List[Dict[str, Any]]:
    """Returns all active user records with decrypted session strings."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM user_sessions")
        rows = cursor.fetchall()
        
        users = []
        for row in rows:
            try:
                decrypted = decrypt_session(row["encrypted_session"])
                users.append({
                    "user_id": row["user_id"],
                    "phone": row["phone"],
                    "session_str": decrypted,
                    "auto_save_ttl": bool(row["auto_save_ttl"])
                })
            except Exception as e:
                print(f"[!] Error decrypting session for user {row['user_id']}: {e}")
        return users

def set_ttl_preference(user_id: int, enabled: bool) -> None:
    """Updates auto-save TTL preference."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE user_sessions
            SET auto_save_ttl = ?, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
        """, (1 if enabled else 0, user_id))
        conn.commit()
