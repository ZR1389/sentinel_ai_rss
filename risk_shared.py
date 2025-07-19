import re
import os
import json
import time
import psycopg2
from datetime import datetime
from functools import lru_cache
import logging

# --- Logging configuration ---
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

RAILWAY_ENV = os.getenv("RAILWAY_ENVIRONMENT")
if RAILWAY_ENV:
    log.info(f"Running in Railway environment: {RAILWAY_ENV}")
else:
    log.info("Running outside Railway or RAILWAY_ENVIRONMENT not set.")

# ---- KEYWORD WEIGHTS ----
KEYWORD_WEIGHTS = {
    "assassination": 30,
    "bombing": 25,
    "explosion": 25,
    "kidnapping": 20,
    "active shooter": 35,
    "armed robbery": 15,
    "riot": 15,
    "civil unrest": 12,
    "terrorism": 18,
    "hostage": 20,
    "carjacking": 14,
    "protest": 8,
    "shooting": 12,
    "looting": 10,
    "evacuation": 8,
    "martial law": 13,
    "power outage": 7,
    "IED": 18,
    "arson": 10,
    "sabotage": 11,
    "roadblock": 7,
    "corruption": 5,
    # ...add more as needed
}

# ---- SHARED ENRICHMENT FUNCTIONS (with CACHING) ----

def _cache_key(*args, **kwargs):
    # Simple cache key generator for enrichment caching
    key = repr(args) + repr(sorted(kwargs.items()))
    return hash(key)

@lru_cache(maxsize=512)
def run_sentiment_analysis_cached(text):
    from xai_client import grok_chat
    from prompts import SENTIMENT_ANALYSIS_PROMPT
    prompt = SENTIMENT_ANALYSIS_PROMPT.format(incident=text)
    messages = [{"role": "system", "content": ""}, {"role": "user", "content": prompt}]
    try:
        return grok_chat(messages, temperature=0.2, max_tokens=60)
    except Exception as e:
        log.error(f"[SentimentAnalysisError] {e}")
        return f"[SentimentAnalysisError] {e}"

def run_sentiment_analysis(text):
    # Use cache for same text
    return run_sentiment_analysis_cached(text)

@lru_cache(maxsize=512)
def run_forecast_cached(region, input_data, user_message):
    from xai_client import grok_chat
    from prompts import PROACTIVE_FORECAST_PROMPT
    prompt = PROACTIVE_FORECAST_PROMPT.format(region=region, input_data=json.dumps(input_data), user_message=user_message)
    messages = [{"role": "system", "content": ""}, {"role": "user", "content": prompt}]
    try:
        return grok_chat(messages, temperature=0.2, max_tokens=80)
    except Exception as e:
        log.error(f"[ForecastError] {e}")
        return f"[ForecastError] {e}"

def run_forecast(region, input_data, user_message=None):
    # Use cache for same input
    user_msg = user_message if user_message else str(input_data)
    return run_forecast_cached(region, json.dumps(input_data, sort_keys=True), user_msg)

@lru_cache(maxsize=512)
def run_legal_risk_cached(text, region):
    from xai_client import grok_chat
    from prompts import LEGAL_REGULATORY_RISK_PROMPT
    prompt = LEGAL_REGULATORY_RISK_PROMPT.format(incident=text, region=region)
    messages = [{"role": "system", "content": ""}, {"role": "user", "content": prompt}]
    try:
        return grok_chat(messages, temperature=0.2, max_tokens=80)
    except Exception as e:
        log.error(f"[LegalRiskError] {e}")
        return f"[LegalRiskError] {e}"

def run_legal_risk(text, region):
    return run_legal_risk_cached(text, region)

@lru_cache(maxsize=512)
def run_cyber_ot_risk_cached(text, region):
    from xai_client import grok_chat
    from prompts import CYBER_OT_RISK_PROMPT
    prompt = CYBER_OT_RISK_PROMPT.format(incident=text, region=region)
    messages = [{"role": "system", "content": ""}, {"role": "user", "content": prompt}]
    try:
        return grok_chat(messages, temperature=0.2, max_tokens=80)
    except Exception as e:
        log.error(f"[CyberOTRiskError] {e}")
        return f"[CyberOTRiskError] {e}"

