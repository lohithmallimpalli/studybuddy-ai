"""StudyBuddy AI - Backend Flask Application.

This module implements a multi-turn AI chatbot application using Flask and the
official Google GenAI Python SDK (`google-genai`).

Endpoints:
    - GET /: Serves the web-based chat interface.
    - GET /health: Health check endpoint.
    - POST /chat: Handles user messages, multi-turn conversation memory,
                  context window management, and Gemini API calls.
"""

import os
import re
import uuid
import logging
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any

from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv

# Import official Google GenAI SDK
from google import genai
from google.genai import types
from google.genai import errors as genai_errors

# Load environment variables from .env file
load_dotenv()

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
DEFAULT_MODEL: str = "gemini-2.5-flash"
DEFAULT_TIMEOUT_SECONDS: float = 30.0

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
# In-Memory Conversation Storage
# Note: Conversations are stored in memory and will reset if the server restarts.
# A threading.Lock ensures thread-safe concurrent access.
# ---------------------------------------------------------------------------
conversations_store: Dict[str, List[Dict[str, Any]]] = {}
store_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Flask Application Setup
# ---------------------------------------------------------------------------
app = Flask(__name__)

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

# Known standard Gemini models in priority order for fallback
FALLBACK_MODELS = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]

def call_gemini_api(
    contents: List[types.Content],
    api_key: str,
    model_name: str,
    timeout: float
) -> str:
    """
    Execute a call to the Google Gemini API using the official google-genai SDK.
    Includes automatic fallback to alternative flash models if the configured model is not found.
    
    Raises:
        ValueError: If response is empty or filtered.
        genai_errors.APIError: If Gemini API returns an error.
        Exception: On network, timeout, or unexpected errors.
    """
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=timeout)
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
            # If the model was not found (404), try the next model in models_to_try
            if getattr(ae, "code", None) == 404:
                logger.warning("Model '%s' returned 404 Not Found. Trying fallback...", current_model)
                continue
            # For other API errors (e.g., 401 auth, 429 quota), raise immediately
            raise ae

    if last_api_error:
        raise last_api_error
    raise ValueError("All candidate Gemini models failed to generate a response.")

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/", methods=["GET"])
def index():
    """Serve the main chatbot interface."""
    return render_template("index.html")

@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint indicating service status."""
    return jsonify({
        "status": "ok",
        "app": "StudyBuddy AI",
        "version": "1.0.0",
        "model": get_gemini_model()
    }), 200

@app.route("/chat", methods=["POST"])
def chat():
    """
    Process user chat messages with multi-turn conversation memory.
    
    Accepts JSON:
        {
            "message": "User question or prompt",
            "conversation_id": "Optional unique conversation ID"
        }
        
    Returns JSON:
        Success (200):
            {"reply": "Model response", "conversation_id": "..."}
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

    # 2. Validate user message
    raw_message = data.get("message")
    if raw_message is None:
        return jsonify({"error": "Missing required 'message' field."}), 400
    if not isinstance(raw_message, str):
        return jsonify({"error": "'message' field must be a string."}), 400
    
    message = raw_message.strip()
    if not message:
        return jsonify({"error": "Message cannot be empty."}), 400

    # 3. Retrieve or generate conversation_id
    raw_conv_id = data.get("conversation_id")
    if raw_conv_id and isinstance(raw_conv_id, str) and raw_conv_id.strip():
        conversation_id = raw_conv_id.strip()
    else:
        conversation_id = str(uuid.uuid4())

    # 4. Check API Key configuration
    api_key = get_gemini_api_key()
    if not api_key:
        logger.error("Request rejected: GEMINI_API_KEY is not configured or is placeholder.")
        return jsonify({
            "error": "Gemini API key is not configured. Please set your GEMINI_API_KEY in the .env file or environment variables to start chatting with StudyBuddy AI."
        }), 503

    model_name = get_gemini_model()
    timeout = get_gemini_timeout()

    # 5. Retrieve existing conversation history (isolated by conversation_id)
    with store_lock:
        existing_history = list(conversations_store.get(conversation_id, []))

    # 6. Apply context window management strategy (max 12 messages, starting with user)
    contents = manage_context_window(existing_history, message, max_messages=MAX_HISTORY_MESSAGES)

    # 7. Call Gemini API
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

    # 8. Persist turn ONLY on successful completion (Rollback invariant maintained)
    now_iso = datetime.now(timezone.utc).isoformat()
    with store_lock:
        if conversation_id not in conversations_store:
            conversations_store[conversation_id] = []
        
        conversations_store[conversation_id].append({
            "role": "user",
            "content": message,
            "timestamp": now_iso
        })
        conversations_store[conversation_id].append({
            "role": "model",
            "content": reply_text,
            "timestamp": now_iso
        })
        
        # Keep maximum 50 messages total per conversation in memory to avoid memory leaks
        if len(conversations_store[conversation_id]) > 50:
            conversations_store[conversation_id] = conversations_store[conversation_id][-50:]

    logger.info("Successfully processed message for conversation_id=%s", conversation_id)
    return jsonify({
        "reply": reply_text,
        "conversation_id": conversation_id
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
