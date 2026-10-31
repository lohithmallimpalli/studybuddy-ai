"""Automated Test Suite for StudyBuddy AI.

This module tests:
1. Health and index endpoints
2. Request validation and error handling for /chat
3. Conversation ID generation and preservation
4. Multi-turn context management and turn sequencing
5. Conversation isolation across separate conversation IDs
6. History rollback when API calls fail
7. Mocked 5-turn conversation sequence
8. Optional live Gemini API integration (executed only when a valid key is present)
"""

import os
import pytest
from unittest.mock import patch, MagicMock
from app import app, conversations_store, store_lock, manage_context_window
from google.genai import types
from google.genai import errors as genai_errors


@pytest.fixture
def client():
    """Create a Flask test client and reset conversation store before each test."""
    app.config["TESTING"] = True
    with store_lock:
        conversations_store.clear()
    with app.test_client() as client:
        yield client
    with store_lock:
        conversations_store.clear()


# ---------------------------------------------------------------------------
# Endpoint & Health Tests
# ---------------------------------------------------------------------------

def test_health_endpoint(client):
    """Verify that GET /health returns 200 with service information."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "ok"
    assert data["app"] == "StudyBuddy AI"
    assert "version" in data
    assert "model" in data


def test_index_endpoint(client):
    """Verify that GET / renders the main HTML interface."""
    response = client.get("/")
    assert response.status_code == 200
    assert b"StudyBuddy AI" in response.data
    assert b"Your Personal AI Study Assistant" in response.data


# ---------------------------------------------------------------------------
# Input Validation Tests for POST /chat
# ---------------------------------------------------------------------------

def test_chat_rejects_non_json(client):
    """Verify POST /chat rejects non-JSON requests with 400 Bad Request."""
    response = client.post("/chat", data="not a json", content_type="text/plain")
    assert response.status_code == 400
    data = response.get_json()
    assert "error" in data


def test_chat_rejects_missing_message_field(client):
    """Verify POST /chat rejects JSON missing the 'message' field."""
    response = client.post("/chat", json={"conversation_id": "test-123"})
    assert response.status_code == 400
    data = response.get_json()
    assert "Missing required 'message' field" in data["error"]


def test_chat_rejects_empty_message(client):
    """Verify POST /chat rejects whitespace-only or empty strings."""
    response = client.post("/chat", json={"message": "   "})
    assert response.status_code == 400
    data = response.get_json()
    assert "Message cannot be empty" in data["error"]


def test_chat_rejects_non_string_message(client):
    """Verify POST /chat rejects non-string message types."""
    response = client.post("/chat", json={"message": 9999})
    assert response.status_code == 400
    data = response.get_json()
    assert "'message' field must be a string" in data["error"]


# ---------------------------------------------------------------------------
# API Key Verification
# ---------------------------------------------------------------------------

def test_chat_missing_api_key_returns_503(client, monkeypatch):
    """Verify that missing or placeholder API key returns 503 Service Unavailable."""
    monkeypatch.setenv("GEMINI_API_KEY", "your_gemini_api_key_here")
    response = client.post("/chat", json={"message": "Hello"})
    assert response.status_code == 503
    data = response.get_json()
    assert "Gemini API key is not configured" in data["error"]


# ---------------------------------------------------------------------------
# Conversation ID & Session Handling
# ---------------------------------------------------------------------------

def test_chat_generates_conversation_id_if_omitted(client, monkeypatch):
    """Verify that omitting conversation_id generates a valid UUID identifier."""
    monkeypatch.setenv("GEMINI_API_KEY", "dummy_test_key_for_mock")
    with patch("app.call_gemini_api", return_value="Hello, student!"):
        response = client.post("/chat", json={"message": "Hello"})
        assert response.status_code == 200
        data = response.get_json()
        assert "conversation_id" in data
        assert len(data["conversation_id"]) > 10
        assert data["reply"] == "Hello, student!"


def test_chat_preserves_supplied_conversation_id(client, monkeypatch):
    """Verify that a supplied conversation_id is preserved throughout the session."""
    monkeypatch.setenv("GEMINI_API_KEY", "dummy_test_key_for_mock")
    conv_id = "test-session-custom-uuid-42"
    with patch("app.call_gemini_api", return_value="Response"):
        response = client.post("/chat", json={"message": "Hello", "conversation_id": conv_id})
        assert response.status_code == 200
        data = response.get_json()
        assert data["conversation_id"] == conv_id


# ---------------------------------------------------------------------------
# Context Management & Conversation Isolation Tests
# ---------------------------------------------------------------------------

def test_manage_context_window_truncation_and_roles():
    """Verify context window enforces 12 messages limit and valid user/model sequencing."""
    # Create 14 simulated messages (7 user, 7 model)
    history = []
    for i in range(7):
        history.append({"role": "user", "content": f"User question {i}"})
        history.append({"role": "model", "content": f"AI answer {i}"})

    new_msg = "Latest user question"
    contents = manage_context_window(history, new_msg, max_messages=12)

    # Must not exceed 12 messages
    assert len(contents) <= 12

    # First turn must always be 'user'
    assert contents[0].role == "user"

    # Last turn must be 'user' with the latest message
    assert contents[-1].role == "user"
    assert contents[-1].parts[0].text == new_msg


def test_conversation_isolation(client, monkeypatch):
    """Verify that different conversation IDs maintain isolated message histories."""
    monkeypatch.setenv("GEMINI_API_KEY", "dummy_test_key_for_mock")

    with patch("app.call_gemini_api") as mock_api:
        mock_api.side_effect = lambda contents, *args: f"Echo: {contents[-1].parts[0].text}"

        # Conversation A: Turn 1
        res_a = client.post("/chat", json={"message": "I love Python", "conversation_id": "conv-A"})
        assert res_a.status_code == 200
        assert res_a.get_json()["reply"] == "Echo: I love Python"

        # Conversation B: Turn 1
        res_b = client.post("/chat", json={"message": "I love Rust", "conversation_id": "conv-B"})
        assert res_b.status_code == 200
        assert res_b.get_json()["reply"] == "Echo: I love Rust"

        # Verify backend storage separation
        with store_lock:
            assert len(conversations_store["conv-A"]) == 2
            assert conversations_store["conv-A"][0]["content"] == "I love Python"

            assert len(conversations_store["conv-B"]) == 2
            assert conversations_store["conv-B"][0]["content"] == "I love Rust"


def test_api_rollback_on_failure(client, monkeypatch):
    """Verify that failed API calls do not leave corrupted or partial messages in history."""
    monkeypatch.setenv("GEMINI_API_KEY", "dummy_test_key_for_mock")
    conv_id = "rollback-test-conv"

    with patch("app.call_gemini_api", side_effect=TimeoutError("Request timed out")):
        response = client.post("/chat", json={"message": "Will fail", "conversation_id": conv_id})
        assert response.status_code == 504
        assert "timed out" in response.get_json()["error"]

    # In-memory store must have no entries for this conversation
    with store_lock:
        assert conv_id not in conversations_store or len(conversations_store[conv_id]) == 0


# ---------------------------------------------------------------------------
# Five-Turn Memory Test (Mocked Automated Verification)
# ---------------------------------------------------------------------------

def test_five_turn_conversation_flow_mocked(client, monkeypatch):
    """
    Automated mock verification of the required 5-turn conversation sequence:
    Turn 1: 'My name is Rahul, and I am learning Python.'
    Turn 2: 'I am a beginner in programming.'
    Turn 3: 'I want to build AI projects using Python.'
    Turn 4: 'What is my name, and which programming language am I learning?' -> Expects 'Rahul and Python'
    Turn 5: 'What kind of projects did I say I wanted to build?' -> Expects 'AI projects using Python'
    """
    monkeypatch.setenv("GEMINI_API_KEY", "dummy_test_key_for_mock")
    conv_id = "test-five-turn-session"

    def mock_gemini_behavior(contents, *args):
        # Extract full conversation text to verify context was provided
        history_text = " ".join([p.text for c in contents for p in c.parts])

        last_user_msg = contents[-1].parts[0].text
        if "What is my name" in last_user_msg:
            assert "Rahul" in history_text, "Context should contain Rahul from Turn 1"
            assert "Python" in history_text, "Context should contain Python from Turn 1"
            return "Your name is Rahul, and you are learning Python!"
        elif "What kind of projects" in last_user_msg:
            assert "AI projects" in history_text, "Context should contain AI projects from Turn 3"
            return "You mentioned that you want to build AI projects using Python."
        return f"Acknowledged: {last_user_msg}"

    with patch("app.call_gemini_api", side_effect=mock_gemini_behavior):
        # Turn 1
        t1 = client.post("/chat", json={"message": "My name is Rahul, and I am learning Python.", "conversation_id": conv_id})
        assert t1.status_code == 200

        # Turn 2
        t2 = client.post("/chat", json={"message": "I am a beginner in programming.", "conversation_id": conv_id})
        assert t2.status_code == 200

        # Turn 3
        t3 = client.post("/chat", json={"message": "I want to build AI projects using Python.", "conversation_id": conv_id})
        assert t3.status_code == 200

        # Turn 4
        t4 = client.post("/chat", json={"message": "What is my name, and which programming language am I learning?", "conversation_id": conv_id})
        assert t4.status_code == 200
        reply4 = t4.get_json()["reply"]
        assert "Rahul" in reply4 and "Python" in reply4

        # Turn 5
        t5 = client.post("/chat", json={"message": "What kind of projects did I say I wanted to build?", "conversation_id": conv_id})
        assert t5.status_code == 200
        reply5 = t5.get_json()["reply"]
        assert "AI projects" in reply5

    # Check store has 10 total messages (5 user + 5 model)
    with store_lock:
        assert len(conversations_store[conv_id]) == 10


# ---------------------------------------------------------------------------
# Real Gemini API Test (Skipped when no live key is configured)
# ---------------------------------------------------------------------------

def test_real_gemini_api_call(client):
    """
    Live test against Google Gemini API.
    Runs ONLY when a genuine GEMINI_API_KEY is provided in the environment.
    """
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key or key == "your_gemini_api_key_here":
        pytest.skip("GEMINI_API_KEY is not set. Skipping real API test.")

    response = client.post("/chat", json={"message": "Hello! Reply with 'StudyBuddy Active'."})
    assert response.status_code == 200
    data = response.get_json()
    assert "reply" in data
    assert len(data["reply"]) > 0
