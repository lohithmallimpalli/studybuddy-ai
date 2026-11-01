"""Automated Test Suite for StudyBuddy AI.

This module tests:
1. Health and index endpoints (with database status)
2. Request validation and error handling for /chat
3. Conversation ID generation, session preservation, and auto-titling
4. Multi-turn context management and alternating turn sequencing
5. Conversation isolation across separate conversation IDs in SQLite
6. History rollback when API calls fail
7. Full CRUD endpoints for conversations:
   - GET /conversations (list)
   - GET /conversations/<id> (details & messages)
   - PATCH /conversations/<id> (rename)
   - DELETE /conversations/<id> (delete & cascade)
   - GET /conversations/search (search by title and message content)
8. Response regeneration endpoint
9. Mocked 5-turn conversation sequence
10. Live Gemini API integration (executed when valid key is present)
"""

import os
import pytest
from unittest.mock import patch, MagicMock
from app import (
    app,
    conversations_store,
    store_lock,
    manage_context_window,
    init_db,
    db_list_conversations,
    db_get_conversation,
    db_get_messages,
)
from google.genai import types
from google.genai import errors as genai_errors


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Create a Flask test client with an isolated temporary SQLite database."""
    app.config["TESTING"] = True
    test_db = str(tmp_path / "test_studybuddy.db")
    monkeypatch.setattr("app.DB_PATH", test_db)
    init_db(test_db)
    
    with store_lock:
        conversations_store.clear()
        
    with app.test_client() as test_client:
        yield test_client
        
    with store_lock:
        conversations_store.clear()


# ---------------------------------------------------------------------------
# Endpoint & Health Tests
# ---------------------------------------------------------------------------

def test_health_endpoint(client):
    """Verify that GET /health returns 200 with service and database status."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "ok"
    assert data["app"] == "StudyBuddy AI"
    assert "version" in data
    assert "model" in data
    assert data["database"] == "ok"


def test_index_endpoint(client):
    """Verify that GET / renders the main HTML interface with required UI elements."""
    response = client.get("/")
    assert response.status_code == 200
    html = response.data
    assert b"StudyBuddy AI" in html
    assert b"Welcome to StudyBuddy AI" in html
    assert b"Explain Big-O Notation" in html
    assert b"Learn Python Programming" in html
    assert b"sidebar" in html


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
    """Verify POST /chat rejects JSON missing the 'message' field when not regenerating."""
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

def test_chat_generates_conversation_id_and_title(client, monkeypatch):
    """Verify that omitting conversation_id generates a UUID and auto-generates title in SQLite."""
    monkeypatch.setenv("GEMINI_API_KEY", "dummy_test_key_for_mock")
    with patch("app.call_gemini_api", return_value="Hello, student!"):
        response = client.post("/chat", json={"message": "What is Python list comprehension?"})
        assert response.status_code == 200
        data = response.get_json()
        assert "conversation_id" in data
        assert len(data["conversation_id"]) > 10
        assert data["reply"] == "Hello, student!"
        assert "title" in data
        assert "Python" in data["title"]


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
    history = []
    for i in range(7):
        history.append({"role": "user", "content": f"User question {i}"})
        history.append({"role": "model", "content": f"AI answer {i}"})

    new_msg = "Latest user question"
    contents = manage_context_window(history, new_msg, max_messages=12)

    assert len(contents) <= 12
    assert contents[0].role == "user"
    assert contents[-1].role == "user"
    assert contents[-1].parts[0].text == new_msg


def test_manage_context_window_merges_adjacent_same_role():
    """Verify that adjacent same-role messages are merged into valid alternating sequences."""
    history = [
        {"role": "user", "content": "Question 1"},
        {"role": "user", "content": "Question 1 follow-up"},
        {"role": "model", "content": "Answer 1"},
        {"role": "model", "content": "Answer 1 extra note"},
    ]
    new_msg = "Question 2"
    contents = manage_context_window(history, new_msg)

    roles = [c.role for c in contents]
    assert roles == ["user", "model", "user"]
    assert "follow-up" in contents[0].parts[0].text
    assert "extra note" in contents[1].parts[0].text
    assert contents[2].parts[0].text == "Question 2"


