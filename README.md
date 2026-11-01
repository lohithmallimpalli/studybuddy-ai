# StudyBuddy AI — Professional Multi-User AI Platform with Guest Access

A commercial-grade, multi-turn conversational AI web platform inspired by ChatGPT and Google Gemini. Built with Python, Flask, SQLite, and the official Google GenAI SDK (`google-genai`), StudyBuddy AI empowers students and software engineers to master computer science, algorithms, and technical concepts with persistent conversation memory, strict per-user data isolation, instant guest access, and modern dark/light UI aesthetics.

---

## Table of Contents
1. [Project Overview](#1-project-overview)
2. [Objectives](#2-objectives)
3. [Key Capabilities & Three Access Modes](#3-key-capabilities--three-access-modes)
4. [Technologies Used](#4-technologies-used)
5. [Project Directory Structure](#5-project-directory-structure)
6. [Prerequisites](#6-prerequisites)
7. [How to Obtain a Gemini API Key](#7-how-to-obtain-a-gemini-api-key)
8. [Installation Instructions](#8-installation-instructions)
9. [Environment Variable Configuration](#9-environment-variable-configuration)
10. [How to Run the Application](#10-how-to-run-the-application)
11. [How to Test the Backend](#11-how-to-test-the-backend)
12. [API Endpoint Documentation](#12-api-endpoint-documentation)
13. [Multi-User Database Architecture](#13-multi-user-database-architecture)
14. [Strict Data Isolation & Security](#14-strict-data-isolation--security)
15. [Context Window Management](#15-context-window-management)
16. [Error Handling & Reliability](#16-error-handling--reliability)
17. [GitHub Upload Instructions](#17-github-upload-instructions)

---

## 1. Project Overview
StudyBuddy AI v3.0 delivers an intuitive, enterprise-grade AI tutoring experience. It provides:
- **Three Access Options**: Sign Up, Login, and **Instant Guest Access** without registration or passwords.
- **Strict Data Isolation**: Server-side session verification ensures registered users and guests only see and modify their own conversations.
- **Guest Account Quotas & Seamless Upgrade**: Guests enjoy 25 free study prompts, with one-click conversion to a registered account and optional conversation transfer.
- **ChatGPT-Style Left Sidebar**: Organizes past conversations into *Today*, *Yesterday*, *Previous 7 Days*, and *Older* with auto-titling, in-place renaming, deletion, and real-time search.
- **ACID-Compliant SQLite Persistence**: Retains all conversation turns across browser refreshes and server reboots.
- **Rich Markdown & Code Highlighting**: Formats headings, lists, tables, and fenced code blocks with language badges and one-click copy buttons.
- **Multi-Tier Model Fallback**: Automatically cascades across `gemini-flash-lite-latest`, `gemini-3.5-flash-lite`, and `gemini-3.1-flash-lite` on transient 404/503 errors.

---

## 2. Objectives
- **Multi-Turn Context Awareness**: Maintain reliable conversation history adhering to Google GenAI's alternating role constraint.
- **Context Economy**: Enforce `MAX_HISTORY_MESSAGES = 12` to prevent token bloat while ensuring conversation sequences always open and close with user turns.
- **Multi-Tenant Privacy**: Enforce database-level foreign keys and session-derived user identification to eliminate cross-account leakage.
- **Zero Friction Onboarding**: Instant guest access with cryptographically secure guest tokens and local persistence.
- **Enterprise UI/UX**: Smooth animations, auto-expanding composer, suggestion cards, response copying, regeneration, and dark/light theme switching.

---

## 3. Key Capabilities & Three Access Modes

### Access Mode A: Sign Up
- Full name, valid email, and secure password (minimum 6 characters) with confirmation validation.
- Werkzeug salted password hashing (`scrypt`).
- Duplicate email prevention (HTTP 409 Conflict).
- Optional transfer of conversations created while previously browsing as a guest.

### Access Mode B: Login
- Secure authentication via email and password.
- HttpOnly, SameSite=Lax session cookies preventing token theft.
- User profile display in the sidebar with avatar and sign-out controls.

### Access Mode C: Continue as Guest (Mandatory & Automatic)
- Immediate access without credentials or registration friction.
- Unique cryptographically generated guest identity (`guest-<uuid>`).
- Full access to the real Gemini AI model and multi-turn conversation memory.
- Guest conversations persist across browser reloads via SQLite and session cookies.
- Guest quota enforcement (25 prompts) to prevent API abuse.
- Clear visual guest badge with usage counter (`X / 25 Prompts`).
- Modal to upgrade guest accounts to permanent accounts with seamless conversation transfer.

---

## 4. Technologies Used
- **Backend Framework**: Python 3.10+ / Python 3.14, Flask 3.x
- **LLM Provider**: Google Gemini API (`gemini-flash-lite-latest` with fallback to `gemini-3.5-flash-lite`)
- **Official SDK**: `google-genai` (Google GenAI Python SDK v2+)
- **Password Security**: `werkzeug.security` (`generate_password_hash`, `check_password_hash`)
- **Database**: SQLite3 with thread-safe connection pooling, foreign keys, and migration handlers
- **Environment**: `python-dotenv`
- **WSGI / Production**: `gunicorn`
- **Testing**: `pytest`, `pytest-mock` (33 automated unit and integration tests)
- **Frontend**: Vanilla HTML5, Modern CSS3 with CSS Custom Properties, Vanilla JavaScript (ES6+ Fetch API, AbortController)
- **Version Control**: Git & GitHub

---

## 5. Project Directory Structure
```
llm-api-chatbot/
├── .env                  # Secret credentials (ignored by Git)
├── .env.example          # Template for environment configuration
├── .gitignore            # Git exclusion rules (ignores .env, *.db, venv/)
├── README.md             # Complete documentation
├── app.py                # Flask application, auth middleware, SQLite DB, Gemini integration
├── requirements.txt      # Project Python dependencies
├── run_memory_test.py    # 5-turn live Gemini memory verification CLI script
├── test_app.py           # Automated pytest test suite (33 tests)
├── static/
│   ├── css/
│   │   └── style.css     # Dark/Light theme, sidebar, user cards, modals, code blocks
│   └── js/
│       └── script.js     # State management, Markdown rendering, auth UI, modals, API calls
└── templates/
    ├── index.html        # Semantic HTML5 layout, sidebar, composer, modals, user cards
    └── auth.html         # Dedicated tabbed authentication screen (Login, Sign Up, Guest, Forgot Password)
```

---

## 6. Prerequisites
- **macOS**, Linux, or Windows
- **Python 3.10+** (Tested on Python 3.14)
- A Google Gemini API Key from [Google AI Studio](https://aistudio.google.com/)

---

## 7. How to Obtain a Gemini API Key
1. Visit [https://aistudio.google.com/](https://aistudio.google.com/) and sign in with your Google account.
2. Click **Get API key** in the left navigation panel.
3. Click **Create API key in new project**.
4. Copy the generated key (`AIzaSy...`).

---

## 8. Installation Instructions

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

## 9. Environment Variable Configuration
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

# Flask Secret Key for sessions
FLASK_SECRET_KEY=studybuddy-super-secret-key-prod-2026

# Flask Server Port (5001 avoids macOS AirPlay conflicts)
FLASK_PORT=5001
FLASK_DEBUG=False
```

---

## 10. How to Run the Application

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

## 11. How to Test the Backend

### Running the Full Automated Test Suite (33 Tests):
```bash
pytest -v test_app.py
```
Covers:
- **Authentication**: Registration, Login, Input validation, Duplicate email checks.
- **Guest Access**: Automatic guest provisioning, guest quota limit enforcement (403).
- **Data Isolation**: Guest A vs. Guest B isolation, User A vs. User B isolation, cross-account access rejection (404).
- **Guest Upgrade**: Conversion to permanent account with atomic conversation transfer.
- **Password Recovery**: Reset token generation, token expiration, password update, credential verification.
- **Conversation CRUD**: List, detail, rename, delete, search by title and message content.
- **Context Window**: 12-message sliding window, alternating turn sequencing, API failure rollback.
- **Live Gemini API**: Live generation test verifying connectivity.

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

## 12. API Endpoint Documentation

### Authentication & Account Endpoints
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/auth/me` | Returns current user profile and guest usage status. |
| `POST` | `/auth/register` | Registers a new user account with optional guest chat transfer. |
| `POST` | `/auth/login` | Authenticates existing user and creates session. |
| `POST` | `/auth/guest` | Explicitly provisions or resets a fresh guest session. |
| `POST` | `/auth/logout` | Clears user session and resets to a clean guest. |
| `POST` | `/auth/upgrade-guest` | Upgrades guest to full account and transfers existing chats. |
| `POST` | `/auth/forgot-password` | Generates a 1-hour secure password reset token. |
| `POST` | `/auth/reset-password` | Validates token and updates user password. |

### Core Chat & Conversation Endpoints
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/health` | Returns service status, model name, and SQLite DB health. |
| `POST` | `/chat` | Sends message or triggers regeneration (enforces guest quota). |
| `GET` | `/conversations` | Lists current user's/guest's conversations. |
| `GET` | `/conversations/<id>` | Retrieves message history verifying user ownership. |
| `PATCH` | `/conversations/<id>` | Renames conversation title verifying ownership. |
| `DELETE` | `/conversations/<id>` | Deletes conversation and messages verifying ownership. |
| `GET` | `/conversations/search?q=query` | Searches conversations within the authenticated user's scope. |

---

## 13. Multi-User Database Architecture
StudyBuddy AI uses four normalized SQLite tables with foreign keys and cascade deletions:

```sql
CREATE TABLE users (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    is_guest INTEGER DEFAULT 0,
    guest_message_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE conversations (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE TABLE password_resets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    token TEXT UNIQUE NOT NULL,
    expires_at TEXT NOT NULL,
    used INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
```

---

## 14. Strict Data Isolation & Security
- **Server-Side Session Resolution**: The authenticated `user_id` is extracted solely from `session['user_id']`. Client requests can never manipulate or override conversation ownership.
- **SQL Ownership Filters**: Every query on `/conversations` and `/conversations/<id>` binds `WHERE user_id = ?`. Unauthorized access attempts return HTTP 404 to avoid leaking conversation existence.
- **No Plaintext Passwords**: Password hashing uses Werkzeug's implementation with automatic salt generation.
- **No Hardcoded Keys**: Gemini credentials reside solely in `.env` (ignored by Git).
- **Log Masking**: Custom logging filter scrubs API keys matching `AIzaSy...` before writing to standard streams.
- **XSS Immunity**: Frontend rendering relies strictly on `document.createElement`, `textContent`, and safe token text nodes.

---

## 15. Context Window Management
- **Maximum 12 Messages**: History is capped at the 12 most recent turns (`MAX_HISTORY_MESSAGES = 12`).
- **Role Sequence Guarantee**: Context always begins with a `user` turn and alternates between `user` and `model`.
- **Atomic Rollback**: If an API call times out or encounters an error, the database transaction rolls back so broken turns never pollute history.

---

## 16. Error Handling & Reliability
- **Model Fallback**: Automatically tries secondary models (`gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`) if a model returns `404` or `503`.
- **Millisecond Timeout Normalization**: Converts seconds into milliseconds for `google-genai` `HttpOptions`, preventing socket timeouts.
- **Guest Quota Alerts**: When a guest reaches 25 messages, the system returns HTTP 403 and automatically opens the upgrade modal.
- **Client Stop Control**: Uses `AbortController` to cancel generation without hanging the UI.

---

## 17. GitHub Upload Instructions

```bash
cd "llm-api-chatbot"

# Verify .env and SQLite DB are safely ignored
git check-ignore -v .env studybuddy.db

# Stage all files
git add .

# Commit changes
git commit -m "Upgrade StudyBuddy AI to v3.0: Multi-user platform with guest access, auth workflows, and SQLite isolation"

# Push to your GitHub repository
git push origin main
```
