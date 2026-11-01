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


# ---------------------------------------------------------------------------
# Authentication & Multi-User Platform Tests
# ---------------------------------------------------------------------------

def test_auth_register_success(client):
    """Verify successful user registration and session establishment."""
    payload = {
        "name": "Jane Doe",
        "email": "jane@example.com",
        "password": "securePassword123",
        "confirm_password": "securePassword123"
    }
    res = client.post("/auth/register", json=payload)
    assert res.status_code == 201
    data = res.get_json()
    assert data["status"] == "ok"
    assert data["user"]["name"] == "Jane Doe"
    assert data["user"]["email"] == "jane@example.com"
    assert data["user"]["is_guest"] is False

    # Check /auth/me returns the registered user
    me_res = client.get("/auth/me")
    assert me_res.status_code == 200
    me_data = me_res.get_json()
    assert me_data["user"]["email"] == "jane@example.com"
    assert me_data["user"]["is_guest"] is False


def test_auth_register_validation(client):
    """Verify input validation for registration."""
    # Missing fields
    res = client.post("/auth/register", json={"name": "Alice"})
    assert res.status_code == 400

    # Invalid email
    res = client.post("/auth/register", json={
        "name": "Alice", "email": "invalid-email", "password": "pass123", "confirm_password": "pass123"
    })
    assert res.status_code == 400
    assert "valid email" in res.get_json()["error"]

    # Short password
    res = client.post("/auth/register", json={
        "name": "Alice", "email": "alice@example.com", "password": "123", "confirm_password": "123"
    })
    assert res.status_code == 400
    assert "at least 6 characters" in res.get_json()["error"]

    # Password mismatch
    res = client.post("/auth/register", json={
        "name": "Alice", "email": "alice@example.com", "password": "password1", "confirm_password": "password2"
    })
    assert res.status_code == 400
    assert "do not match" in res.get_json()["error"]


def test_auth_register_duplicate_email(client):
    """Verify registering with an existing email returns 409 Conflict."""
    payload = {
        "name": "Bob",
        "email": "bob@example.com",
        "password": "mypassword123",
        "confirm_password": "mypassword123"
    }
    res1 = client.post("/auth/register", json=payload)
    assert res1.status_code == 201

    res2 = client.post("/auth/register", json=payload)
    assert res2.status_code == 409
    assert "already exists" in res2.get_json()["error"]


def test_auth_login_success_and_invalid(client):
    """Verify login with correct and incorrect credentials."""
    # Register user
    client.post("/auth/register", json={
        "name": "Charlie",
        "email": "charlie@example.com",
        "password": "mypassword123",
        "confirm_password": "mypassword123"
    })

    # Wrong password
    res_wrong_pw = client.post("/auth/login", json={
        "email": "charlie@example.com",
        "password": "wrongpassword"
    })
    assert res_wrong_pw.status_code == 401

    # Unregistered email
    res_no_user = client.post("/auth/login", json={
        "email": "unknown@example.com",
        "password": "mypassword123"
    })
    assert res_no_user.status_code == 401

    # Successful login
    res_ok = client.post("/auth/login", json={
        "email": "charlie@example.com",
        "password": "mypassword123"
    })
    assert res_ok.status_code == 200
    assert res_ok.get_json()["user"]["name"] == "Charlie"


def test_guest_session_provisioning(client):
    """Verify guest session is automatically initialized with usage counters."""
    res = client.get("/auth/me")
    assert res.status_code == 200
    user = res.get_json()["user"]
    assert user["is_guest"] is True
    assert user["name"] == "Guest Student"
    assert user["guest_message_count"] == 0
    assert user["guest_limit"] == 25

    # Provision explicit fresh guest session
    guest_res = client.post("/auth/guest")
    assert guest_res.status_code == 200
    new_guest = guest_res.get_json()["user"]
    assert new_guest["is_guest"] is True
    assert new_guest["id"] != user["id"]


