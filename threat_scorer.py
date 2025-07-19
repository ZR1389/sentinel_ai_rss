import json
import os
import re
import threading
from functools import lru_cache
import logging
from risk_shared import (
    compute_keyword_weight,
    run_sentiment_analysis,
    run_forecast,
    run_legal_risk,
    run_cyber_ot_risk,
    run_environmental_epidemic_risk,
    enrich_log_db,  # new: logs to DB
)
from prompts import (
    THREAT_SCORER_SYSTEM_PROMPT,
)
from xai_client import grok_chat
from openai import OpenAI

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

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# Medium tier keywords (NEW)
MEDIUM_KEYWORDS = [
    "protest", "civil unrest", "looting", "roadblock", "arson", "sabotage"
]

CRITICAL_KEYWORDS = [
    "active shooter", "explosion", "suicide bombing", "mass killing"
]

HIGH_KEYWORDS = [
    "armed robbery", "kidnapping", "hostage", "carjacking"
]

def get_safe_prompt(alert_text, triggers, location):
    # ...unchanged...
    keys = set(re.findall(r"\{(\w+)\}", THREAT_SCORER_SYSTEM_PROMPT))
    values = {k: "Unknown" for k in keys}
    values.update({
        "alert_text": alert_text,
        "triggers": triggers,
        "location": location,
        "label": "Unrated"
    })
    try:
        return THREAT_SCORER_SYSTEM_PROMPT.format(**values)
    except KeyError as e:
        log.error(f"[ThreatScorer][PromptFormatError] {e}")
        return "ALERT: {alert_text}\nTriggers: {triggers}\nLocation: {location}\nLabel: {label}".format(**values)

