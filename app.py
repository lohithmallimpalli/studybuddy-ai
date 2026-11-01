"""StudyBuddy AI - Backend Flask Application.

This module implements a multi-turn AI chatbot application using Flask, SQLite,
and the official Google GenAI Python SDK (`google-genai`).

Endpoints:
    - GET /: Serves the modern web-based chat interface.
    - GET /health: Health check endpoint.
    - POST /chat: Handles user messages, multi-turn conversation memory,
                  context window management, regeneration, and Gemini API calls.
    - GET /conversations: Lists previous conversations with metadata and last message preview.
    - GET /conversations/<id>: Retrieves full message history for a specific conversation.
    - PATCH /conversations/<id>: Renames a conversation.
    - DELETE /conversations/<id>: Deletes a conversation and all its messages.
    - GET /conversations/search: Searches conversations across titles and message contents.
"""

import os
import re
import uuid
import sqlite3
import logging
import threading
from datetime import datetime, timezone
from contextlib import contextmanager
from typing import Dict, List, Optional, Tuple, Any

from flask import Flask, render_template, request, jsonify
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
    
    # Matches common Google API key patterns (e.g. AIzaSy...)
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
    """Initialize SQLite tables for conversations and messages."""
    target_path = custom_path or DB_PATH
    with get_db(target_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_conv_id ON messages(conversation_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations(updated_at DESC)")

def generate_smart_title(prompt: str) -> str:
    """Derive an attractive, human-readable conversation title from the first prompt."""
    cleaned = prompt.strip().replace("\n", " ")
    cleaned = re.sub(r'^[#*\s\-]+', '', cleaned)
    # Remove leading common conversational phrases if desired
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

def db_list_conversations(custom_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return all conversations ordered by recent activity with message count and preview."""
    with get_db(custom_path) as conn:
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

def db_get_conversation(conv_id: str, custom_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieve metadata for a single conversation."""
    with get_db(custom_path) as conn:
        cursor = conn.execute(
            "SELECT id, title, created_at, updated_at FROM conversations WHERE id = ?",
            (conv_id,)
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "title": row["title"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"]
        }

def db_get_messages(conv_id: str, custom_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve ordered message history for a conversation."""
    with get_db(custom_path) as conn:
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
    user_content: str,
    model_content: str,
    custom_path: Optional[str] = None
) -> str:
    """Atomically record a user message and model response turn."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db(custom_path) as conn:
        cursor = conn.execute("SELECT id, title FROM conversations WHERE id = ?", (conv_id,))
        row = cursor.fetchone()
        if not row:
            title = generate_smart_title(user_content)
            conn.execute(
                "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (conv_id, title, now_iso, now_iso)
            )
        else:
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

def db_rename_conversation(conv_id: str, new_title: str, custom_path: Optional[str] = None) -> bool:
    """Update a conversation title."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db(custom_path) as conn:
        cursor = conn.execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
            (new_title, now_iso, conv_id)
        )
        return cursor.rowcount > 0

def db_delete_conversation(conv_id: str, custom_path: Optional[str] = None) -> bool:
    """Delete a conversation and its messages via cascade delete."""
    with get_db(custom_path) as conn:
        cursor = conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
        return cursor.rowcount > 0

def db_search_conversations(query: str, custom_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Search conversations by title or message content."""
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
            WHERE c.title LIKE ? OR m.content LIKE ?
            GROUP BY c.id
            ORDER BY c.updated_at DESC
        """, (pattern, pattern))
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

def db_delete_last_model_message(conv_id: str, custom_path: Optional[str] = None) -> Optional[Tuple[str, List[Dict[str, Any]]]]:
    """
    Remove the last model message for regeneration.
    Returns (last_user_prompt, previous_history_messages) or None.
    """
    with get_db(custom_path) as conn:
        cursor = conn.execute(
            "SELECT id, role, content, created_at FROM messages WHERE conversation_id = ? ORDER BY id ASC",
            (conv_id,)
        )
        all_msgs = [dict(r) for r in cursor.fetchall()]
        if not all_msgs:
            return None
        
        # If the last message is model, remove it
        if all_msgs[-1]["role"] == "model":
            model_msg_id = all_msgs[-1]["id"]
            conn.execute("DELETE FROM messages WHERE id = ?", (model_msg_id,))
            all_msgs.pop()
        
        # Now find the last user message
        if not all_msgs or all_msgs[-1]["role"] != "user":
            return None
        
        last_user_prompt = all_msgs[-1]["content"]
        # History prior to this user prompt
        prior_history = [
            {"role": m["role"], "content": m["content"]}
            for m in all_msgs[:-1]
        ]
        return last_user_prompt, prior_history

def db_add_model_reply(conv_id: str, reply_text: str, custom_path: Optional[str] = None) -> None:
    """Append a model reply to an existing conversation (used after regeneration)."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db(custom_path) as conn:
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, 'model', ?, ?)",
            (conv_id, reply_text, now_iso)
        )
        conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now_iso, conv_id))

# ---------------------------------------------------------------------------
# In-Memory Backward Compatibility Store (Mirrored with DB)
# ---------------------------------------------------------------------------
conversations_store: Dict[str, List[Dict[str, Any]]] = {}
store_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Flask Application Setup & Initialization
# ---------------------------------------------------------------------------
app = Flask(__name__)

# Initialize the SQLite database schema
init_db()

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

    Strategy:
    1. Combines previous conversation history with the new user message.
    2. Enforces the max_messages limit (keeping the most recent turns).
    3. Guarantees that the conversation starts with a valid 'user' message.
       If trimming leaves a leading 'model' turn, that turn is dropped.
    4. Guarantees the conversation ends with the new user message.
    5. Converts valid turns into Google GenAI `types.Content` objects.
    """
    # Create the complete candidate sequence
    candidate_messages: List[Dict[str, str]] = [
        {"role": msg["role"], "content": msg["content"]}
        for msg in history
        if msg.get("role") in ("user", "model") and msg.get("content")
    ]
    candidate_messages.append({"role": "user", "content": new_user_message})

    # Keep only the latest max_messages
    if len(candidate_messages) > max_messages:
        candidate_messages = candidate_messages[-max_messages:]

    # Gemini multi-turn histories must start with a 'user' turn
    while candidate_messages and candidate_messages[0]["role"] != "user":
        candidate_messages.pop(0)

    # Ensure there is at least the current user message
    if not candidate_messages:
        candidate_messages = [{"role": "user", "content": new_user_message}]

    # Ensure alternating roles by merging adjacent messages with identical roles
    merged_messages: List[Dict[str, str]] = []
    for msg in candidate_messages:
        if merged_messages and merged_messages[-1]["role"] == msg["role"]:
            merged_messages[-1]["content"] += "\n\n" + msg["content"]
        else:
            merged_messages.append({"role": msg["role"], "content": msg["content"]})

    # Ensure final message is the user's message
    if merged_messages[-1]["role"] != "user":
        merged_messages.append({"role": "user", "content": new_user_message})

    # Convert to Google GenAI Content objects
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
    Execute a call to the Google Gemini API using the official google-genai SDK.
    Includes automatic fallback to alternative flash models if the configured model is not found (404)
    or overloaded (503).
    
    Raises:
        ValueError: If response is empty or filtered.
        genai_errors.APIError: If Gemini API returns an error.
        Exception: On network, timeout, or unexpected errors.
    """
    # Convert timeout from seconds to milliseconds for Google GenAI HttpOptions
    timeout_ms = int(timeout * 1000) if timeout else 30000
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=timeout_ms)
    )

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        temperature=0.7,
    )

    # Candidate models to try: specified model first, followed by fallbacks
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

            # If text is empty, inspect candidate finish reasons
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
            # If the model was not found (404) or experiencing temporary spikes (503), try the next model
            if getattr(ae, "code", None) in (404, 503):
                logger.warning("Model '%s' returned %s. Trying fallback...", current_model, getattr(ae, "code", None))
                continue
            # For other API errors (e.g., 401 auth, 429 quota), raise immediately
            raise ae

    if last_api_error:
        raise last_api_error
    raise ValueError("All candidate Gemini models failed to generate a response.")