def test_multi_user_data_isolation(client, monkeypatch):
    """Verify strict data isolation: User A cannot see, read, modify or delete User B's conversations."""
    monkeypatch.setenv("GEMINI_API_KEY", "dummy_test_key_for_mock")

    # Client A: register Alice
    client.post("/auth/register", json={
        "name": "Alice User", "email": "alice.iso@example.com", "password": "password123", "confirm_password": "password123"
    })
    with patch("app.call_gemini_api", return_value="Alice response"):
        res_a = client.post("/chat", json={"message": "Alice secret message", "conversation_id": "alice-conv-1"})
        assert res_a.status_code == 200

    # Create Client B: separate session for Bob
    client_b = app.test_client()
    client_b.post("/auth/register", json={
        "name": "Bob User", "email": "bob.iso@example.com", "password": "password123", "confirm_password": "password123"
    })
    with patch("app.call_gemini_api", return_value="Bob response"):
        res_b = client_b.post("/chat", json={"message": "Bob secret message", "conversation_id": "bob-conv-1"})
        assert res_b.status_code == 200

    # Bob's conversation list should ONLY contain Bob's conversation
    b_list = client_b.get("/conversations").get_json()["conversations"]
    b_ids = [c["id"] for c in b_list]
    assert "bob-conv-1" in b_ids
    assert "alice-conv-1" not in b_ids

    # Bob attempting to retrieve Alice's conversation must return 404
    b_get_alice = client_b.get("/conversations/alice-conv-1")
    assert b_get_alice.status_code == 404

    # Bob attempting to rename Alice's conversation must return 404
    b_rename_alice = client_b.patch("/conversations/alice-conv-1", json={"title": "Hacked Title"})
    assert b_rename_alice.status_code == 404

    # Bob attempting to delete Alice's conversation must return 404
    b_delete_alice = client_b.delete("/conversations/alice-conv-1")
    assert b_delete_alice.status_code == 404

    # Alice's conversation is untouched
    a_conv = client.get("/conversations/alice-conv-1")
    assert a_conv.status_code == 200
    assert a_conv.get_json()["conversation"]["id"] == "alice-conv-1"


def test_guest_isolation_between_different_guests(client, monkeypatch):
    """Verify separate guest sessions cannot see or modify each other's conversations."""
    monkeypatch.setenv("GEMINI_API_KEY", "dummy_test_key_for_mock")

    guest_1 = client
    guest_2 = app.test_client()

    with patch("app.call_gemini_api", return_value="Guest 1 answer"):
        res1 = guest_1.post("/chat", json={"message": "Guest 1 topic", "conversation_id": "g1-conv"})
        assert res1.status_code == 200

    with patch("app.call_gemini_api", return_value="Guest 2 answer"):
        res2 = guest_2.post("/chat", json={"message": "Guest 2 topic", "conversation_id": "g2-conv"})
        assert res2.status_code == 200

    # Guest 1 sees only g1-conv
    g1_list = [c["id"] for c in guest_1.get("/conversations").get_json()["conversations"]]
    assert "g1-conv" in g1_list
    assert "g2-conv" not in g1_list

    # Guest 2 cannot access g1-conv
    assert guest_2.get("/conversations/g1-conv").status_code == 404
    assert guest_2.delete("/conversations/g1-conv").status_code == 404


