import os
import logging
from deepseek_client import deepseek_chat
from openai_client_wrapper import openai_chat
from xai_client import grok_chat
from moonshot_client import moonshot_chat

logger = logging.getLogger("llm_router")

def route_llm(messages, temperature=0.4, usage_counts=None, task_type="general"):
    usage_counts = usage_counts or {"deepseek": 0, "openai": 0, "grok": 0, "moonshot": 0, "none": 0}

    # New specialized routing based on task type
    if task_type == "enrichment" or task_type == "search":
        # Moonshot primary for enrichment and search
        PROVIDER_PRIMARY = os.getenv("LLM_PRIMARY_ENRICHMENT", "moonshot").lower()
        PROVIDER_SECONDARY = os.getenv("LLM_SECONDARY_VERIFICATION", "grok").lower() 
        PROVIDER_TERTIARY = os.getenv("LLM_TERTIARY_FALLBACK", "deepseek").lower()
        PROVIDER_QUATERNARY = os.getenv("LLM_CRITICAL_VALIDATION", "openai").lower()
    else:
        # Fallback to legacy configuration  
        PROVIDER_PRIMARY = os.getenv("ADVISOR_PROVIDER_PRIMARY", "moonshot").lower()
        PROVIDER_SECONDARY = os.getenv("ADVISOR_PROVIDER_SECONDARY", "grok").lower()
        PROVIDER_TERTIARY = os.getenv("ADVISOR_PROVIDER_TERTIARY", "deepseek").lower()
        PROVIDER_QUATERNARY = os.getenv("ADVISOR_PROVIDER_QUATERNARY", "openai").lower()
    
    provider_order = [PROVIDER_PRIMARY, PROVIDER_SECONDARY, PROVIDER_TERTIARY, PROVIDER_QUATERNARY]

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
            elif name == "moonshot" and moonshot_chat:
                s = moonshot_chat(messages, temperature=temperature)
                if s and s.strip():
                    usage_counts["moonshot"] += 1
                    return s.strip(), "moonshot"
        except Exception as e:
            logger.error(f"[LLM Router][{name} error] {e}")
        return None, None

    for provider in provider_order:
        summary, model_name = try_provider(provider)
        if summary:
            return summary, model_name

    usage_counts["none"] += 1
    return "", "none"

def route_llm_search(query, context="", usage_counts=None):
    """
    Specialized routing for real-time search and information retrieval.
    Uses Moonshot exclusively for search tasks as configured.
    """
    usage_counts = usage_counts or {"deepseek": 0, "openai": 0, "grok": 0, "moonshot": 0, "none": 0}
    
    search_provider = os.getenv("LLM_REAL_TIME_SEARCH", "moonshot").lower()
    
    search_messages = [
        {
            "role": "system", 
            "content": "You are a real-time threat intelligence search assistant. Provide accurate, current information about security threats, incidents, and advisories. Focus on factual details, locations, and actionable insights."
        },
        {
            "role": "user", 
            "content": f"Search Query: {query}\n\nContext: {context}\n\nProvide relevant threat intelligence information:"
        }
    ]
    
    logger.info(f"[LLM Search Router] Using {search_provider} for real-time search")
    
    try:
        if search_provider == "moonshot" and moonshot_chat:
            result = moonshot_chat(search_messages, temperature=0.3, max_tokens=800)
            if result and result.strip():
                usage_counts["moonshot"] += 1
                return result.strip(), "moonshot"
        elif search_provider == "deepseek" and deepseek_chat:
            result = deepseek_chat(search_messages, temperature=0.3)
            if result and result.strip():
                usage_counts["deepseek"] += 1
                return result.strip(), "deepseek"
        elif search_provider == "openai" and openai_chat:
            result = openai_chat(search_messages, temperature=0.3)
            if result and result.strip():
                usage_counts["openai"] += 1
                return result.strip(), "openai"
        elif search_provider == "grok" and grok_chat:
            result = grok_chat(search_messages, temperature=0.3)
            if result and result.strip():
                usage_counts["grok"] += 1
                return result.strip(), "grok"
    except Exception as e:
        logger.error(f"[LLM Search Router][{search_provider} error] {e}")
    
    usage_counts["none"] += 1
    return "Search temporarily unavailable", "none"
