#!/usr/bin/env python3
"""Five-Turn Memory Verification Script for StudyBuddy AI.

This script tests the required 5-turn multi-turn conversation memory sequence:
  Turn 1: "My name is Rahul, and I am learning Python."
  Turn 2: "I am a beginner in programming."
  Turn 3: "I want to build AI projects using Python."
  Turn 4: "What is my name, and which programming language am I learning?"
          -> Expected result: Mentions "Rahul" and "Python"
  Turn 5: "What kind of projects did I say I wanted to build?"
          -> Expected result: Mentions "AI projects" / "Python"

Usage:
  1. Ensure GEMINI_API_KEY is configured in .env or environment:
     export GEMINI_API_KEY="your-real-key"
  2. Run:
     python run_memory_test.py
"""

import sys
import os
import uuid
import json

# Ensure parent directory is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, get_gemini_api_key

TURNS = [
    {
        "turn": 1,
        "prompt": "My name is Rahul, and I am learning Python.",
        "expected_check": None,
    },
    {
        "turn": 2,
        "prompt": "I am a beginner in programming.",
        "expected_check": None,
    },
    {
        "turn": 3,
        "prompt": "I want to build AI projects using Python.",
        "expected_check": None,
    },
    {
        "turn": 4,
        "prompt": "What is my name, and which programming language am I learning?",
        "expected_check": lambda reply: "rahul" in reply.lower() and "python" in reply.lower(),
        "expected_description": "Must mention 'Rahul' and 'Python'",
    },
    {
        "turn": 5,
        "prompt": "What kind of projects did I say I wanted to build?",
        "expected_check": lambda reply: "ai" in reply.lower() or "artificial intelligence" in reply.lower(),
        "expected_description": "Must mention 'AI projects' using Python",
    },
]


def run_test():
    print("=" * 70)
    print("StudyBuddy AI — 5-Turn Memory Verification Test")
    print("=" * 70)

    api_key = get_gemini_api_key()
    if not api_key:
        print("\n[!] GEMINI_API_KEY is not configured or is a placeholder in .env.")
        print("    Please set a valid GEMINI_API_KEY in .env before running live tests.")
        print("    Example:")
        print("      GEMINI_API_KEY=AIzaSyYourActualKeyHere")
        print("\n    To run automated unit tests with mocks instead, run:")
        print("      pytest -v test_app.py\n")
        return False

    conversation_id = f"cli-test-{uuid.uuid4().hex[:8]}"
    print(f"[*] Initialized Test Conversation ID: {conversation_id}\n")

    client = app.test_client()
    passed_all = True

    for item in TURNS:
        turn_num = item["turn"]
        prompt = item["prompt"]
        print(f"--- Turn {turn_num} ---")
        print(f"User : {prompt}")

        response = client.post(
            "/chat",
            json={"message": prompt, "conversation_id": conversation_id},
        )

        if response.status_code != 200:
            print(f"[ERROR] Request failed with HTTP {response.status_code}")
            print(f"Server response: {response.get_data(as_text=True)}")
            return False

        data = response.get_json()
        reply = data.get("reply", "")
        print(f"AI   : {reply.strip()}\n")

        check_fn = item.get("expected_check")
        if check_fn:
            desc = item.get("expected_description", "Memory verification")
            if check_fn(reply):
                print(f"  [PASSED] Turn {turn_num} memory check passed: ({desc})\n")
            else:
                print(f"  [FAILED] Turn {turn_num} memory check failed: ({desc})\n")
                passed_all = False

    print("=" * 70)
    if passed_all:
        print("[SUCCESS] All 5 turns completed and context memory verified!")
    else:
        print("[NOTICE] Conversation completed, but some assertions need review.")
    print("=" * 70)
    return passed_all


if __name__ == "__main__":
    success = run_test()
    sys.exit(0 if success else 1)