def test_guest_upgrade_with_conversation_transfer(client, monkeypatch):
    """Verify upgrading a guest to registered account transfers conversation ownership seamlessly."""
    monkeypatch.setenv("GEMINI_API_KEY", "dummy_test_key_for_mock")

    # Start as guest and create a conversation
    with patch("app.call_gemini_api", return_value="Pre-upgrade answer"):
        client.post("/chat", json={"message": "Important guest study note", "conversation_id": "conv-upgrade-test"})

    guest_convs = client.get("/conversations").get_json()["conversations"]
    assert len(guest_convs) == 1
    assert guest_convs[0]["id"] == "conv-upgrade-test"

    # Upgrade guest account
    upgrade_res = client.post("/auth/upgrade-guest", json={
        "name": "Upgraded Student",
        "email": "upgraded@example.com",
        "password": "strongPassword123",
        "transfer_chats": True
    })
    assert upgrade_res.status_code == 200
    up_data = upgrade_res.get_json()
    assert up_data["status"] == "ok"
    assert up_data["transferred_conversations"] == 1
    assert up_data["user"]["is_guest"] is False

    # Check conversation is now retained under the registered account
    reg_convs = client.get("/conversations").get_json()["conversations"]
    assert len(reg_convs) == 1
    assert reg_convs[0]["id"] == "conv-upgrade-test"

    # Verify user profile in session is now registered
    me_res = client.get("/auth/me")
    assert me_res.get_json()["user"]["is_guest"] is False
    assert me_res.get_json()["user"]["email"] == "upgraded@example.com"


def test_guest_quota_enforcement(client, monkeypatch):
    """Verify guest accounts cannot exceed GUEST_MESSAGE_LIMIT prompts."""
    monkeypatch.setenv("GEMINI_API_KEY", "dummy_test_key_for_mock")

    # Initialize guest and manually update guest message count to limit in DB
    me = client.get("/auth/me").get_json()["user"]
    guest_id = me["id"]

    from app import get_db, GUEST_MESSAGE_LIMIT
    with get_db() as conn:
        conn.execute("UPDATE users SET guest_message_count = ? WHERE id = ?", (GUEST_MESSAGE_LIMIT, guest_id))

    # Next chat message must return 403 Forbidden
    res = client.post("/chat", json={"message": "Exceeding limit test prompt"})
    assert res.status_code == 403
    data = res.get_json()
    assert data["limit_reached"] is True
    assert "quota reached" in data["error"].lower()


def test_password_reset_workflow(client):
    """Verify forgot password and token-based reset workflow."""
    # Register user
    client.post("/auth/register", json={
        "name": "Sam Reset",
        "email": "sam.reset@example.com",
        "password": "initialPassword123",
        "confirm_password": "initialPassword123"
    })

    # Request reset token
    forgot_res = client.post("/auth/forgot-password", json={"email": "sam.reset@example.com"})
    assert forgot_res.status_code == 200
    token = forgot_res.get_json().get("reset_token")
    assert token and len(token) > 20

    # Reset with invalid token
    bad_res = client.post("/auth/reset-password", json={
        "token": "fake-invalid-token", "password": "newPassword123", "confirm_password": "newPassword123"
    })
    assert bad_res.status_code == 400

    # Reset with valid token
    ok_res = client.post("/auth/reset-password", json={
        "token": token, "password": "newPassword123", "confirm_password": "newPassword123"
    })
    assert ok_res.status_code == 200

    # Old password no longer works
    fail_login = client.post("/auth/login", json={"email": "sam.reset@example.com", "password": "initialPassword123"})
    assert fail_login.status_code == 401

    # New password works
    success_login = client.post("/auth/login", json={"email": "sam.reset@example.com", "password": "newPassword123"})
    assert success_login.status_code == 200


def test_logout_resets_to_fresh_guest(client):
    """Verify logging out clears user session and provisions a fresh guest."""
    # Register and log in
    client.post("/auth/register", json={
        "name": "Logout User", "email": "logout@example.com", "password": "password123", "confirm_password": "password123"
    })
    assert client.get("/auth/me").get_json()["user"]["is_guest"] is False

    # Logout
    logout_res = client.post("/auth/logout")
    assert logout_res.status_code == 200
    assert logout_res.get_json()["user"]["is_guest"] is True

    # Next check confirms guest
    me_res = client.get("/auth/me")
    assert me_res.get_json()["user"]["is_guest"] is True

