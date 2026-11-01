"""StudyBuddy AI — Professional Multi-User AI Platform with Guest Access.

This module implements a complete, commercial-grade AI study platform using Flask,
SQLite, and Google GenAI SDK (`google-genai`).

Key Capabilities:
- Three Access Modes: Registered Login, Sign Up, and Instant Guest Access.
- Permanent SQLite persistent storage with strict per-user/per-guest data isolation.
- Guest account management with usage limits and seamless account upgrade (with conversation transfer).
- Multi-turn conversation memory with 12-message sliding window and role sequence guarantees.
- Comprehensive REST APIs for authentication, conversations CRUD, search, and response regeneration.
- Security: Werkzeug password hashing, HttpOnly session cookies, input validation, SQL injection protection, and sanitized logging.
"""

import os
import re
import uuid
import sqlite3
import logging
import secrets
import threading
from datetime import datetime, timezone, timedelta
from contextlib import contextmanager
from typing import Dict, List, Optional, Tuple, Any

from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

# Import official Google GenAI SDK
from google import genai
from google.genai import types
from google.genai import errors as genai_errors

# Load environment variables from .env file (resolved relative to this file)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

# Configure logging without exposing sensitive data
class SensitiveDataFilter(logging.Filter):
    """Filter that sanitizes API keys and secrets from log messages."""
    API_KEY_REGEX = re.compile(r'AIza[0-9A-Za-z\-_]{35}')

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self.API_KEY_REGEX.sub('[REDACTED_API_KEY]', record.msg)
            api_key = os.getenv("GEMINI_API_KEY")
            if api_key and len(api_key) > 5 and api_key != "your_gemini_api_key_here":
                record.msg = record.msg.replace(api_key, '[REDACTED_API_KEY]')
        return True

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger("studybuddy_ai")
logger.addFilter(SensitiveDataFilter())

# ---------------------------------------------------------------------------
# Configuration & Constants
# ---------------------------------------------------------------------------
MAX_HISTORY_MESSAGES: int = 12  # Maximum number of messages passed to Gemini API
DEFAULT_MODEL: str = "gemini-flash-lite-latest"
DEFAULT_TIMEOUT_SECONDS: float = 30.0
GUEST_MESSAGE_LIMIT: int = 25   # Maximum prompts permitted for unverified guest sessions

# Known standard Gemini models in priority order for fallback
FALLBACK_MODELS = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-flash-lite-latest"]

SYSTEM_PROMPT: str = (
    "You are StudyBuddy AI, a friendly and knowledgeable AI study assistant. "
    "Help students understand programming, computer science, algorithms, "
    "artificial intelligence, machine learning, and technical concepts. "
    "Explain difficult topics in simple English. Provide structured explanations, "
    "practical examples, and step-by-step guidance. Remember relevant information "
    "from the conversation history provided. Do not invent facts or claim to "
    "remember information that is not present in the available context. If you are "
    "uncertain, explain the uncertainty. Be helpful, professional, and concise."
)

EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')

# ---------------------------------------------------------------------------
# Flask Application Setup
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "studybuddy-super-secret-key-prod-2026")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)

# ---------------------------------------------------------------------------
# SQLite Persistent Storage
# ---------------------------------------------------------------------------
DB_PATH = os.getenv("SQLITE_DB_PATH", os.path.join(BASE_DIR, "studybuddy.db"))

