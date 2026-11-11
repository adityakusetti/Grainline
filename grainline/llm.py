"""One place for LLM calls: JSON-only responses, retries, and a safe fallback when anything fails."""
import json
import os

from . import http

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def extract_json(text):
    try:
        return json.loads(text[text.index("{"): text.rindex("}") + 1])
    except (ValueError, json.JSONDecodeError):
        return None


def chat_json(system, user, model, temperature=0):
    """Return parsed JSON from the model, or None if the call or the parsing fails."""
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        return None
    try:
        r = http.request("POST", http_url(), headers={"Authorization": f"Bearer {key}"}, timeout=120,
                         json={"model": model, "temperature": temperature, "response_format": {"type": "json_object"},
                               "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        return extract_json(r.json()["choices"][0]["message"]["content"])
    except Exception:
        return None


def http_url():
    return os.environ.get("GRAINLINE_LLM_URL", GROQ_URL)
