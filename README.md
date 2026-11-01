# StudyBuddy AI — Professional AI Study Assistant

A commercial-grade, multi-turn conversational AI web application inspired by ChatGPT and Google Gemini. Built with Python, Flask, SQLite, and the official Google GenAI SDK (`google-genai`), StudyBuddy AI empowers students and software engineers to master computer science, algorithms, and technical concepts with persistent conversation memory, an interactive sidebar dashboard, and modern dark/light UI aesthetics.

---

## Table of Contents
1. [Project Title](#1-project-title)
2. [Project Overview](#2-project-overview)
3. [Objectives](#3-project-objectives)
4. [Key Features](#4-key-features)
5. [Technologies Used](#5-technologies-used)
6. [Project Directory Structure](#6-project-directory-structure)
7. [Prerequisites](#7-prerequisites)
8. [How to Obtain a Gemini API Key](#8-how-to-obtain-a-gemini-api-key)
9. [Installation Instructions](#9-installation-instructions)
10. [Environment Variable Configuration](#10-environment-variable-configuration)
11. [How to Run the Application](#11-how-to-run-the-application)
12. [How to Test the Backend](#12-how-to-test-the-backend)
13. [API Endpoint Documentation](#13-api-endpoint-documentation)
14. [SQLite Persistent Storage Architecture](#14-sqlite-persistent-storage-architecture)
15. [Context Window Management](#15-context-window-management)
16. [Error Handling & Reliability](#16-error-handling--reliability)
17. [Security & XSS Prevention](#17-security--xss-prevention)
18. [GitHub Upload Instructions](#18-github-upload-instructions)

---

## 1. Project Title
**StudyBuddy AI — Professional LLM API Integration Chatbot (v2.0)**

---

## 2. Project Overview
StudyBuddy AI delivers an intuitive, full-featured AI tutoring experience. Beyond single-prompt interactions, StudyBuddy AI provides:
- A ChatGPT-style collapsible left sidebar organizing past conversations by time categories (Today, Yesterday, Previous 7 Days, Older).
- Local persistent storage powered by SQLite, ensuring conversations survive browser refreshes and server reboots.
- Dynamic conversation management: automatic title generation, in-place renaming, deletion with confirmation, and real-time history search.
- Rich Markdown parsing with fenced code block detection, syntax tokenization, and one-click code copy buttons.
- Multi-tier model fallback (`gemini-flash-lite-latest` with automatic resilience for 404 or 503 errors).

---

## 3. Project Objectives
- **Multi-Turn Context Awareness**: Maintain reliable conversation history adhering to Google GenAI's alternating role constraint.
- **Context Economy**: Enforce `MAX_HISTORY_MESSAGES = 12` to prevent token bloat while ensuring the conversation sequence always opens and closes with user turns.
- **Permanent Persistence**: Store conversations and messages in an ACID-compliant local SQLite database with cascade deletes.
- **Enterprise UI/UX**: Provide smooth animations, auto-expanding composer, suggestion cards, response copying, regeneration, and dark/light theme switching.
- **Strict Security**: Zero client-side API key exposure, sanitized logging filters, and safe DOM manipulation preventing XSS.

---

## 4. Key Features
- **ChatGPT-Style Left Sidebar**:
  - Auto-generated conversation titles derived from the opening prompt.
  - Chronological grouping: *Today*, *Yesterday*, *Previous 7 Days*, and *Older*.
  - Three-dot action menu on each conversation for **Rename** and **Delete** with confirmation modals.
  - Real-time search filtering conversations by title or message contents.
  - Desktop sidebar collapse/expand toggle (`⌘[` or `Ctrl+[`) and mobile slide-out drawer with backdrop.
- **Persistent SQLite Storage**:
  - Automatic database initialization (`studybuddy.db`).
  - Seamlessly reloads previous conversations upon page refresh or server restart.
- **Rich Message Presentation**:
  - Markdown headings, lists, bold, italics, tables, and blockquotes.
  - Fenced code blocks with language badge and one-click "Copy Code" button.
  - Syntax token styling for keywords, strings, numbers, and comments.
  - Response action toolbar: "Copy response" and "Regenerate" on the latest assistant turn.
  - "Stop generation" button using standard browser `AbortController`.
- **Interactive Welcome Screen**:
  - 6 interactive study cards for instant prompts: Big-O notation, Python basics, machine learning, data structures, deep learning, and code debugging.
- **Theme Customization**:
  - Dark Navy glassmorphic mode (default) and clean Slate Light mode with `localStorage` persistence.

---

## 5. Technologies Used
- **Backend Framework**: Python 3.10+ / Python 3.14, Flask 3.x
- **LLM Provider**: Google Gemini API (`gemini-flash-lite-latest` with fallback to `gemini-3.5-flash-lite`)
- **Official SDK**: `google-genai` (Google GenAI Python SDK v2+)
- **Database**: SQLite3 with thread-safe connection pooling and foreign keys
- **Environment**: `python-dotenv`
- **WSGI / Production**: `gunicorn`
- **Testing**: `pytest`, `pytest-mock`
- **Frontend**: Vanilla HTML5, Modern CSS3 with CSS Custom Properties, Vanilla JavaScript (ES6+ Fetch API, AbortController)
- **Version Control**: Git & GitHub

---

## 6. Project Directory Structure
```
llm-api-chatbot/
├── .env                  # Secret credentials (ignored by Git)
├── .env.example          # Template for environment configuration
├── .gitignore            # Git exclusion rules (ignores .env, *.db, venv/)
├── README.md             # Complete documentation
├── app.py                # Flask application, SQLite DB, and Gemini API integration
├── requirements.txt      # Project Python dependencies
├── run_memory_test.py    # 5-turn live Gemini memory verification CLI script
├── test_app.py           # Automated pytest test suite (22 tests)
├── static/
│   ├── css/
│   │   └── style.css     # Dark/Light theme, sidebar, code blocks, animations
│   └── js/
│       └── script.js     # State management, Markdown rendering, API calls, modals
└── templates/
    └── index.html        # Semantic HTML5 layout, sidebar, composer, and modals
```

---

## 7. Prerequisites
- **macOS**, Linux, or Windows
- **Python 3.10+** (Tested on Python 3.14)
- A Google Gemini API Key from [Google AI Studio](https://aistudio.google.com/)

---

## 8. How to Obtain a Gemini API Key
1. Visit [https://aistudio.google.com/](https://aistudio.google.com/) and sign in with your Google account.
2. Click **Get API key** in the left navigation panel.
3. Click **Create API key in new project**.
4. Copy the generated key (`AIzaSy...`).

---

## 9. Installation Instructions

```bash
# 1. Clone or navigate to the repository
cd "llm-api-chatbot"

# 2. Create and activate a Python virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install required dependencies
pip install -r requirements.txt
```

---

## 10. Environment Variable Configuration
Create a `.env` file in the project root:

```bash
cp .env.example .env
```

Edit `.env` with your actual credentials:
```ini
# Google Gemini API Key
GEMINI_API_KEY=AIzaSyYourActualKeyHere

# Primary Model (Recommended: gemini-flash-lite-latest)
GEMINI_MODEL=gemini-flash-lite-latest

# API Request Timeout in seconds
GEMINI_TIMEOUT=30.0

# Flask Server Port (5001 avoids macOS AirPlay conflicts)
FLASK_PORT=5001
FLASK_DEBUG=False
```

---

## 11. How to Run the Application

### Development Mode:
```bash
source venv/bin/activate
python app.py
```
Open [http://localhost:5001](http://localhost:5001) in your browser.

### Production WSGI Mode (Gunicorn):
```bash
gunicorn -w 2 -b 0.0.0.0:5001 app:app
```

---

## 12. How to Test the Backend

### Running the Automated Test Suite (22 Tests):
```bash
pytest -v test_app.py
```
Covers:
- Health check and index routes
- Request validation (bad JSON, missing fields, empty strings)
- Missing API key 503 response
- SQLite persistence, session isolation, and atomic rollback on failure
- Full CRUD operations: listing, retrieving, renaming, deleting, and searching conversations
- Regeneration of last response
- Five-turn conversation memory sequence
- Live Gemini API connectivity

### Running the 5-Turn Memory Verification Script:
```bash
python run_memory_test.py
```
Executes the live 5-turn test sequence against Google Gemini:
- Turn 1: *"My name is Rahul, and I am learning Python."*
- Turn 2: *"I am a beginner in programming."*
- Turn 3: *"I want to build AI projects using Python."*
- Turn 4: *"What is my name, and which programming language am I learning?"* -> Verified: recalls **Rahul** and **Python**.
- Turn 5: *"What kind of projects did I say I wanted to build?"* -> Verified: recalls **AI projects**.

---

## 13. API Endpoint Documentation

### Core Endpoints
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/` | Serves the main web dashboard. |
| `GET` | `/health` | Returns service status, model name, and SQLite database health. |
| `POST` | `/chat` | Submits a message or triggers regeneration. |

#### `POST /chat` Payload:
```json
{
  "message": "Explain recursion in Python",
  "conversation_id": "optional-uuid",
  "regenerate": false
}
```
#### `POST /chat` Success Response (200):
```json
{
  "reply": "Recursion occurs when a function calls itself...",
  "conversation_id": "6abc12d1-4e78-4ef3-9821-ab90177a7554",
  "title": "Explain recursion in Python"
}
```

### Conversation Management Endpoints
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/conversations` | Lists all conversations ordered by recent activity. |
| `GET` | `/conversations/<id>` | Retrieves full message history for a specific conversation. |
| `PATCH` | `/conversations/<id>` | Renames conversation title (`{"title": "New Title"}`). |
| `DELETE` | `/conversations/<id>` | Deletes conversation and cascades delete to messages. |
| `GET` | `/conversations/search?q=query` | Searches conversations by title or message contents. |

---

## 14. SQLite Persistent Storage Architecture

StudyBuddy AI manages data through two normalized SQLite tables:

```sql
CREATE TABLE conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,         -- 'user' or 'model'
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);
```

- **Thread Safety**: Wrapped in Python `contextlib.contextmanager` with automatic commits, rollbacks, and connection closing.
- **Cascade Deletion**: Foreign key constraints enabled (`PRAGMA foreign_keys = ON`). Deleting a conversation cleanly removes all its messages.
- **Indexing**: Indices on `messages(conversation_id)` and `conversations(updated_at DESC)` guarantee fast sidebar rendering and sub-millisecond lookups.

---

## 15. Context Window Management
To optimize token usage and comply with Gemini's API expectations:
- **Maximum 12 Messages**: History is capped at the 12 most recent turns (`MAX_HISTORY_MESSAGES = 12`).
- **Role Sequence Guarantee**: Histories always begin with a `user` turn. Trimming leading `model` turns ensures compatibility.
- **Role Alternation**: Adjacent messages with identical roles are merged automatically.
- **Atomic Rollback**: If an API call fails or times out, neither the user query nor an empty model response is recorded in SQLite.

---

## 16. Error Handling & Reliability
- **Model Fallback**: Automatically tries secondary models (`gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`) if a model returns `404` or `503`.
- **Timeout Management**: Converts seconds to milliseconds for `google-genai` `HttpOptions`, preventing socket timeouts.
- **User-Friendly Error Cards**: Clear in-chat alerts for quota exceeded (429), timeouts (504), or network outages.
- **Client Stop Control**: Uses `AbortController` to cancel generation without hanging the UI.

---

## 17. Security & XSS Prevention
- **No Hardcoded Keys**: API keys are loaded via environment variables; `.env` and `*.db` are excluded in `.gitignore`.
- **Log Masking**: Custom `SensitiveDataFilter` scrubs Google API key signatures (`AIzaSy...`) from stdout and logs.
- **XSS Immunity**: Frontend rendering relies strictly on `document.createElement`, `textContent`, and safe token text nodes. Untrusted user and model inputs are never evaluated as HTML or JavaScript.

---

## 18. GitHub Upload Instructions

```bash
cd "llm-api-chatbot"

# Verify .env and SQLite DB are safely ignored
git check-ignore -v .env studybuddy.db

# Stage all files
git add .

# Commit changes
git commit -m "Upgrade StudyBuddy AI to v2.0: SQLite persistence, ChatGPT-style sidebar, and dynamic UI"

# Push to your GitHub repository
git push origin main
```