@contextmanager
def get_db(custom_path: Optional[str] = None):
    """Context manager for SQLite database connection with row factory and foreign keys."""
    target_path = custom_path or DB_PATH
    conn = sqlite3.connect(target_path, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db(custom_path: Optional[str] = None) -> None:
    """Initialize SQLite tables for users, conversations, messages, and password resets."""
    target_path = custom_path or DB_PATH
    with get_db(target_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                is_guest INTEGER DEFAULT 0,
                guest_message_count INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS password_resets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                token TEXT UNIQUE NOT NULL,
                expires_at TEXT NOT NULL,
                used INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        # Migration check: if conversations was created in v2.0 without user_id
        cursor = conn.execute("PRAGMA table_info(conversations)")
        cols = [r["name"] for r in cursor.fetchall()]
        if "user_id" not in cols:
            conn.execute("ALTER TABLE conversations ADD COLUMN user_id TEXT DEFAULT 'guest-legacy'")
            now_iso = datetime.now(timezone.utc).isoformat()
            conn.execute("""
                INSERT OR IGNORE INTO users (id, name, email, password_hash, is_guest, guest_message_count, created_at, updated_at)
                VALUES ('guest-legacy', 'Guest Student', 'guest-legacy@guest.local', '', 1, 0, ?, ?)
            """, (now_iso, now_iso))

        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations(updated_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id)")

# Initialize database on app startup
init_db()

# ---------------------------------------------------------------------------
# Database Helpers: User & Authentication Operations
# ---------------------------------------------------------------------------

def db_create_user(
    name: str,
    email: str,
    password: str,
    is_guest: bool = False,
    custom_path: Optional[str] = None
) -> Dict[str, Any]:
    """Create a new registered or guest user record."""
    now_iso = datetime.now(timezone.utc).isoformat()
    user_id = f"guest-{uuid.uuid4().hex[:12]}" if is_guest else str(uuid.uuid4())
    pw_hash = generate_password_hash(password) if password else ""
    with get_db(custom_path) as conn:
        conn.execute("""
            INSERT INTO users (id, name, email, password_hash, is_guest, guest_message_count, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 0, ?, ?)
        """, (user_id, name.strip(), email.lower().strip(), pw_hash, 1 if is_guest else 0, now_iso, now_iso))
        return {
            "id": user_id,
            "name": name.strip(),
            "email": email.lower().strip(),
            "is_guest": bool(is_guest),
            "guest_message_count": 0,
            "guest_limit": GUEST_MESSAGE_LIMIT
        }

def db_get_user_by_id(user_id: str, custom_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieve user metadata by ID."""
    with get_db(custom_path) as conn:
        cursor = conn.execute(
            "SELECT id, name, email, is_guest, guest_message_count, created_at FROM users WHERE id = ?",
            (user_id,)
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "name": row["name"],
            "email": row["email"],
            "is_guest": bool(row["is_guest"]),
            "guest_message_count": row["guest_message_count"] or 0,
            "guest_limit": GUEST_MESSAGE_LIMIT,
            "created_at": row["created_at"]
        }

def db_get_user_by_email(email: str, custom_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieve full user record by email (including password_hash)."""
    with get_db(custom_path) as conn:
        cursor = conn.execute(
            "SELECT id, name, email, password_hash, is_guest, guest_message_count, created_at FROM users WHERE LOWER(email) = LOWER(?)",
            (email.strip(),)
        )
        row = cursor.fetchone()
        if not row:
            return None
        return dict(row)

def db_increment_guest_message_count(user_id: str, custom_path: Optional[str] = None) -> int:
    """Increment message count for a guest session."""
    with get_db(custom_path) as conn:
        conn.execute("UPDATE users SET guest_message_count = guest_message_count + 1 WHERE id = ?", (user_id,))
        cursor = conn.execute("SELECT guest_message_count FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        return row["guest_message_count"] if row else 0

def db_transfer_guest_conversations(old_guest_id: str, new_user_id: str, custom_path: Optional[str] = None) -> int:
    """Securely transfer conversation ownership from guest session to a registered user."""
    with get_db(custom_path) as conn:
        cursor = conn.execute(
            "UPDATE conversations SET user_id = ? WHERE user_id = ?",
            (new_user_id, old_guest_id)
        )
        count = cursor.rowcount
        conn.execute("DELETE FROM users WHERE id = ? AND is_guest = 1", (old_guest_id,))
        return count

def db_create_password_reset(user_id: str, custom_path: Optional[str] = None) -> str:
    """Generate a secure password reset token."""
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires = (now + timedelta(hours=1)).isoformat()
    with get_db(custom_path) as conn:
        conn.execute("""
            INSERT INTO password_resets (user_id, token, expires_at, used, created_at)
            VALUES (?, ?, ?, 0, ?)
        """, (user_id, token, expires, now.isoformat()))
    return token

def db_verify_and_use_reset_token(token: str, new_password: str, custom_path: Optional[str] = None) -> bool:
    """Verify reset token and update user password."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db(custom_path) as conn:
        cursor = conn.execute("""
            SELECT id, user_id, expires_at, used FROM password_resets
            WHERE token = ? AND used = 0
        """, (token,))
        row = cursor.fetchone()
        if not row:
            return False
        if row["expires_at"] < now_iso:
            return False
        user_id = row["user_id"]
        new_pw_hash = generate_password_hash(new_password)
        conn.execute("UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?", (new_pw_hash, now_iso, user_id))
        conn.execute("UPDATE password_resets SET used = 1 WHERE id = ?", (row["id"],))
        return True

# ---------------------------------------------------------------------------
# Database Helpers: Conversation & Message Operations (Isolated by User)
# ---------------------------------------------------------------------------

def generate_smart_title(prompt: str) -> str:
    """Derive a clean conversation title from the first prompt."""
    cleaned = prompt.strip().replace("\n", " ")
    cleaned = re.sub(r'^[#*\s\-]+', '', cleaned)
    cleaned = re.sub(r'^(hello|hi|hey|can you|could you|please)\b[\s,:]*', '', cleaned, flags=re.IGNORECASE).strip()
    if not cleaned:
        cleaned = prompt.strip()
    if len(cleaned) <= 36:
        return cleaned or "New Study Session"
    words = cleaned.split()
    title = ""
    for w in words:
        if len(title) + len(w) + 1 > 35:
            break
        title = f"{title} {w}".strip()
    return (title or cleaned[:35]).strip() + "..."

def db_list_conversations(user_id: Optional[str] = None, custom_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """List conversations belonging strictly to the specified user/guest, or all if user_id is None."""
    with get_db(custom_path) as conn:
        if user_id:
            cursor = conn.execute("""
                SELECT 
                    c.id, 
                    c.title, 
                    c.created_at, 
                    c.updated_at,
                    COUNT(m.id) as message_count,
                    (SELECT content FROM messages WHERE conversation_id = c.id ORDER BY id DESC LIMIT 1) as last_message
                FROM conversations c
                LEFT JOIN messages m ON c.id = m.conversation_id
                WHERE c.user_id = ?
                GROUP BY c.id
                ORDER BY c.updated_at DESC
            """, (user_id,))
        else:
            cursor = conn.execute("""
                SELECT 
                    c.id, 
                    c.title, 
                    c.created_at, 
                    c.updated_at,
                    COUNT(m.id) as message_count,
                    (SELECT content FROM messages WHERE conversation_id = c.id ORDER BY id DESC LIMIT 1) as last_message
                FROM conversations c
                LEFT JOIN messages m ON c.id = m.conversation_id
                GROUP BY c.id
                ORDER BY c.updated_at DESC
            """)
        return [
            {
                "id": r["id"],
                "title": r["title"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
                "message_count": r["message_count"],
                "last_message": r["last_message"] or ""
            }
            for r in cursor.fetchall()
        ]

def db_get_conversation(conv_id: str, user_id: Optional[str] = None, custom_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieve metadata for a conversation verifying ownership if user_id is provided."""
    with get_db(custom_path) as conn:
        if user_id:
            cursor = conn.execute(
                "SELECT id, user_id, title, created_at, updated_at FROM conversations WHERE id = ? AND user_id = ?",
                (conv_id, user_id)
            )
        else:
            cursor = conn.execute(
                "SELECT id, user_id, title, created_at, updated_at FROM conversations WHERE id = ?",
                (conv_id,)
            )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "title": row["title"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"]
        }

def db_get_messages(conv_id: str, user_id: Optional[str] = None, custom_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve ordered message history for a conversation verifying ownership if user_id is provided."""
    with get_db(custom_path) as conn:
        if user_id:
            check = conn.execute("SELECT id FROM conversations WHERE id = ? AND user_id = ?", (conv_id, user_id)).fetchone()
            if not check:
                return []
        cursor = conn.execute(
            "SELECT id, role, content, created_at FROM messages WHERE conversation_id = ? ORDER BY id ASC",
            (conv_id,)
        )
        return [
            {
                "id": r["id"],
                "role": r["role"],
                "content": r["content"],
                "timestamp": r["created_at"]
            }
            for r in cursor.fetchall()
        ]

def db_save_turn(
    conv_id: str,
    user_id: str,
    user_content: str,
    model_content: str,
    custom_path: Optional[str] = None
) -> str:
    """Record a user prompt and model response turn with ownership verification."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db(custom_path) as conn:
        cursor = conn.execute("SELECT id, user_id, title FROM conversations WHERE id = ?", (conv_id,))
        row = cursor.fetchone()
        if not row:
            title = generate_smart_title(user_content)
            conn.execute(
                "INSERT INTO conversations (id, user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (conv_id, user_id, title, now_iso, now_iso)
            )
        else:
            if row["user_id"] != user_id:
                raise PermissionError("Access denied: You do not own this conversation.")
            title = row["title"]
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now_iso, conv_id)
            )
        
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, 'user', ?, ?)",
            (conv_id, user_content, now_iso)
        )
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, 'model', ?, ?)",
            (conv_id, model_content, now_iso)
        )
        return title

