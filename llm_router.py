import os
import logging
from deepseek_client import deepseek_chat
from openai_client_wrapper import openai_chat
from xai_client import grok_chat

logger = logging.getLogger("llm_router")

def route_llm(messages, temperature=0.4, usage_counts=None):
    usage_counts = usage_counts or {"deepseek": 0, "openai": 0, "grok": 0, "none": 0}

    PROVIDER_PRIMARY = os.getenv("ADVISOR_PROVIDER_PRIMARY", "deepseek").lower()
    PROVIDER_SECONDARY = os.getenv("ADVISOR_PROVIDER_SECONDARY", "openai").lower()
    PROVIDER_TERTIARY = os.getenv("ADVISOR_PROVIDER_TERTIARY", "grok").lower()
    provider_order = [PROVIDER_PRIMARY, PROVIDER_SECONDARY, PROVIDER_TERTIARY]

    logger.info(f"[LLM Router] Using provider order: {provider_order}")

    def try_provider(name):
        try:
            if name == "deepseek" and deepseek_chat:
                s = deepseek_chat(messages, temperature=temperature)
                if s and s.strip():
                    usage_counts["deepseek"] += 1
                    return s.strip(), "deepseek"
            elif name == "openai" and openai_chat:
                s = openai_chat(messages, temperature=temperature)
                if s and s.strip():
                    usage_counts["openai"] += 1
                    return s.strip(), "openai"
            elif name == "grok" and grok_chat:
                s = grok_chat(messages, temperature=temperature)
                if s and s.strip():
                    usage_counts["grok"] += 1
                    return s.strip(), "grok"
        except Exception as e:
            logger.error(f"[LLM Router][{name} error] {e}")
        return None, None

    for provider in provider_order:
        summary, model_name = try_provider(provider)
        if summary:
            return summary, model_name

    usage_counts["none"] += 1
    return "", "none"
