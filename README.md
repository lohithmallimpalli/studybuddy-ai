# StudyBuddy AI — Your Personal AI Study Assistant

A production-ready conversational AI web application built with Python, Flask, and the official Google GenAI SDK (`google-genai`). StudyBuddy AI is engineered to help students and developers master computer science, programming algorithms, and technical concepts through intelligent, multi-turn dialogue with real memory and context management.

---

## Table of Contents
1. [Project Title](#1-project-title)
2. [Project Overview](#2-project-overview)
3. [Objectives](#3-project-objectives)
4. [Features](#4-features)
5. [Technologies Used](#5-technologies-used)
6. [Project Directory Structure](#6-project-directory-structure)
7. [Prerequisites](#7-prerequisites)
8. [How to Obtain a Gemini API Key](#8-how-to-obtain-a-gemini-api-key)
9. [Installation Instructions for macOS](#9-installation-instructions-for-macos)
10. [Virtual Environment Setup](#10-virtual-environment-setup)
11. [Environment Variable Configuration](#11-environment-variable-configuration)
12. [How to Run the Application](#12-how-to-run-the-application)
13. [How to Test the Backend](#13-how-to-test-the-backend)
14. [API Endpoint Documentation](#14-api-endpoint-documentation)
15. [Conversation History Implementation](#15-conversation-history-implementation)
16. [Context Window Management](#16-context-window-management)
17. [Error Handling](#17-error-handling)
18. [Security Practices](#18-security-practices)
19. [Known Limitations](#19-known-limitations)
20. [GitHub Upload Instructions](#20-github-upload-instructions)

---

## 1. Project Title
**StudyBuddy AI — LLM API Integration Chatbot**

---

## 2. Project Overview
StudyBuddy AI provides students, self-taught programmers, and computer science engineers with an interactive study partner. Unlike basic single-prompt chatbots, StudyBuddy AI maintains genuine multi-turn conversation memory, allowing users to ask follow-up questions, reference prior explanations, and build complex projects step-by-step. The backend is implemented in Flask and communicates directly with the Google Gemini API using Google's modern `google-genai` Python library.

---

## 3. Project Objectives
- Implement authentic multi-turn conversation memory using Google's modern `google-genai` SDK.
- Enforce strict context window management (`MAX_HISTORY_MESSAGES = 12`) to optimize token economy and respect model sequence constraints.
- Build a responsive, high-performance web interface adhering to modern dark-mode aesthetic standards.
- Ensure strict security compliance: zero API key exposure to client code, `.gitignore` exclusion of credentials, and sanitized logging.
- Maintain thread-safe in-memory session isolation for concurrent users.

---

## 4. Features
- **Multi-Turn Context Awareness**: Remembers earlier context within a conversation (e.g., student name, chosen programming language, and goals).
- **Session Isolation**: Each conversation is assigned a unique RFC4122 v4 UUID; messages from one conversation never leak into another.
- **Context Management**: Dynamically trims conversation history to the most recent 12 turns while guaranteeing proper role alternating starting with a user turn.
- **Atomic History Updates (Rollback Invariant)**: In-memory history is updated only upon a successful API response. If an API request fails or times out, history is not corrupted.
- **XSS-Safe Frontend**: Uses safe DOM operations (`textContent`, `document.createElement`) to display model outputs without executing untrusted scripts.
- **Code Block Formatting**: Automatically detects fenced code blocks (` ```python `) and formats them into readable code snippets.
- **Interactive Suggestion Chips**: Quick-start prompts to explore Big-O notation, Python decorators, algorithm traversals, and machine learning concepts.
- **Comprehensive Error Notifications**: Clear, non-technical error notifications for missing API keys, rate limits, timeouts, and network issues.
- **One-Click New Chat**: Generates a clean session and resets client-side context instantly.

---

## 5. Technologies Used
- **Backend**: Python 3.10+ / Python 3.12 / Python 3.14, Flask 3.x
- **LLM Provider**: Google Gemini API (`gemini-2.5-flash` or `gemini-2.0-flash`)
- **Official SDK**: `google-genai` (Google GenAI Python SDK)
- **Environment Management**: `python-dotenv`
- **WSGI / Production Server**: `gunicorn`
- **Testing**: `pytest`, `pytest-mock`
- **Frontend**: Vanilla HTML5, Modern CSS3 (Dark Navy Glassmorphic Design), Vanilla JavaScript (ES6+ Fetch API)
- **Version Control**: Git & GitHub

---

## 6. Project Directory Structure
```
llm-api-chatbot/
├── .env                  # Local secret keys (ignored by git)
├── .env.example          # Safe template for environment variables
├── .gitignore            # Git exclusion rules
├── README.md             # Complete project documentation
├── app.py                # Main Flask application and Gemini API integration
├── requirements.txt      # Project Python dependencies
├── run_memory_test.py    # 5-turn memory verification CLI script
├── test_app.py           # Automated pytest test suite
├── static/
│   ├── css/
│   │   └── style.css     # Dark navy design system, animations, responsive layout
│   └── js/
│       └── script.js     # DOM manipulation, Fetch API, session handling
└── templates/
    └── index.html        # Semantic HTML5 chat interface layout
```

---

## 7. Prerequisites
Before installing the application, ensure your environment meets the following requirements:
- **macOS** (Sonoma, Ventura, Monterey, or later) or Linux / Windows
- **Python 3.10+** (Tested on Python 3.12 and Python 3.14)
- **Git** installed (`git --version`)
- A valid **Google Gemini API Key** (from Google AI Studio)

---

## 8. How to Obtain a Gemini API Key
1. Visit the [Google AI Studio](https://aistudio.google.com/).
2. Sign in with your Google account.
3. Click on the blue **"Get API key"** button in the left sidebar.
4. Select **"Create API key"** (in a new or existing Google Cloud project).
5. Copy your generated key (starts with `AIzaSy...`).
6. Treat this key as a secret. Never commit it to GitHub or share it publicly.

---

## 9. Installation Instructions for macOS
Open your Terminal (`Terminal.app` or iTerm2) and execute the following commands:

```bash
# 1. Clone or navigate to the project directory
cd "llm-api-chatbot"

# 2. Verify Python 3 is available
python3 --version
```

---

## 10. Virtual Environment Setup
It is best practice to run the application within an isolated virtual environment:

```bash
# Create a virtual environment named 'venv'
python3 -m venv venv

# Activate the virtual environment on macOS/Linux
source venv/bin/activate

# Upgrade pip to latest version
pip install --upgrade pip

# Install all required project dependencies
pip install -r requirements.txt
```

To deactivate the virtual environment at any time:
```bash
deactivate
```

---

## 11. Environment Variable Configuration
1. Create a `.env` file by copying the provided `.env.example` template:
   ```bash
   cp .env.example .env
   ```

2. Open `.env` in your preferred editor (e.g., `nano .env` or VS Code) and set your `GEMINI_API_KEY`:
   ```ini
   # Google Gemini API Key
   GEMINI_API_KEY=AIzaSyYourActualGeminiApiKeyHere

   # Gemini Model configuration (Default: gemini-2.5-flash)
   GEMINI_MODEL=gemini-2.5-flash

   # API Request Timeout in seconds
   GEMINI_TIMEOUT=30.0

   # Flask Server Configuration
   # (Port 5001 is recommended on macOS to avoid AirPlay Receiver conflicts on 5000)
   FLASK_PORT=5001
   FLASK_DEBUG=False
   ```

> **Note on macOS Port 5000**: macOS uses port 5000 by default for its ControlCenter "AirPlay Receiver" feature. StudyBuddy AI defaults to `FLASK_PORT=5001` so that it runs out-of-the-box without port collision errors.

---

## 12. How to Run the Application

### Development Mode (Flask Built-in Server):
```bash
# Ensure virtual environment is active
source venv/bin/activate

# Run the Flask app
python app.py
```
Output:
```
Starting StudyBuddy AI server on http://127.0.0.1:5001 (Debug: False)...
 * Serving Flask app 'app'
 * Running on http://127.0.0.1:5001
```
Open your browser and navigate to: **`http://127.0.0.1:5001`**

### Production Mode (Gunicorn WSGI):
```bash
# Run with 2 worker processes binding to port 5001
gunicorn -w 2 -b 0.0.0.0:5001 app:app
```

---

## 13. How to Test the Backend

### Running the Automated Test Suite:
Run pytest from within the `llm-api-chatbot` directory:
```bash
pytest -v test_app.py
```
This suite automatically tests:
- Health check `GET /health` and UI route `GET /`
- Rejection of invalid JSON, missing message, and empty strings (HTTP 400)
- Graceful 503 response when API key is missing or unconfigured
- Automatic conversation ID generation and preservation
- Context window truncation and role sequencing (first turn must be `user`)
- Conversation isolation between separate session IDs
- Atomic rollback of conversation history upon simulated API failure
- Full mocked 5-turn conversation sequence

### Running the 5-Turn Memory Verification Script:
Once you have added your real `GEMINI_API_KEY` to `.env`:
```bash
python run_memory_test.py
```
This tests the full 5-turn sequence against the real Gemini API and validates that StudyBuddy AI accurately recalls earlier turns:
- **Turn 1**: "My name is Rahul, and I am learning Python."
- **Turn 2**: "I am a beginner in programming."
- **Turn 3**: "I want to build AI projects using Python."
- **Turn 4**: "What is my name, and which programming language am I learning?" *(Validates response contains 'Rahul' and 'Python')*
- **Turn 5**: "What kind of projects did I say I wanted to build?" *(Validates response contains 'AI projects')*

---

## 14. API Endpoint Documentation

### `GET /`
- **Description**: Serves the main web chatbot interface.
- **Response**: HTML5 document (HTTP 200).

### `GET /health`
- **Description**: Health check endpoint to verify backend status and model configuration.
- **Response (HTTP 200)**:
  ```json
  {
    "app": "StudyBuddy AI",
    "model": "gemini-2.5-flash",
    "status": "ok",
    "version": "1.0.0"
  }
  ```

### `POST /chat`
- **Description**: Submits a user message, manages conversation context, and queries the Gemini API.
- **Request Headers**: `Content-Type: application/json`
- **Request Body**:
  ```json
  {
    "message": "Explain quicksort in Python",
    "conversation_id": "optional-uuid-string"
  }
  ```
- **Validation Rules**:
  - `message` is required, must be a string, and cannot be blank or whitespace-only.
  - `conversation_id` is optional; if omitted or blank, the server generates a new UUID v4.
- **Success Response (HTTP 200)**:
  ```json
  {
    "reply": "Quicksort is an efficient, divide-and-conquer sorting algorithm...",
    "conversation_id": "b8f235d0-424a-4d7a-b50a-99238374a485"
  }
  ```
- **Error Responses**:
  - **400 Bad Request**: Invalid JSON or empty `message`.
    ```json
    {"error": "Message cannot be empty."}
    ```
  - **401 Unauthorized**: Invalid or expired `GEMINI_API_KEY`.
    ```json
    {"error": "Authentication failed. The provided Gemini API key is invalid or unauthorized."}
    ```
  - **429 Too Many Requests**: Gemini API quota or rate limit exceeded.
    ```json
    {"error": "Gemini API rate limit or quota exceeded. Please wait a moment and try again."}
    ```
  - **503 Service Unavailable**: `GEMINI_API_KEY` is not configured or network unreachable.
    ```json
    {"error": "Gemini API key is not configured. Please set your GEMINI_API_KEY in the .env file or environment variables to start chatting with StudyBuddy AI."}
    ```
  - **504 Gateway Timeout**: Gemini API did not respond within configured timeout.
    ```json
    {"error": "Request to the Gemini API timed out. Please try again."}
    ```

---

## 15. Conversation History Implementation
1. **In-Memory Store**: Conversation turns are maintained in a global dictionary `conversations_store` mapped by `conversation_id`.
2. **Turn Structure**: Each entry stores `{"role": "user"|"model", "content": str, "timestamp": str}`.
3. **Thread Safety**: Concurrent read and write operations are synchronized using a `threading.Lock()` (`store_lock`).
4. **Data Isolation**: Conversations are partitioned strictly by `conversation_id`. Requests from different clients cannot see or modify other sessions.
5. **Session Ephemerality**: In-memory storage resets whenever the Flask application restarts.

---

## 16. Context Window Management
StudyBuddy AI enforces an active context management strategy through the `manage_context_window` function:
- **Maximum History Limit**: Enforces `MAX_HISTORY_MESSAGES = 12`. Only the 12 most recent message turns are transmitted to the API.
- **Role Sequence Integrity**:
  - The Gemini API requires conversation histories to begin with a `user` turn. If window slicing cuts into a `model` turn, `manage_context_window` automatically discards the leading model turn so the history begins with a `user` turn.
  - The final message in the sequence is always the new user prompt.
- **System Prompt Separation**: The system prompt (`SYSTEM_PROMPT`) is supplied through `types.GenerateContentConfig(system_instruction=...)` and is never mixed into user/model history turns.
- **Atomic Rollback**: If an API call fails or encounters an exception, neither the user message nor an empty reply is added to the permanent store, keeping history clean.

---

## 17. Error Handling
The application handles failure modes with user-friendly error responses:
- **Missing API Key**: Returns HTTP 503 with setup instructions, displaying an alert banner on the frontend.
- **Invalid Input**: Returns HTTP 400 for empty messages, missing fields, or invalid JSON.
- **Rate Limits (429)**: Returns HTTP 429 notifying the user to pause before re-submitting.
- **API Timeouts**: Configurable timeout (`GEMINI_TIMEOUT`, default 30s) prevents hung connections and returns HTTP 504.
- **Empty or Filtered Responses**: Detects empty generation or safety block flags (`response.candidates[0].finish_reason`) and returns an informative notice.
- **Frontend Feedback**: Disables the Send button during generation, renders typing indicators, and logs network failures without crashing.

---

## 18. Security Practices
- **No Hardcoded Credentials**: API keys are loaded strictly from environment variables via `os.getenv()`.
- **Git Protection**: `.env` is declared in `.gitignore` and verified before committing.
- **Zero Frontend Leakage**: The client communicates solely with `/chat`. The Gemini API key is never exposed to browser JavaScript or client-side assets.
- **Sanitized Logging**: A custom `SensitiveDataFilter` scrubs Google API key patterns (`AIza...`) from all server log outputs.
- **XSS Prevention**: Model responses are rendered using safe DOM properties (`textContent`) and programmatic node creation, preventing malicious script injection.

---

## 19. Known Limitations
- **In-Memory Volatility**: Conversations are stored in memory and do not persist across server restarts. For permanent production use, an external database (e.g., PostgreSQL or Redis) should be integrated.
- **Token Ceiling**: Long, single messages that exceed Gemini's per-prompt token limit will trigger an API error.
- **Client Session Persistence**: Conversation IDs are tied to browser session state; refreshing the browser will reset the client session view.

---

## 20. GitHub Upload Instructions

Follow these exact steps to push this project to your GitHub account:

### Step 1: Verify Git Status and Ignored Files
```bash
cd "llm-api-chatbot"

# Verify .env is completely ignored by Git
git check-ignore -v .env
# Expected output: .gitignore:2:.env .env

# Check tracked and untracked files
git status
```

### Step 2: Stage and Commit the Code
```bash
# Add all safe project files
git add .

# Verify staged files (ensure .env is NOT in this list)
git status

# Commit the files
git commit -m "Initial commit: StudyBuddy AI multi-turn chatbot with Google Gemini API"
```

### Step 3: Connect and Push to GitHub
1. Create a new repository on [GitHub](https://github.com/new) named `llm-api-chatbot` (do not initialize with a README, .gitignore, or license).
2. Run the following commands, replacing `YOUR_USERNAME` with your GitHub username:

```bash
# Set default branch to main
git branch -M main

# Add your GitHub remote repository
git remote add origin https://github.com/YOUR_USERNAME/llm-api-chatbot.git

# Push code to GitHub
git push -u origin main
```