def assess_threat_level(alert_text, triggers=None, location=None, alert_uuid=None, plan="FREE", enrich=True, user_email=None, source_alert=None):
    triggers = triggers or []
    alert_text_lower = alert_text.lower()

    # --- Use shared keyword scoring ---
    kw_score, kw_matches = compute_keyword_weight(alert_text, return_detail=True)
    input_excerpt = alert_text[:200]

    # Check CRITICAL
    for kw in CRITICAL_KEYWORDS:
        if re.search(rf'\b{re.escape(kw)}\b', alert_text_lower):
            result = {
                "label": "Critical",
                "threat_label": "Critical",
                "score": 100,
                "confidence": 1.0,
                "reasoning": f"Keyword '{kw}' matched.",
                "model_used": "rules",
                "keyword_weight": kw_score,
                "matched_keywords": kw_matches,
                "input_excerpt": input_excerpt,
                "location": location,
                "source_alert": source_alert,
            }
            if enrich:
                result["sentiment"] = run_sentiment_analysis(alert_text)
                result["forecast"] = run_forecast(location, alert_text)
                result["legal_risk"] = run_legal_risk(alert_text, location)
                result["cyber_ot_risk"] = run_cyber_ot_risk(alert_text, location)
                result["environmental_epidemic_risk"] = run_environmental_epidemic_risk(alert_text, location)
            enrich_log_db(result, enrichment_type="critical_rule", user_email=user_email)
            log.info(f"[ThreatScorer] Critical keyword matched: '{kw}' in '{input_excerpt}'")
            return result

    # Check HIGH
    for kw in HIGH_KEYWORDS:
        if re.search(rf'\b{re.escape(kw)}\b', alert_text_lower):
            result = {
                "label": "High",
                "threat_label": "High",
                "score": 85,
                "confidence": 0.95,
                "reasoning": f"Keyword '{kw}' matched.",
                "model_used": "rules",
                "keyword_weight": kw_score,
                "matched_keywords": kw_matches,
                "input_excerpt": input_excerpt,
                "location": location,
                "source_alert": source_alert,
            }
            if enrich:
                result["sentiment"] = run_sentiment_analysis(alert_text)
                result["forecast"] = run_forecast(location, alert_text)
                result["legal_risk"] = run_legal_risk(alert_text, location)
                result["cyber_ot_risk"] = run_cyber_ot_risk(alert_text, location)
                result["environmental_epidemic_risk"] = run_environmental_epidemic_risk(alert_text, location)
            enrich_log_db(result, enrichment_type="high_rule", user_email=user_email)
            log.info(f"[ThreatScorer] High keyword matched: '{kw}' in '{input_excerpt}'")
            return result

    # Check MEDIUM (NEW)
    for kw in MEDIUM_KEYWORDS:
        if re.search(rf'\b{re.escape(kw)}\b', alert_text_lower):
            result = {
                "label": "Medium",
                "threat_label": "Medium",
                "score": 70,
                "confidence": 0.85,
                "reasoning": f"Keyword '{kw}' matched.",
                "model_used": "rules",
                "keyword_weight": kw_score,
                "matched_keywords": kw_matches,
                "input_excerpt": input_excerpt,
                "location": location,
                "source_alert": source_alert,
            }
            if enrich:
                result["sentiment"] = run_sentiment_analysis(alert_text)
                result["forecast"] = run_forecast(location, alert_text)
                result["legal_risk"] = run_legal_risk(alert_text, location)
                result["cyber_ot_risk"] = run_cyber_ot_risk(alert_text, location)
                result["environmental_epidemic_risk"] = run_environmental_epidemic_risk(alert_text, location)
            enrich_log_db(result, enrichment_type="medium_rule", user_email=user_email)
            log.info(f"[ThreatScorer] Medium keyword matched: '{kw}' in '{input_excerpt}'")
            return result

    def llm_score():
        prompt = get_safe_prompt(alert_text, triggers, location)
        messages = [
            {"role": "system", "content": ""},
            {"role": "user", "content": prompt}
        ]
        try:
            result = grok_chat(messages, temperature=0.2, max_tokens=120)
            if result:
                try:
                    data = json.loads(result)
                except Exception as e:
                    log.error(f"[ThreatScorer][Grok][JSONDecodeError] {e} | result: {result}")
                    return None
                output = {
                    "label": data.get("label", "Unrated"),
                    "threat_label": data.get("label", "Unrated"),
                    "score": data.get("score", 0) + kw_score,
                    "confidence": data.get("confidence", 0.7),
                    "reasoning": data.get("reasoning", ""),
                    "llm_explanation": data.get("explanation", data.get("reasoning", "")),
                    "model_used": "grok",
                    "keyword_weight": kw_score,
                    "matched_keywords": kw_matches,
                    "input_excerpt": input_excerpt,
                    "location": location,
                    "source_alert": source_alert,
                }
                if enrich:
                    output["sentiment"] = run_sentiment_analysis(alert_text)
                    output["forecast"] = run_forecast(location, alert_text)
                    output["legal_risk"] = run_legal_risk(alert_text, location)
                    output["cyber_ot_risk"] = run_cyber_ot_risk(alert_text, location)
                    output["environmental_epidemic_risk"] = run_environmental_epidemic_risk(alert_text, location)
                enrich_log_db(output, enrichment_type="llm_grok", user_email=user_email)
                log.info("[ThreatScorer][Grok] LLM scoring completed.")
                return output
        except Exception as e:
            log.error(f"[ThreatScorer][Grok] {e}")
        if openai_client:
            try:
                response = openai_client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=messages,
                    temperature=0.2,
                    max_tokens=120
                )
                reply = response.choices[0].message.content.strip()
                try:
                    data = json.loads(reply)
                except Exception as e:
                    log.error(f"[ThreatScorer][OpenAI][JSONDecodeError] {e} | reply: {reply}")
                    return None
                output = {
                    "label": data.get("label", "Unrated"),
                    "threat_label": data.get("label", "Unrated"),
                    "score": data.get("score", 0) + kw_score,
                    "confidence": data.get("confidence", 0.7),
                    "reasoning": data.get("reasoning", ""),
                    "llm_explanation": data.get("explanation", data.get("reasoning", "")),
                    "model_used": "openai",
                    "keyword_weight": kw_score,
                    "matched_keywords": kw_matches,
                    "input_excerpt": input_excerpt,
                    "location": location,
                    "source_alert": source_alert,
                }
                if enrich:
                    output["sentiment"] = run_sentiment_analysis(alert_text)
                    output["forecast"] = run_forecast(location, alert_text)
                    output["legal_risk"] = run_legal_risk(alert_text, location)
                    output["cyber_ot_risk"] = run_cyber_ot_risk(alert_text, location)
                    output["environmental_epidemic_risk"] = run_environmental_epidemic_risk(alert_text, location)
                enrich_log_db(output, enrichment_type="llm_openai", user_email=user_email)
                log.info("[ThreatScorer][OpenAI] LLM scoring completed.")
                return output
            except Exception as e:
                log.error(f"[ThreatScorer][OpenAI] {e}")
        return None

    result = [None]
    def run_llm():
        result[0] = llm_score()

    t = threading.Thread(target=run_llm)
    t.start()
    t.join(5)
    if t.is_alive():
        base = {
            "label": "Moderate",
            "threat_label": "Moderate",
            "score": 60 + kw_score,
            "confidence": 0.7,
            "reasoning": "Timed out or no critical/high/medium keywords, rules fallback.",
            "model_used": "timeout",
            "keyword_weight": kw_score,
            "matched_keywords": kw_matches,
            "input_excerpt": input_excerpt,
            "location": location,
            "source_alert": source_alert,
        }
        if enrich:
            base["sentiment"] = run_sentiment_analysis(alert_text)
            base["forecast"] = run_forecast(location, alert_text)
            base["legal_risk"] = run_legal_risk(alert_text, location)
            base["cyber_ot_risk"] = run_cyber_ot_risk(alert_text, location)
            base["environmental_epidemic_risk"] = run_environmental_epidemic_risk(alert_text, location)
        enrich_log_db(base, enrichment_type="timeout", user_email=user_email)
        log.warning("[ThreatScorer] LLM scoring timed out. Using rules fallback.")
        return base
    if result[0]:
        return result[0]

    base = {
        "label": "Moderate",
        "threat_label": "Moderate",
        "score": 60 + kw_score,
        "confidence": 0.7,
        "reasoning": "No critical, high, or medium keywords, rules fallback.",
        "model_used": "rules",
        "keyword_weight": kw_score,
        "matched_keywords": kw_matches,
        "input_excerpt": input_excerpt,
        "location": location,
        "source_alert": source_alert,
    }
    if enrich:
        base["sentiment"] = run_sentiment_analysis(alert_text)
        base["forecast"] = run_forecast(location, alert_text)
        base["legal_risk"] = run_legal_risk(alert_text, location)
        base["cyber_ot_risk"] = run_cyber_ot_risk(alert_text, location)
        base["environmental_epidemic_risk"] = run_environmental_epidemic_risk(alert_text, location)
    enrich_log_db(base, enrichment_type="fallback", user_email=user_email)
    log.info("[ThreatScorer] No LLM or keyword match. Using rules fallback.")
    return base