def db_rename_conversation(conv_id: str, user_id: Optional[str] = None, new_title: str = "", custom_path: Optional[str] = None) -> bool:
    """Update conversation title verifying user ownership if user_id is provided."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db(custom_path) as conn:
        if user_id:
            cursor = conn.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ? AND user_id = ?",
                (new_title, now_iso, conv_id, user_id)
            )
        else:
            cursor = conn.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                (new_title, now_iso, conv_id)
            )
        return cursor.rowcount > 0

def db_delete_conversation(conv_id: str, user_id: Optional[str] = None, custom_path: Optional[str] = None) -> bool:
    """Delete a conversation verifying user ownership if user_id is provided."""
    with get_db(custom_path) as conn:
        if user_id:
            cursor = conn.execute("DELETE FROM conversations WHERE id = ? AND user_id = ?", (conv_id, user_id))
        else:
            cursor = conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
        return cursor.rowcount > 0

def db_search_conversations(query: str, user_id: str, custom_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Search conversations by title or message content within the user's scope."""
    pattern = f"%{query.strip()}%"
    with get_db(custom_path) as conn:
        cursor = conn.execute("""
            SELECT DISTINCT 
                c.id, 
                c.title, 
                c.created_at, 
                c.updated_at,
                COUNT(m.id) as message_count,
                (SELECT content FROM messages WHERE conversation_id = c.id ORDER BY id DESC LIMIT 1) as last_message
            FROM conversations c
            LEFT JOIN messages m ON c.id = m.conversation_id
            WHERE c.user_id = ? AND (c.title LIKE ? OR m.content LIKE ?)
            GROUP BY c.id
            ORDER BY c.updated_at DESC
        """, (user_id, pattern, pattern))
        return [
            {
                "id": r["id"],
                "title": r["title"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
                "message_count": r["message_count"],
                "last_message": r["last_message"] or ""
            }
            for r in cursor.fetchall()
        ]

def db_delete_last_model_message(conv_id: str, user_id: str, custom_path: Optional[str] = None) -> Optional[Tuple[str, List[Dict[str, Any]]]]:
    """Delete the last model reply for regeneration verifying user ownership."""
    with get_db(custom_path) as conn:
        conv_check = conn.execute("SELECT id FROM conversations WHERE id = ? AND user_id = ?", (conv_id, user_id)).fetchone()
        if not conv_check:
            return None
        cursor = conn.execute(
            "SELECT id, role, content, created_at FROM messages WHERE conversation_id = ? ORDER BY id ASC",
            (conv_id,)
        )
        all_msgs = [dict(r) for r in cursor.fetchall()]
        if not all_msgs:
            return None
        if all_msgs[-1]["role"] == "model":
            model_msg_id = all_msgs[-1]["id"]
            conn.execute("DELETE FROM messages WHERE id = ?", (model_msg_id,))
            all_msgs.pop()
        if not all_msgs or all_msgs[-1]["role"] != "user":
            return None
        last_user_prompt = all_msgs[-1]["content"]
        prior_history = [
            {"role": m["role"], "content": m["content"]}
            for m in all_msgs[:-1]
        ]
        return last_user_prompt, prior_history

def db_add_model_reply(conv_id: str, reply_text: str, custom_path: Optional[str] = None) -> None:
    """Append a model reply to an existing conversation."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db(custom_path) as conn:
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, 'model', ?, ?)",
            (conv_id, reply_text, now_iso)
        )
        conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now_iso, conv_id))

# ---------------------------------------------------------------------------
# Backward Compatibility In-Memory Cache
# ---------------------------------------------------------------------------
conversations_store: Dict[str, List[Dict[str, Any]]] = {}
store_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Current User Session Middleware
# ---------------------------------------------------------------------------

def get_current_user(create_guest_if_missing: bool = True) -> Optional[Dict[str, Any]]:
    """
    Retrieve authenticated user or provision a cryptographically secure guest session.
    Guarantees that user identity is derived strictly from server-side session state.
    """
    user_id = session.get("user_id")
    if user_id:
        user = db_get_user_by_id(user_id)
        if user:
            return user
        session.pop("user_id", None)
        session.pop("is_guest", None)

    if create_guest_if_missing:
        guest_email = f"guest_{uuid.uuid4().hex[:8]}@studybuddy.local"
        guest = db_create_user(name="Guest Student", email=guest_email, password="", is_guest=True)
        session["user_id"] = guest["id"]
        session["is_guest"] = True
        session.permanent = True
        logger.info("Initialized new persistent guest session: %s", guest["id"])
        return guest

    return None

# ---------------------------------------------------------------------------
# Gemini API & Context Management Integration
# ---------------------------------------------------------------------------

def get_gemini_api_key() -> Optional[str]:
    """Retrieve and validate the Gemini API key from environment."""
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key or key == "your_gemini_api_key_here":
        return None
    return key

def get_gemini_model() -> str:
    """Retrieve the configured Gemini model name."""
    return os.getenv("GEMINI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL

def get_gemini_timeout() -> float:
    """Retrieve the configured API timeout in seconds."""
    raw_val = os.getenv("GEMINI_TIMEOUT", str(DEFAULT_TIMEOUT_SECONDS)).strip()
    try:
        return float(raw_val)
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS

def manage_context_window(
    history: List[Dict[str, Any]],
    new_user_message: str,
    max_messages: int = MAX_HISTORY_MESSAGES
) -> List[types.Content]:
    """
    Format and manage the context window for the Gemini API.
    Maintains 12 messages maximum, strictly starts with user, and alternates roles.
    """
    candidate_messages: List[Dict[str, str]] = [
        {"role": msg["role"], "content": msg["content"]}
        for msg in history
        if msg.get("role") in ("user", "model") and msg.get("content")
    ]
    candidate_messages.append({"role": "user", "content": new_user_message})

    if len(candidate_messages) > max_messages:
        candidate_messages = candidate_messages[-max_messages:]

    while candidate_messages and candidate_messages[0]["role"] != "user":
        candidate_messages.pop(0)

    if not candidate_messages:
        candidate_messages = [{"role": "user", "content": new_user_message}]

    merged_messages: List[Dict[str, str]] = []
    for msg in candidate_messages:
        if merged_messages and merged_messages[-1]["role"] == msg["role"]:
            merged_messages[-1]["content"] += "\n\n" + msg["content"]
        else:
            merged_messages.append({"role": msg["role"], "content": msg["content"]})

    if merged_messages[-1]["role"] != "user":
        merged_messages.append({"role": "user", "content": new_user_message})

    contents: List[types.Content] = []
    for msg in merged_messages:
        content_obj = types.Content(
            role=msg["role"],
            parts=[types.Part.from_text(text=msg["content"])]
        )
        contents.append(content_obj)

    return contents

def call_gemini_api(
    contents: List[types.Content],
    api_key: str,
    model_name: str,
    timeout: float
) -> str:
    """
    Execute a call to Google Gemini API using official google-genai SDK.
    Includes millisecond timeout conversion and automatic model fallback.
    """
    timeout_ms = int(timeout * 1000) if timeout else 30000
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=timeout_ms)
    )

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        temperature=0.7,
    )

    models_to_try = [model_name]
    for fb in FALLBACK_MODELS:
        if fb != model_name:
            models_to_try.append(fb)

    last_api_error = None
    for current_model in models_to_try:
        try:
            logger.info("Attempting Gemini API call with model=%s, context_turns=%d", current_model, len(contents))
            response = client.models.generate_content(
                model=current_model,
                contents=contents,
                config=config,
            )

            if not response:
                raise ValueError("No response object received from Gemini API.")

            reply_text = response.text
            if reply_text and reply_text.strip():
                return reply_text.strip()

            if response.candidates:
                first_candidate = response.candidates[0]
                finish_reason = getattr(first_candidate, "finish_reason", None)
                if finish_reason:
                    logger.warning("Gemini generation finished with reason: %s", finish_reason)
                    if "SAFETY" in str(finish_reason).upper():
                        raise ValueError("Response blocked by safety filters. Please rephrase your question.")
                    if "RECITATION" in str(finish_reason).upper():
                        raise ValueError("Response blocked due to recitation policies. Please rephrase.")

            raise ValueError("The model returned an empty response. Please try asking in a different way.")

        except genai_errors.APIError as ae:
            last_api_error = ae
            if getattr(ae, "code", None) in (404, 503):
                logger.warning("Model '%s' returned %s. Trying fallback...", current_model, getattr(ae, "code", None))
                continue
            raise ae

    if last_api_error:
        raise last_api_error
    raise ValueError("All candidate Gemini models failed to generate a response.")

# ---------------------------------------------------------------------------
# Routes: Core & UI Views
# ---------------------------------------------------------------------------

@app.route("/", methods=["GET"])
def index():
    """Serve the main chatbot interface ensuring active guest or registered session."""
    user = get_current_user(create_guest_if_missing=True)
    return render_template("index.html", current_user=user)

@app.route("/login", methods=["GET"])
def login_view():
    """Serve the dedicated authentication screen (Login tab active)."""
    return render_template("auth.html", initial_tab="login")

@app.route("/register", methods=["GET"])
def register_view():
    """Serve the dedicated authentication screen (Sign Up tab active)."""
    return render_template("auth.html", initial_tab="register")

@app.route("/forgot-password", methods=["GET"])
def forgot_password_view():
    """Serve the dedicated authentication screen (Forgot Password tab active)."""
    return render_template("auth.html", initial_tab="forgot")

@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint indicating service and database status."""
    db_status = "ok"
    try:
        with get_db() as conn:
            conn.execute("SELECT 1")
    except Exception as exc:
        db_status = f"error: {str(exc)}"

    return jsonify({
        "status": "ok",
        "app": "StudyBuddy AI",
        "version": "3.0.0",
        "model": get_gemini_model(),
        "database": db_status
    }), 200

# ---------------------------------------------------------------------------
# Routes: Authentication & User Management
# ---------------------------------------------------------------------------

@app.route("/auth/me", methods=["GET"])
def auth_me():
    """Return the profile of the current authenticated user or guest."""
    user = get_current_user(create_guest_if_missing=True)
    return jsonify({
        "authenticated": True,
        "user": user
    }), 200

@app.route("/auth/register", methods=["POST"])
def auth_register():
    """Register a new permanent user account with optional guest conversation transfer."""
    if not request.is_json:
        return jsonify({"error": "Request body must be valid JSON."}), 400

    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    confirm_password = data.get("confirm_password", "")
    transfer_chats = bool(data.get("transfer_guest_chats", True))

    if not name or not email or not password:
        return jsonify({"error": "Name, email, and password are required."}), 400

    if not EMAIL_REGEX.match(email):
        return jsonify({"error": "Please provide a valid email address."}), 400

    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters long."}), 400

    if password != confirm_password:
        return jsonify({"error": "Passwords do not match."}), 400

    existing_user = db_get_user_by_email(email)
    if existing_user and not existing_user.get("is_guest"):
        return jsonify({"error": "An account with this email address already exists. Please log in."}), 409

    try:
        old_guest_id = session.get("user_id") if session.get("is_guest") else None

        user = db_create_user(name=name, email=email, password=password, is_guest=False)
        new_user_id = user["id"]

        transferred_count = 0
        if old_guest_id and transfer_chats:
            transferred_count = db_transfer_guest_conversations(old_guest_id, new_user_id)
            logger.info("Transferred %d guest conversations from %s to %s", transferred_count, old_guest_id, new_user_id)

        session["user_id"] = new_user_id
        session["is_guest"] = False
        session.permanent = True

        return jsonify({
            "status": "ok",
            "message": "Account created successfully!",
            "user": user,
            "transferred_conversations": transferred_count
        }), 201

    except Exception as exc:
        logger.error("Registration failure: %s", exc)
        return jsonify({"error": "Failed to create account. Please try again."}), 500

@app.route("/auth/login", methods=["POST"])
def auth_login():
    """Authenticate an existing user and establish a secure session."""
    if not request.is_json:
        return jsonify({"error": "Request body must be valid JSON."}), 400

    data = request.get_json(silent=True) or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not email or not password:
        return jsonify({"error": "Email and password are required."}), 400

    user_record = db_get_user_by_email(email)
    if not user_record or user_record.get("is_guest"):
        return jsonify({"error": "Invalid email or password."}), 401

    if not check_password_hash(user_record["password_hash"], password):
        return jsonify({"error": "Invalid email or password."}), 401

    session["user_id"] = user_record["id"]
    session["is_guest"] = False
    session.permanent = True

    logger.info("User logged in successfully: %s (%s)", user_record["name"], user_record["email"])
    return jsonify({
        "status": "ok",
        "message": "Logged in successfully!",
        "user": {
            "id": user_record["id"],
            "name": user_record["name"],
            "email": user_record["email"],
            "is_guest": False
        }
    }), 200

@app.route("/auth/guest", methods=["POST"])
def auth_guest():
    """Provision or reset a persistent guest session."""
    guest_email = f"guest_{uuid.uuid4().hex[:8]}@studybuddy.local"
    guest = db_create_user(name="Guest Student", email=guest_email, password="", is_guest=True)
    session["user_id"] = guest["id"]
    session["is_guest"] = True
    session.permanent = True

    return jsonify({
        "status": "ok",
        "message": "Guest session initialized.",
        "user": guest
    }), 200

@app.route("/auth/logout", methods=["POST"])
def auth_logout():
    """Log out current user and initialize a clean guest session."""
    session.clear()
    new_guest = get_current_user(create_guest_if_missing=True)
    return jsonify({
        "status": "ok",
        "message": "Logged out successfully.",
        "user": new_guest
    }), 200

@app.route("/auth/upgrade-guest", methods=["POST"])
def auth_upgrade_guest():
    """Upgrade the current guest account to a registered account with conversation transfer."""
    if not request.is_json:
        return jsonify({"error": "Request body must be valid JSON."}), 400

    current_user = get_current_user(create_guest_if_missing=False)
    if not current_user or not current_user.get("is_guest"):
        return jsonify({"error": "Only active guest accounts can be upgraded."}), 400

    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    transfer_chats = bool(data.get("transfer_chats", True))

    if not name or not email or not password:
        return jsonify({"error": "Name, email, and password are required."}), 400

    if not EMAIL_REGEX.match(email):
        return jsonify({"error": "Invalid email address format."}), 400

    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters."}), 400

    existing = db_get_user_by_email(email)
    if existing and not existing.get("is_guest"):
        return jsonify({"error": "An account with this email already exists."}), 409

    try:
        old_guest_id = current_user["id"]
        new_user = db_create_user(name=name, email=email, password=password, is_guest=False)
        new_user_id = new_user["id"]

        transferred_count = 0
        if transfer_chats:
            transferred_count = db_transfer_guest_conversations(old_guest_id, new_user_id)

        session["user_id"] = new_user_id
        session["is_guest"] = False
        session.permanent = True

        return jsonify({
            "status": "ok",
            "message": "Guest account successfully upgraded to permanent account!",
            "user": new_user,
            "transferred_conversations": transferred_count
        }), 200
    except Exception as exc:
        logger.error("Upgrade guest failure: %s", exc)
        return jsonify({"error": "Failed to upgrade guest account."}), 500

@app.route("/auth/forgot-password", methods=["POST"])
def auth_forgot_password():
    """Generate a password reset token for the given email."""
    if not request.is_json:
        return jsonify({"error": "Request body must be valid JSON."}), 400

    data = request.get_json(silent=True) or {}
    email = data.get("email", "").strip().lower()
    if not email:
        return jsonify({"error": "Email is required."}), 400

    user = db_get_user_by_email(email)
    if not user or user.get("is_guest"):
        # For security, return generic success notice
        return jsonify({
            "status": "ok",
            "message": "If this email is registered, password reset instructions have been generated."
        }), 200

    token = db_create_password_reset(user["id"])
    logger.info("Generated password reset token for %s", email)
    return jsonify({
        "status": "ok",
        "message": "Password reset token generated successfully.",
        "reset_token": token
    }), 200

@app.route("/auth/reset-password", methods=["POST"])
def auth_reset_password():
    """Reset password using a valid reset token."""
    if not request.is_json:
        return jsonify({"error": "Request body must be valid JSON."}), 400

    data = request.get_json(silent=True) or {}
    token = data.get("token", "").strip()
    password = data.get("password", "")
    confirm_password = data.get("confirm_password", "")

    if not token or not password:
        return jsonify({"error": "Reset token and new password are required."}), 400

    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters."}), 400

    if password != confirm_password:
        return jsonify({"error": "Passwords do not match."}), 400

    success = db_verify_and_use_reset_token(token, password)
    if not success:
        return jsonify({"error": "Invalid or expired password reset token."}), 400

    return jsonify({
        "status": "ok",
        "message": "Password updated successfully. You can now log in."
    }), 200

# ---------------------------------------------------------------------------
# Routes: Conversation History (Strictly Isolated by User)
# ---------------------------------------------------------------------------

@app.route("/conversations", methods=["GET"])
def list_conversations():
    """List all saved conversations for the authenticated user/guest."""
    user = get_current_user(create_guest_if_missing=True)
    try:
        conversations = db_list_conversations(user["id"])
        return jsonify({"conversations": conversations}), 200
    except Exception as exc:
        logger.error("Failed to list conversations: %s", exc)
        return jsonify({"error": "Failed to retrieve conversation history."}), 500

@app.route("/conversations/search", methods=["GET"])
def search_conversations():
    """Search conversations by title or message content within the user's scope."""
    user = get_current_user(create_guest_if_missing=True)
    query = request.args.get("q", "").strip()
    try:
        if not query:
            results = db_list_conversations(user["id"])
        else:
            results = db_search_conversations(query, user["id"])
        return jsonify({
            "query": query,
            "conversations": results
        }), 200
    except Exception as exc:
        logger.error("Failed to search conversations: %s", exc)
        return jsonify({"error": "Failed to search conversation history."}), 500

@app.route("/conversations/<conv_id>", methods=["GET"])
def get_conversation_detail(conv_id: str):
    """Retrieve full details and messages verifying user ownership."""
    user = get_current_user(create_guest_if_missing=True)
    try:
        conv = db_get_conversation(conv_id, user["id"])
        if not conv:
            return jsonify({"error": "Conversation not found."}), 404
        messages = db_get_messages(conv_id, user["id"])
        return jsonify({
            "conversation": conv,
            "messages": messages
        }), 200
    except Exception as exc:
        logger.error("Failed to retrieve conversation %s: %s", conv_id, exc)
        return jsonify({"error": "Failed to retrieve conversation."}), 500

@app.route("/conversations/<conv_id>", methods=["PATCH"])
def rename_conversation(conv_id: str):
    """Rename a conversation title verifying ownership."""
    user = get_current_user(create_guest_if_missing=True)
    if not request.is_json:
        return jsonify({"error": "Request body must be valid JSON."}), 400

    data = request.get_json(silent=True) or {}
    title = data.get("title")
    if not title or not isinstance(title, str) or not title.strip():
        return jsonify({"error": "'title' field is required and cannot be empty."}), 400

    clean_title = title.strip()
    try:
        updated = db_rename_conversation(conv_id, user["id"], clean_title)
        if not updated:
            return jsonify({"error": "Conversation not found or access denied."}), 404
        return jsonify({
            "status": "ok",
            "conversation_id": conv_id,
            "title": clean_title
        }), 200
    except Exception as exc:
        logger.error("Failed to rename conversation %s: %s", conv_id, exc)
        return jsonify({"error": "Failed to update conversation."}), 500

@app.route("/conversations/<conv_id>", methods=["DELETE"])
def delete_conversation(conv_id: str):
    """Delete a conversation verifying ownership."""
    user = get_current_user(create_guest_if_missing=True)
    try:
        deleted = db_delete_conversation(conv_id, user["id"])
        if not deleted:
            return jsonify({"error": "Conversation not found or access denied."}), 404
        
        with store_lock:
            conversations_store.pop(conv_id, None)

        return jsonify({
            "status": "ok",
            "message": "Conversation deleted successfully."
        }), 200
    except Exception as exc:
        logger.error("Failed to delete conversation %s: %s", conv_id, exc)
        return jsonify({"error": "Failed to delete conversation."}), 500

# ---------------------------------------------------------------------------
# Route: Chat with Multi-turn Memory, Ownership & Guest Quota
# ---------------------------------------------------------------------------

@app.route("/chat", methods=["POST"])
def chat():
    """
    Process chat messages with persistent multi-turn memory, role isolation, and guest quotas.
    """
    user = get_current_user(create_guest_if_missing=True)

    if not request.is_json:
        return jsonify({"error": "Request body must be valid JSON with Content-Type application/json."}), 400

    try:
        data = request.get_json(silent=False)
    except Exception:
        return jsonify({"error": "Malformed JSON in request payload."}), 400

    if not isinstance(data, dict):
        return jsonify({"error": "Request payload must be a JSON object."}), 400

    is_regenerate = bool(data.get("regenerate", False))
    raw_conv_id = data.get("conversation_id")

    # Enforce Guest Usage Limit
    if user.get("is_guest"):
        current_count = user.get("guest_message_count", 0)
        if current_count >= GUEST_MESSAGE_LIMIT:
            return jsonify({
                "error": f"Guest message quota reached ({current_count}/{GUEST_MESSAGE_LIMIT}). Please create a free account to continue studying with StudyBuddy AI!",
                "limit_reached": True
            }), 403

    if is_regenerate:
        if not raw_conv_id or not isinstance(raw_conv_id, str) or not raw_conv_id.strip():
            return jsonify({"error": "Missing conversation_id for regeneration."}), 400
        conversation_id = raw_conv_id.strip()

        regen_data = db_delete_last_model_message(conversation_id, user["id"])
        if not regen_data:
            return jsonify({"error": "No previous user turn available to regenerate."}), 400

        user_message, history_messages = regen_data
        
        with store_lock:
            if conversation_id in conversations_store and conversations_store[conversation_id]:
                if conversations_store[conversation_id][-1]["role"] == "model":
                    conversations_store[conversation_id].pop()
    else:
        raw_message = data.get("message")
        if raw_message is None:
            return jsonify({"error": "Missing required 'message' field."}), 400
        if not isinstance(raw_message, str):
            return jsonify({"error": "'message' field must be a string."}), 400
        
        user_message = raw_message.strip()
        if not user_message:
            return jsonify({"error": "Message cannot be empty."}), 400

        if raw_conv_id and isinstance(raw_conv_id, str) and raw_conv_id.strip():
            conversation_id = raw_conv_id.strip()
        else:
            conversation_id = str(uuid.uuid4())

        # Verify ownership if continuing an existing conversation
        existing_conv = db_get_conversation(conversation_id, user["id"])
        if raw_conv_id and not existing_conv:
            # If a conversation_id was provided but does not belong to this user, verify if it exists anywhere
            with get_db() as conn:
                foreign_check = conn.execute("SELECT id FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
                if foreign_check:
                    return jsonify({"error": "Unauthorized access to conversation."}), 403

        # Retrieve prior messages for context
        db_msgs = db_get_messages(conversation_id, user["id"])
        if db_msgs:
            history_messages = [{"role": m["role"], "content": m["content"]} for m in db_msgs]
        else:
            with store_lock:
                history_messages = list(conversations_store.get(conversation_id, []))

    api_key = get_gemini_api_key()
    if not api_key:
        logger.error("Request rejected: GEMINI_API_KEY is not configured or is placeholder.")
        return jsonify({
            "error": "Gemini API key is not configured. Please set your GEMINI_API_KEY in the .env file or environment variables to start chatting with StudyBuddy AI."
        }), 503

    model_name = get_gemini_model()
    timeout = get_gemini_timeout()

    contents = manage_context_window(history_messages, user_message, max_messages=MAX_HISTORY_MESSAGES)

    try:
        reply_text = call_gemini_api(contents, api_key, model_name, timeout)
    except ValueError as ve:
        logger.warning("Empty or invalid model response: %s", str(ve))
        return jsonify({"error": str(ve)}), 502
    except genai_errors.APIError as ae:
        code = getattr(ae, "code", None)
        err_msg = str(ae)
        logger.error("Gemini API Error (status_code=%s): %s", code, err_msg)
        
        if code in (401, 403):
            return jsonify({
                "error": "Authentication failed. The provided Gemini API key is invalid or unauthorized."
            }), 401
        elif code == 404:
            return jsonify({
                "error": f"The configured Gemini model '{model_name}' was not found. Please verify GEMINI_MODEL."
            }), 404
        elif code == 429:
            return jsonify({
                "error": "Gemini API rate limit or quota exceeded. Please wait a moment and try again."
            }), 429
        elif code and 500 <= code < 600:
            return jsonify({
                "error": "Google Gemini API service is temporarily unavailable. Please try again shortly."
            }), 503
        else:
            return jsonify({
                "error": "An error occurred while contacting the Gemini API. Please try again."
            }), 502
    except (TimeoutError, Exception) as exc:
        exc_name = type(exc).__name__
        exc_str = str(exc)
        logger.error("Exception during Gemini call (%s): %s", exc_name, exc_str)
        
        if "timeout" in exc_name.lower() or "timeout" in exc_str.lower():
            return jsonify({
                "error": "Request to the Gemini API timed out. Please try again."
            }), 504
        elif "connect" in exc_name.lower() or "network" in exc_str.lower():
            return jsonify({
                "error": "Network error while connecting to Gemini API. Please check your internet connection."
            }), 503
        else:
            return jsonify({
                "error": "An unexpected server error occurred while processing your request."
            }), 500

    # Persist turn in database with user ownership
    now_iso = datetime.now(timezone.utc).isoformat()
    if is_regenerate:
        db_add_model_reply(conversation_id, reply_text)
        conv = db_get_conversation(conversation_id, user["id"])
        conv_title = conv["title"] if conv else "Study Session"
    else:
        conv_title = db_save_turn(conversation_id, user["id"], user_message, reply_text)

    # Increment guest prompt usage count
    new_guest_count = user.get("guest_message_count", 0)
    if user.get("is_guest") and not is_regenerate:
        new_guest_count = db_increment_guest_message_count(user["id"])

    # Maintain backward compatibility store
    with store_lock:
        if conversation_id not in conversations_store:
            conversations_store[conversation_id] = []
        if not is_regenerate:
            conversations_store[conversation_id].append({
                "role": "user",
                "content": user_message,
                "timestamp": now_iso
            })
        conversations_store[conversation_id].append({
            "role": "model",
            "content": reply_text,
            "timestamp": now_iso
        })
        if len(conversations_store[conversation_id]) > 50:
            conversations_store[conversation_id] = conversations_store[conversation_id][-50:]

    logger.info("Processed message for conversation_id=%s, user_id=%s (title='%s')", conversation_id, user["id"], conv_title)
    return jsonify({
        "reply": reply_text,
        "conversation_id": conversation_id,
        "title": conv_title,
        "is_guest": user.get("is_guest", False),
        "guest_message_count": new_guest_count,
        "guest_limit": GUEST_MESSAGE_LIMIT
    }), 200

# ---------------------------------------------------------------------------
# CLI / Development Server Runner
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.getenv("FLASK_PORT", 5001))
    debug = os.getenv("FLASK_DEBUG", "False").lower() in ("true", "1", "yes")
    print(f"Starting StudyBuddy AI server on http://127.0.0.1:{port} (Debug: {debug})...")
    app.run(host="0.0.0.0", port=port, debug=debug)
