"""Diagnostic: which Gemini models respond to your key right now?

Sends a one-word prompt to each model (costs almost nothing) and lists the
Flash models your key can see.

Run from the project folder:  python ping_gemini.py
Or test specific models:      python ping_gemini.py gemini-3.5-flash gemini-flash-latest
"""
import os
import sys

from dotenv import load_dotenv
from google import genai
from google.genai import errors

load_dotenv()
key = os.getenv("GOOGLE_API_KEY")
if not key:
    sys.exit("GOOGLE_API_KEY is missing from .env")

print("Models set in .env:", os.getenv("GEMINI_MODELS") or os.getenv("GEMINI_MODEL") or "(not set, so RiskLens uses its defaults)")
client = genai.Client(api_key=key)

print("\nFlash models visible to your key:")
try:
    for m in client.models.list():
        if "flash" in m.name and "tts" not in m.name and "live" not in m.name:
            print("  ", m.name.replace("models/", ""))
except errors.APIError as e:
    print(f"   Could not list models: {e.code} {e.status} - {e.message}")

models = sys.argv[1:] or ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-flash-latest"]
print("\nTest calls:")
for model in models:
    try:
        r = client.models.generate_content(model=model, contents="Reply with the single word OK.")
        print(f"   {model}: WORKS (replied {(r.text or '').strip()[:20]!r})")
    except errors.APIError as e:
        print(f"   {model}: {e.code} {e.status} - {(e.message or '')[:120]}")
    except Exception as e:
        print(f"   {model}: could not connect - {e}")