def test_conversation_isolation_in_sqlite(client, monkeypatch):
    """Verify that different conversation IDs maintain isolated histories in SQLite."""
    monkeypatch.setenv("GEMINI_API_KEY", "dummy_test_key_for_mock")

    with patch("app.call_gemini_api") as mock_api:
        mock_api.side_effect = lambda contents, *args: f"Echo: {contents[-1].parts[0].text}"

        res_a = client.post("/chat", json={"message": "I love Python", "conversation_id": "conv-A"})
        assert res_a.status_code == 200

        res_b = client.post("/chat", json={"message": "I love Rust", "conversation_id": "conv-B"})
        assert res_b.status_code == 200

        msgs_a = db_get_messages("conv-A")
        assert len(msgs_a) == 2
        assert msgs_a[0]["content"] == "I love Python"

        msgs_b = db_get_messages("conv-B")
        assert len(msgs_b) == 2
        assert msgs_b[0]["content"] == "I love Rust"


def test_api_rollback_on_failure(client, monkeypatch):
    """Verify that failed API calls do not leave corrupted messages in SQLite or memory."""
    monkeypatch.setenv("GEMINI_API_KEY", "dummy_test_key_for_mock")
    conv_id = "rollback-test-conv"

    with patch("app.call_gemini_api", side_effect=TimeoutError("Request timed out")):
        response = client.post("/chat", json={"message": "Will fail", "conversation_id": conv_id})
        assert response.status_code == 504
        assert "timed out" in response.get_json()["error"]

    msgs = db_get_messages(conv_id)
    assert len(msgs) == 0


# ---------------------------------------------------------------------------
# Conversation CRUD & Search Endpoints
# ---------------------------------------------------------------------------

def test_list_and_detail_conversations(client, monkeypatch):
    """Verify GET /conversations and GET /conversations/<id>."""
    monkeypatch.setenv("GEMINI_API_KEY", "dummy_test_key_for_mock")
    with patch("app.call_gemini_api", return_value="Binary search is O(log n)."):
        client.post("/chat", json={"message": "Explain binary search", "conversation_id": "c-101"})

    # List conversations
    res_list = client.get("/conversations")
    assert res_list.status_code == 200
    data = res_list.get_json()
    assert "conversations" in data
    assert len(data["conversations"]) == 1
    assert data["conversations"][0]["id"] == "c-101"
    assert data["conversations"][0]["message_count"] == 2

    # Detail conversation
    res_detail = client.get("/conversations/c-101")
    assert res_detail.status_code == 200
    detail = res_detail.get_json()
    assert detail["conversation"]["id"] == "c-101"
    assert len(detail["messages"]) == 2
    assert detail["messages"][0]["role"] == "user"
    assert detail["messages"][1]["role"] == "model"


def test_get_conversation_not_found(client):
    """Verify GET /conversations/<id> returns 404 for unknown ID."""
    res = client.get("/conversations/non-existent-id")
    assert res.status_code == 404
    assert "not found" in res.get_json()["error"].lower()


def test_rename_conversation(client, monkeypatch):
    """Verify PATCH /conversations/<id> updates conversation title."""
    monkeypatch.setenv("GEMINI_API_KEY", "dummy_test_key_for_mock")
    with patch("app.call_gemini_api", return_value="OK"):
        client.post("/chat", json={"message": "Initial topic", "conversation_id": "c-rename"})

    patch_res = client.patch(
        "/conversations/c-rename",
        json={"title": "Updated Master Topic"}
    )
    assert patch_res.status_code == 200
    data = patch_res.get_json()
    assert data["title"] == "Updated Master Topic"

    # Verify updated in DB
    conv = db_get_conversation("c-rename")
    assert conv["title"] == "Updated Master Topic"


def test_rename_conversation_validation(client):
    """Verify PATCH /conversations/<id> rejects empty title and missing record."""
    res_empty = client.patch("/conversations/c-dummy", json={"title": "   "})
    assert res_empty.status_code == 400

    res_404 = client.patch("/conversations/c-not-found", json={"title": "New Title"})
    assert res_404.status_code == 404


def test_delete_conversation(client, monkeypatch):
    """Verify DELETE /conversations/<id> deletes record and messages from SQLite."""
    monkeypatch.setenv("GEMINI_API_KEY", "dummy_test_key_for_mock")
    with patch("app.call_gemini_api", return_value="OK"):
        client.post("/chat", json={"message": "Topic to delete", "conversation_id": "c-del"})

    del_res = client.delete("/conversations/c-del")
    assert del_res.status_code == 200

    # Ensure removed
    assert db_get_conversation("c-del") is None
    assert len(db_get_messages("c-del")) == 0

    # Delete again returns 404
    del_res2 = client.delete("/conversations/c-del")
    assert del_res2.status_code == 404


