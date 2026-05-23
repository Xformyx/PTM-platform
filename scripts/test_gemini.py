#!/usr/bin/env python3
"""
Quick Gemini API connectivity test.
Loads .env from project root and sends a minimal request.

Usage:
  cd ptm-platform && python scripts/test_gemini.py
  # or with explicit key:
  GEMINI_API_KEY=your_key python scripts/test_gemini.py
"""
import os
import sys
from pathlib import Path

# Load .env from project root (parent of scripts/)
ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

try:
    import requests
except ImportError:
    print("Install requests: pip install requests")
    sys.exit(1)

API_KEY = os.getenv("GEMINI_API_KEY", "")
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"

if not API_KEY:
    print("GEMINI_API_KEY not set. Add to .env or: GEMINI_API_KEY=xxx python scripts/test_gemini.py")
    sys.exit(1)

print(f"Testing Gemini API (model={MODEL})...")
try:
    r = requests.post(
        URL,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"},
        json={
            "model": MODEL,
            "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
            "max_tokens": 10,
        },
        timeout=15,
    )
    if r.status_code == 200:
        text = r.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        print(f"OK - Gemini responded: {text.strip()!r}")
    else:
        print(f"FAIL - HTTP {r.status_code}: {r.text[:300]}")
        sys.exit(1)
except Exception as e:
    print(f"FAIL - {e}")
    sys.exit(1)