# ---------------------------------------------------------------------------
# Routes: Core & UI
# ---------------------------------------------------------------------------

@app.route("/", methods=["GET"])
def index():
    """Serve the main chatbot interface."""
    return render_template("index.html")

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
        "version": "2.0.0",
        "model": get_gemini_model(),
        "database": db_status
    }), 200

# ---------------------------------------------------------------------------
# Routes: Conversations Management
# ---------------------------------------------------------------------------

@app.route("/conversations", methods=["GET"])
def list_conversations():
    """List all saved conversations ordered by recent activity."""
    try:
        conversations = db_list_conversations()
        return jsonify({"conversations": conversations}), 200
    except Exception as exc:
        logger.error("Failed to list conversations: %s", exc)
        return jsonify({"error": "Failed to retrieve conversation history."}), 500

@app.route("/conversations/search", methods=["GET"])
def search_conversations():
    """Search conversations by title or message content."""
    query = request.args.get("q", "").strip()
    try:
        if not query:
            results = db_list_conversations()
        else:
            results = db_search_conversations(query)
        return jsonify({
            "query": query,
            "conversations": results
        }), 200
    except Exception as exc:
        logger.error("Failed to search conversations: %s", exc)
        return jsonify({"error": "Failed to search conversation history."}), 500

@app.route("/conversations/<conv_id>", methods=["GET"])
def get_conversation_detail(conv_id: str):
    """Retrieve full details and messages for a specific conversation."""
    try:
        conv = db_get_conversation(conv_id)
        if not conv:
            return jsonify({"error": "Conversation not found."}), 404
        messages = db_get_messages(conv_id)
        return jsonify({
            "conversation": conv,
            "messages": messages
        }), 200
    except Exception as exc:
        logger.error("Failed to retrieve conversation %s: %s", conv_id, exc)
        return jsonify({"error": "Failed to retrieve conversation."}), 500