def test_search_conversations(client, monkeypatch):
    """Verify GET /conversations/search matches by title or message content."""
    monkeypatch.setenv("GEMINI_API_KEY", "dummy_test_key_for_mock")
    with patch("app.call_gemini_api", return_value="Data structures are fundamental."):
        client.post("/chat", json={"message": "Discuss binary trees", "conversation_id": "c-trees"})

    with patch("app.call_gemini_api", return_value="PyTorch tensors are multidimensional."):
        client.post("/chat", json={"message": "Explain deep learning tensors", "conversation_id": "c-dl"})

    # Search for "binary"
    search_trees = client.get("/conversations/search?q=binary")
    assert search_trees.status_code == 200
    results = search_trees.get_json()["conversations"]
    assert len(results) == 1
    assert results[0]["id"] == "c-trees"

    # Search for "tensors" (matches message content)
    search_dl = client.get("/conversations/search?q=tensors")
    assert search_dl.status_code == 200
    results_dl = search_dl.get_json()["conversations"]
    assert len(results_dl) == 1
    assert results_dl[0]["id"] == "c-dl"


def test_regenerate_response(client, monkeypatch):
    """Verify POST /chat with regenerate=True replaces the last AI turn."""
    monkeypatch.setenv("GEMINI_API_KEY", "dummy_test_key_for_mock")
    conv_id = "c-regen-test"

    # Turn 1
    with patch("app.call_gemini_api", return_value="First AI response"):
        client.post("/chat", json={"message": "Tell me a joke", "conversation_id": conv_id})

    msgs1 = db_get_messages(conv_id)
    assert len(msgs1) == 2
    assert msgs1[1]["content"] == "First AI response"

    # Regenerate Turn 1
    with patch("app.call_gemini_api", return_value="Second regenerated AI response"):
        regen_res = client.post("/chat", json={"conversation_id": conv_id, "regenerate": True})
        assert regen_res.status_code == 200
        assert regen_res.get_json()["reply"] == "Second regenerated AI response"

    msgs2 = db_get_messages(conv_id)
    # Total messages should still be 2 (1 user, 1 regenerated model reply)
    assert len(msgs2) == 2
    assert msgs2[1]["content"] == "Second regenerated AI response"


# ---------------------------------------------------------------------------
# Five-Turn Memory Test (Mocked Automated Verification)
# ---------------------------------------------------------------------------

def test_five_turn_conversation_flow_mocked(client, monkeypatch):
    """
    Automated mock verification of the required 5-turn conversation sequence
    with persistent SQLite storage.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "dummy_test_key_for_mock")
    conv_id = "test-five-turn-session"

    def mock_gemini_behavior(contents, *args):
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
        t1 = client.post("/chat", json={"message": "My name is Rahul, and I am learning Python.", "conversation_id": conv_id})
        assert t1.status_code == 200

        t2 = client.post("/chat", json={"message": "I am a beginner in programming.", "conversation_id": conv_id})
        assert t2.status_code == 200

        t3 = client.post("/chat", json={"message": "I want to build AI projects using Python.", "conversation_id": conv_id})
        assert t3.status_code == 200

        t4 = client.post("/chat", json={"message": "What is my name, and which programming language am I learning?", "conversation_id": conv_id})
        assert t4.status_code == 200
        reply4 = t4.get_json()["reply"]
        assert "Rahul" in reply4 and "Python" in reply4

        t5 = client.post("/chat", json={"message": "What kind of projects did I say I wanted to build?", "conversation_id": conv_id})
        assert t5.status_code == 200
        reply5 = t5.get_json()["reply"]
        assert "AI projects" in reply5

    # Check SQLite database has 10 total messages (5 user + 5 model)
    msgs = db_get_messages(conv_id)
    assert len(msgs) == 10


# ---------------------------------------------------------------------------
# Real Gemini API Test (Skipped when no live key is configured)
# ---------------------------------------------------------------------------

def test_real_gemini_api_call(client):
    """Live test against Google Gemini API."""
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key or key == "your_gemini_api_key_here":
        pytest.skip("GEMINI_API_KEY is not set. Skipping real API test.")

    response = client.post("/chat", json={"message": "Hello! Reply with 'StudyBuddy Active'."})
    assert response.status_code == 200
    data = response.get_json()
    assert "reply" in data
    assert len(data["reply"]) > 0
