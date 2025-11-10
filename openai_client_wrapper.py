# openai_client_wrapper.py — Sentinel unified OpenAI client
import os, logging
from openai import OpenAI

logger = logging.getLogger("openai_client_wrapper")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
DEFAULT_TEMP = float(os.getenv("OPENAI_TEMPERATURE", "0.4"))

client = OpenAI(api_key=OPENAI_API_KEY, timeout=60.0) if OPENAI_API_KEY else None

def openai_chat(messages, temperature=DEFAULT_TEMP, model=DEFAULT_MODEL):
    if not client:
        raise RuntimeError("OpenAI client not initialized (missing key or import).")

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"[OpenAI API Error] {e}")
        return None
