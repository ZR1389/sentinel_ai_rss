# deepseek_client.py — DeepSeek API wrapper
import os, requests, logging

logger = logging.getLogger("deepseek_client")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"

def deepseek_chat(messages, temperature=0.4, model="deepseek-chat"):
    """
    Minimal DeepSeek chat interface.
    Compatible with OpenAI-style message schema.
    Returns string or None.
    """
    if not DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY not set")

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }

    try:
        r = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=60)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"[DeepSeek API Error] {e}")
        return None