@app.route("/conversations/<conv_id>", methods=["PATCH"])
def rename_conversation(conv_id: str):
    """Rename a conversation title."""
    if not request.is_json:
        return jsonify({"error": "Request body must be valid JSON."}), 400

    try:
        data = request.get_json(silent=False) or {}
    except Exception:
        return jsonify({"error": "Malformed JSON in request payload."}), 400

    title = data.get("title")
    if not title or not isinstance(title, str) or not title.strip():
        return jsonify({"error": "'title' field is required and cannot be empty."}), 400

    clean_title = title.strip()
    try:
        updated = db_rename_conversation(conv_id, clean_title)
        if not updated:
            return jsonify({"error": "Conversation not found."}), 404
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
    """Delete a conversation and its messages."""
    try:
        deleted = db_delete_conversation(conv_id)
        if not deleted:
            return jsonify({"error": "Conversation not found."}), 404
        
        # Also clean up backward compatibility store
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
# Route: Chat with Multi-turn Memory & Regeneration
# ---------------------------------------------------------------------------

@app.route("/chat", methods=["POST"])
def chat():
    """
    Process user chat messages with persistent multi-turn conversation memory.
    
    Accepts JSON:
        {
            "message": "User question or prompt",
            "conversation_id": "Optional unique conversation ID",
            "regenerate": false  (optional: if true, regenerates the last AI reply)
        }
        
    Returns JSON:
        Success (200):
            {"reply": "Model response", "conversation_id": "...", "title": "..."}
        Error (400, 401, 429, 503, 504, 500):
            {"error": "User-friendly error explanation"}
    """
    # 1. Validate Content-Type and JSON structure
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

    if is_regenerate:
        # Regeneration mode: re-run the last user prompt
        if not raw_conv_id or not isinstance(raw_conv_id, str) or not raw_conv_id.strip():
            return jsonify({"error": "Missing conversation_id for regeneration."}), 400
        conversation_id = raw_conv_id.strip()

        regen_data = db_delete_last_model_message(conversation_id)
        if not regen_data:
            return jsonify({"error": "No previous user turn available to regenerate."}), 400

        user_message, history_messages = regen_data
        
        # Also sync in-memory backward compatibility store
        with store_lock:
            if conversation_id in conversations_store and conversations_store[conversation_id]:
                if conversations_store[conversation_id][-1]["role"] == "model":
                    conversations_store[conversation_id].pop()
    else:
        # Standard chat message mode
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

        # Retrieve prior history from SQLite (fallback to memory if not yet persisted)
        db_msgs = db_get_messages(conversation_id)
        if db_msgs:
            history_messages = [{"role": m["role"], "content": m["content"]} for m in db_msgs]
        else:
            with store_lock:
                history_messages = list(conversations_store.get(conversation_id, []))

    # 2. Check API Key configuration
    api_key = get_gemini_api_key()
    if not api_key:
        logger.error("Request rejected: GEMINI_API_KEY is not configured or is placeholder.")
        return jsonify({
            "error": "Gemini API key is not configured. Please set your GEMINI_API_KEY in the .env file or environment variables to start chatting with StudyBuddy AI."
        }), 503

    model_name = get_gemini_model()
    timeout = get_gemini_timeout()

    # 3. Apply context window management strategy (max 12 messages, starting with user)
    contents = manage_context_window(history_messages, user_message, max_messages=MAX_HISTORY_MESSAGES)

    # 4. Call Gemini API
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

    # 5. Persist turn ONLY on successful completion (Rollback invariant maintained)
    now_iso = datetime.now(timezone.utc).isoformat()
    if is_regenerate:
        db_add_model_reply(conversation_id, reply_text)
        conv = db_get_conversation(conversation_id)
        conv_title = conv["title"] if conv else "Study Session"
    else:
        conv_title = db_save_turn(conversation_id, user_message, reply_text)

    # Sync in-memory store for backward compatibility
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

    logger.info("Successfully processed message for conversation_id=%s (title='%s')", conversation_id, conv_title)
    return jsonify({
        "reply": reply_text,
        "conversation_id": conversation_id,
        "title": conv_title
    }), 200

# ---------------------------------------------------------------------------
# CLI / Development Server Runner
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Note: On macOS, port 5000 is often reserved by AirPlay Receiver (ControlCenter).
    # Defaulting to 5001 ensures smooth operation out-of-the-box on Mac.
    port = int(os.getenv("FLASK_PORT", 5001))
    debug = os.getenv("FLASK_DEBUG", "False").lower() in ("true", "1", "yes")
    print(f"Starting StudyBuddy AI server on http://127.0.0.1:{port} (Debug: {debug})...")
    app.run(host="0.0.0.0", port=port, debug=debug)
