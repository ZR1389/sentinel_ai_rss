# deepseek_client.py — DeepSeek API wrapper
import os, requests, logging
from llm_rate_limiter import rate_limited

logger = logging.getLogger("deepseek_client")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"

@rate_limited("deepseek")
def deepseek_chat(messages, temperature=0.4, model="deepseek-chat", timeout=15):
    """
    Minimal DeepSeek chat interface.
    Compatible with OpenAI-style message schema.
    Returns string or None.
    
    Args:
        messages: List of message dicts
        temperature: Sampling temperature
        model: Model name
        timeout: Request timeout in seconds (default: 15s for fast-failover)
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
        r = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"[DeepSeek API Error] {e}")
        return None