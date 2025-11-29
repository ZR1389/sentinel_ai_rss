# openai_client_wrapper.py — Sentinel unified OpenAI client
import os, logging
from openai import OpenAI
from monitoring.llm_rate_limiter import rate_limited
from core.config import CONFIG

logger = logging.getLogger("openai_client_wrapper")

OPENAI_API_KEY = CONFIG.llm.openai_api_key
DEFAULT_MODEL = CONFIG.llm.openai_model
DEFAULT_TEMP = CONFIG.llm.openai_temperature

client = OpenAI(api_key=OPENAI_API_KEY, timeout=60.0) if OPENAI_API_KEY else None

@rate_limited("openai")
def openai_chat(messages, temperature=DEFAULT_TEMP, model=DEFAULT_MODEL, timeout=20):
    """
    OpenAI chat completion with timeout support.
    
    Args:
        messages: List of message dicts
        temperature: Sampling temperature
        model: Model name
        timeout: Request timeout in seconds (default: 20s for fast-failover)
    """
    if not client:
        raise RuntimeError("OpenAI client not initialized (missing key or import).")

    try:
        # Create a new client instance with custom timeout
        timeout_client = OpenAI(api_key=OPENAI_API_KEY, timeout=timeout)
        resp = timeout_client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"[OpenAI API Error] {e}")
        return None