def run_cyber_ot_risk(text, region):
    return run_cyber_ot_risk_cached(text, region)

@lru_cache(maxsize=512)
def run_environmental_epidemic_risk_cached(text, region):
    from xai_client import grok_chat
    from prompts import ENVIRONMENTAL_EPIDEMIC_RISK_PROMPT
    prompt = ENVIRONMENTAL_EPIDEMIC_RISK_PROMPT.format(incident=text, region=region)
    messages = [{"role": "system", "content": ""}, {"role": "user", "content": prompt}]
    try:
        return grok_chat(messages, temperature=0.2, max_tokens=80)
    except Exception as e:
        log.error(f"[EnvEpidemicRiskError] {e}")
        return f"[EnvEpidemicRiskError] {e}"

def run_environmental_epidemic_risk(text, region):
    return run_environmental_epidemic_risk_cached(text, region)

# ---- ENRICHMENT LOGGING ----

def enrich_log(
    alert,
    region=None,
    city=None,
    source=None,
    user_email=None,
    log_path=None
):
    """
    Log enriched alert data to a JSONL file for analyst review, retraining, or audit.
    Includes region, city, source, and user_email for better metadata.
    Logging only happens if LOG_ALERTS=true in env.
    log_path can be set via ENRICH_LOG_PATH env var, else defaults to logs/alert_enrichments.jsonl.
    """
    if os.getenv("LOG_ALERTS", "true").lower() != "true":
        return

    if log_path is None:
        log_path = os.getenv("ENRICH_LOG_PATH", "logs/alert_enrichments.jsonl")

    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    enrich_record = {
        "timestamp": datetime.utcnow().isoformat(),
        "region": region if region else alert.get('region'),
        "city": city if city else alert.get('city'),
        "source": source if source else alert.get('source'),
        "user_email": user_email,
        "alert": alert
    }
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(enrich_record, ensure_ascii=False) + "\n")
    except Exception as e:
        log.error(f"[enrich_log][FileError] {e}")

def enrich_log_db(
    enrichment_result,
    enrichment_type="",
    user_email=None,
    db_url=None
):
    """
    Log enrichment result to a database table (enrichment_logs) for audit, quota, and analytics.
    """
    db_url = db_url or os.getenv("DATABASE_URL")
    if not db_url:
        log.warning("DATABASE_URL not set. Falling back to file logging for enrichment logs.")
        enrich_log(
            enrichment_result,
            region=enrichment_result.get('location'),
            source=enrichment_result.get('model_used'),
            user_email=user_email
        )
        return
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO enrichment_logs 
            (timestamp, enrichment_type, user_email, result_json)
            VALUES (%s, %s, %s, %s)
        """, (
            datetime.utcnow().isoformat(),
            enrichment_type,
            user_email,
            json.dumps(enrichment_result, ensure_ascii=False)
        ))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        log.error(f"[enrich_log_db][DBError] {e}")
        # Fallback to file log if DB fails
        enrich_log(
            enrichment_result,
            region=enrichment_result.get('location'),
            source=enrichment_result.get('model_used'),
            user_email=user_email
        )

# ---- SHARED KEYWORD SCORING ----

def compute_keyword_weight(text, return_detail=False):
    """
    Compute the total keyword weight for a given text using the shared dictionary, using regex for precise word boundaries.
    If return_detail=True, returns (score, matched_keywords).
    """
    score = 0
    matched = []
    text_lower = text.lower()
    for k, w in KEYWORD_WEIGHTS.items():
        # Use regex for word boundary matching (case-insensitive)
        if re.search(rf'\b{k}\b', text_lower, re.IGNORECASE):
            score += w
            matched.append(k)
    if return_detail:
        return score, matched
    return score