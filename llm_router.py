import os
import logging
from deepseek_client import deepseek_chat
from openai_client_wrapper import openai_chat
from xai_client import grok_chat
from moonshot_client import moonshot_chat

logger = logging.getLogger("llm_router")

def route_llm(messages, temperature=0.4, usage_counts=None, task_type="general"):
    usage_counts = usage_counts or {"deepseek": 0, "openai": 0, "grok": 0, "moonshot": 0, "none": 0}

    # New specialized routing based on task type - OPTIMIZED FOR PAID PROVIDERS
    if task_type == "enrichment" or task_type == "search":
        # Paid providers first: Grok → OpenAI → Moonshot → DeepSeek (free fallback)
        PROVIDER_PRIMARY = os.getenv("LLM_PRIMARY_ENRICHMENT", "grok").lower()
        PROVIDER_SECONDARY = os.getenv("LLM_SECONDARY_VERIFICATION", "openai").lower() 
        PROVIDER_TERTIARY = os.getenv("LLM_TERTIARY_FALLBACK", "moonshot").lower()
        PROVIDER_QUATERNARY = os.getenv("LLM_CRITICAL_VALIDATION", "deepseek").lower()
    else:
        # Advisor routing: prioritize paid providers - Grok → OpenAI → Moonshot → DeepSeek
        PROVIDER_PRIMARY = os.getenv("ADVISOR_PROVIDER_PRIMARY", "grok").lower()
        PROVIDER_SECONDARY = os.getenv("ADVISOR_PROVIDER_SECONDARY", "openai").lower()
        PROVIDER_TERTIARY = os.getenv("ADVISOR_PROVIDER_TERTIARY", "moonshot").lower()
        PROVIDER_QUATERNARY = os.getenv("ADVISOR_PROVIDER_QUATERNARY", "deepseek").lower()
    
    # Provider-specific timeouts (in seconds) - optimized for speed and reliability
    TIMEOUT_DEEPSEEK = int(os.getenv("DEEPSEEK_TIMEOUT", "10"))      # Fast, reliable
    TIMEOUT_OPENAI = int(os.getenv("OPENAI_TIMEOUT", "15"))         # Generally fast
    TIMEOUT_GROK = int(os.getenv("GROK_TIMEOUT", "12"))             # Medium speed
    TIMEOUT_MOONSHOT = int(os.getenv("MOONSHOT_TIMEOUT", "8"))      # Often slow, fail fast
    
    provider_order = [PROVIDER_PRIMARY, PROVIDER_SECONDARY, PROVIDER_TERTIARY, PROVIDER_QUATERNARY]

    logger.info(f"[LLM Router] Using provider order: {provider_order}")

    def try_provider(name):
        try:
            if name == "deepseek" and deepseek_chat:
                s = deepseek_chat(messages, temperature=temperature, timeout=TIMEOUT_DEEPSEEK)
                if s and s.strip():
                    usage_counts["deepseek"] += 1
                    return s.strip(), "deepseek"
            elif name == "openai" and openai_chat:
                s = openai_chat(messages, temperature=temperature, timeout=TIMEOUT_OPENAI)
                if s and s.strip():
                    usage_counts["openai"] += 1
                    return s.strip(), "openai"
            elif name == "grok" and grok_chat:
                s = grok_chat(messages, temperature=temperature, timeout=TIMEOUT_GROK)
                if s and s.strip():
                    usage_counts["grok"] += 1
                    return s.strip(), "grok"
            elif name == "moonshot" and moonshot_chat:
                s = moonshot_chat(messages, temperature=temperature, timeout=TIMEOUT_MOONSHOT)
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
    Uses paid providers first for better response quality: Grok → OpenAI → Moonshot → DeepSeek.
    """
    usage_counts = usage_counts or {"deepseek": 0, "openai": 0, "grok": 0, "moonshot": 0, "none": 0}
    
    # Prioritize paid providers for search
    search_provider = os.getenv("LLM_REAL_TIME_SEARCH", "grok").lower()
    fallback_provider = "openai"
    
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
    
    # Try primary provider first
    try:
        if search_provider == "grok" and grok_chat:
            result = grok_chat(search_messages, temperature=0.3, timeout=12)
            if result and result.strip():
                usage_counts["grok"] += 1
                return result.strip(), "grok"
        elif search_provider == "openai" and openai_chat:
            result = openai_chat(search_messages, temperature=0.3, timeout=15)
            if result and result.strip():
                usage_counts["openai"] += 1
                return result.strip(), "openai"
        elif search_provider == "moonshot" and moonshot_chat:
            result = moonshot_chat(search_messages, temperature=0.3, max_tokens=800, timeout=8)
            if result and result.strip():
                usage_counts["moonshot"] += 1
                return result.strip(), "moonshot"
        elif search_provider == "deepseek" and deepseek_chat:
            result = deepseek_chat(search_messages, temperature=0.3, timeout=10)
            if result and result.strip():
                usage_counts["deepseek"] += 1
                return result.strip(), "deepseek"
    except Exception as e:
        logger.warning(f"[LLM Search Router] Primary provider {search_provider} failed: {e}")
    
    # Try fallback provider
    logger.info(f"[LLM Search Router] Falling back to {fallback_provider}")
    try:
        if fallback_provider == "openai" and openai_chat:
            result = openai_chat(search_messages, temperature=0.3, timeout=15)
            if result and result.strip():
                usage_counts["openai"] += 1
                return result.strip(), "openai"
        elif fallback_provider == "grok" and grok_chat:
            result = grok_chat(search_messages, temperature=0.3, timeout=12)
            if result and result.strip():
                usage_counts["grok"] += 1
                return result.strip(), "grok"
        elif fallback_provider == "deepseek" and deepseek_chat:
            result = deepseek_chat(search_messages, temperature=0.3, timeout=10)
            if result and result.strip():
                usage_counts["deepseek"] += 1
                return result.strip(), "deepseek"
        elif fallback_provider == "moonshot" and moonshot_chat:
            result = moonshot_chat(search_messages, temperature=0.3, max_tokens=800, timeout=8)
            if result and result.strip():
                usage_counts["moonshot"] += 1
                return result.strip(), "moonshot"
    except Exception as e:
        logger.error(f"[LLM Search Router][{fallback_provider} error] {e}")
    
    usage_counts["none"] += 1
    return "Search temporarily unavailable", "none"

def route_llm_batch(alerts_batch, usage_counts=None):
    """
    Specialized routing for batch processing multiple alerts in 128k context.
    Uses paid providers first: Moonshot → OpenAI → Grok → DeepSeek.
    """
    usage_counts = usage_counts or {"deepseek": 0, "openai": 0, "grok": 0, "moonshot": 0, "none": 0}
    
    batch_provider = os.getenv("LLM_PRIMARY_ENRICHMENT", "grok").lower()
    
    # Create a batch processing prompt that takes advantage of 128k context
    batch_content = ""
    for i, alert in enumerate(alerts_batch[:20]):  # Process up to 20 alerts in one call
        batch_content += f"ALERT {i+1}:\n"
        batch_content += f"Title: {alert.get('title', 'N/A')}\n"
        batch_content += f"Summary: {alert.get('summary', 'N/A')}\n"
        batch_content += f"Location: {alert.get('city', 'N/A')}, {alert.get('country', 'N/A')}\n"
        batch_content += f"Link: {alert.get('link', 'N/A')}\n"
        batch_content += f"---\n"
    
    batch_messages = [
        {
            "role": "system",
            "content": "You are a threat intelligence analyst processing multiple security alerts in batch. For each alert, provide: threat_level (critical/high/moderate/low), category, key_entities, geographic_impact, and actionable_insights. Return structured analysis maintaining alert order."
        },
        {
            "role": "user", 
            "content": f"Analyze these {len(alerts_batch)} security alerts:\n\n{batch_content}\n\nProvide structured threat analysis for each alert:"
        }
    ]
    
    logger.info(f"[LLM Batch Router] Processing {len(alerts_batch)} alerts with {batch_provider}")
    
    try:
        if batch_provider == "grok" and grok_chat:
            result = grok_chat(batch_messages, temperature=0.2, timeout=12)
            if result and result.strip():
                usage_counts["grok"] += 1
                return result.strip(), "grok"
        elif batch_provider == "openai" and openai_chat:
            result = openai_chat(batch_messages, temperature=0.2, timeout=15)
            if result and result.strip():
                usage_counts["openai"] += 1
                return result.strip(), "openai"
        elif batch_provider == "moonshot" and moonshot_chat:
            result = moonshot_chat(batch_messages, temperature=0.2, max_tokens=2000, timeout=8)
            if result and result.strip():
                usage_counts["moonshot"] += 1
                return result.strip(), "moonshot"
        elif batch_provider == "deepseek" and deepseek_chat:
            result = deepseek_chat(batch_messages, temperature=0.2, timeout=10)
            if result and result.strip():
                usage_counts["deepseek"] += 1
                return result.strip(), "deepseek"
        
        # Fallback to single-alert processing if batch fails
        logger.warning("[LLM Batch Router] Batch processing failed, falling back to single alerts")
        return "Batch processing unavailable, use single alert processing", "none"
    except Exception as e:
        logger.error(f"[LLM Batch Router][{batch_provider} error] {e}")
    
    usage_counts["none"] += 1
    return "Batch processing temporarily unavailable", "none"