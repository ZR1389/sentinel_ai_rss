import os
import signal
import logging
import threading
from contextlib import contextmanager
from xai_sdk import Client
from xai_sdk.chat import user, system
from llm_rate_limiter import rate_limited
from config import CONFIG

logger = logging.getLogger("xai_client")

XAI_API_KEY = CONFIG.llm.xai_api_key
XAI_API_HOST = "api.x.ai"
XAI_MODEL = CONFIG.llm.xai_model
TEMPERATURE = CONFIG.llm.xai_temperature

@contextmanager
def _timeout(seconds: int):
    """Force-timeout wrapper for blocking calls using SIGALRM (main thread only).
    Falls back to no alarm when not in main thread to avoid runtime errors.
    """
    if threading.current_thread() is not threading.main_thread() or seconds <= 0:
        # No-op timeout context outside main thread
        yield
        return

    def timeout_handler(signum, frame):
        raise TimeoutError(f"LLM call exceeded {seconds}s")

    # Set the signal handler (main thread only)
    prev_handler = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)  # Cancel the alarm
        # Restore previous handler to be safe
        try:
            signal.signal(signal.SIGALRM, prev_handler)
        except Exception:
            pass

@rate_limited("xai")
def grok_chat(messages, model=XAI_MODEL, temperature=TEMPERATURE, timeout=15):
    """
    Grok chat completion with **enforced** timeout support.
    Uses SIGALRM to prevent indefinite blocking.
    
    Args:
        messages: List of message dicts
        model: Model name
        temperature: Sampling temperature
        timeout: Request timeout in seconds (default: 15s for fast-failover)
    """
    if not XAI_API_KEY:
        logger.error("[Grok-3-mini] API key missing.")
        return None
    
    try:
        with _timeout(timeout):
            client = Client(api_host=XAI_API_HOST, api_key=XAI_API_KEY)
            chat = client.chat.create(model=model, temperature=temperature)
            for m in messages:
                if m["role"] == "system":
                    chat.append(system(m["content"]))
                elif m["role"] == "user":
                    chat.append(user(m["content"]))
            response = chat.sample()
            return response.content.strip() if response else None
    except TimeoutError:
        logger.error(f"[Grok-3-mini] Timeout after {timeout}s")
        return None
    except Exception as e:
        logger.error(f"[Grok-3-mini error] {e}")
        return None