import os
import time
import json
import re
import hashlib
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

import pycountry
from dotenv import load_dotenv
import numpy as np
from xai_client import grok_chat
from openai import OpenAI
from prompts import (
    THREAT_CATEGORY_PROMPT,
    THREAT_CATEGORY_SYSTEM_PROMPT,
    THREAT_SUBCATEGORY_PROMPT,
    THREAT_DETECT_COUNTRY_PROMPT,
    THREAT_DETECT_CITY_PROMPT,
    THREAT_SUMMARIZE_SYSTEM_PROMPT,
    PROACTIVE_FORECAST_PROMPT,
    HISTORICAL_COMPARISON_PROMPT,
    SENTIMENT_ANALYSIS_PROMPT,
    LEGAL_REGULATORY_RISK_PROMPT,
    ACCESSIBILITY_INCLUSION_PROMPT,
    PROFESSION_AWARE_PROMPT,
    USER_CONTEXT_PROMPT,
    SYSTEM_PROMPT,
    CYBER_OT_RISK_PROMPT,
    ENVIRONMENTAL_EPIDEMIC_RISK_PROMPT,
)

from city_utils import fuzzy_match_city, normalize_city
from plan_utils import (
    get_plan_limits,
    check_user_summary_quota,
    increment_user_summary_usage,
    check_session_summary_quota,
    increment_session_summary_usage
)
import psycopg2
import logging

# === SHARED ENRICHMENT LOGIC IMPORTS ===
from risk_shared import (
    compute_keyword_weight,
    enrich_log,
    run_sentiment_analysis,
    run_forecast,
    run_legal_risk,
    run_cyber_ot_risk,
    run_environmental_epidemic_risk,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---- ENVIRONMENT & CONFIG ----
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

RAILWAY_ENV = os.getenv("RAILWAY_ENVIRONMENT")
if RAILWAY_ENV:
    logger.info(f"Running in Railway environment: {RAILWAY_ENV}")
else:
    logger.info("Running outside Railway or RAILWAY_ENVIRONMENT not set.")

if not OPENAI_API_KEY:
    logger.warning("OPENAI_API_KEY not set! LLM features will be disabled.")
if not DATABASE_URL:
    logger.warning("DATABASE_URL not set! Database operations may fail.")

GROK_MODEL = os.getenv("GROK_MODEL", "grok-3-mini")
TEMPERATURE = 0.4
ENABLE_SEMANTIC_DEDUP = True
SEMANTIC_DEDUP_THRESHOLD = float(os.getenv("SEMANTIC_DEDUP_THRESHOLD", 0.9))

CATEGORIES = [
    "Crime", "Terrorism", "Civil Unrest", "Cyber",
    "Infrastructure", "Environmental", "Epidemic", "Other"
]

COUNTRY_LIST = [country.name for country in pycountry.countries]
CITY_LIST = [
    "New York", "London", "Paris", "Berlin", "Moscow", "Mumbai", "Beijing",
    "Cape Town", "Lagos", "Mexico City", "Tokyo", "Istanbul", "Jakarta", "Los Angeles",
    "Buenos Aires", "Cairo", "Bangkok", "Madrid", "Rome", "Sydney", "Toronto", "Chicago"
]

TRIGGER_KEYWORDS = [
    "armed robbery", "civil unrest", "kidnapping", "protest", "evacuation",
    "martial law", "carjacking", "load shedding", "corruption", "terrorism",
    "shooting", "power outage", "IED", "riot", "hostage", "assault", "gunfire",
    "explosion", "looting", "roadblock", "arson", "sabotage"
]

# ---- USAGE LOGGING ----
def log_threat_engine_usage(email, plan, action_type, status, region=None, summary_text=None):
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO threat_engine_usage
            (email, region, plan, action_type, status, summary_excerpt)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            email,
            region,
            plan,
            action_type,
            status,
            summary_text[:120] if summary_text else None
        ))
        
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"[Threat engine usage logging error] {e}")

# ---- PLAN LOGIC ----

def can_user_summarize(user_email, plan_limits, feature="custom_pdf_briefings_frequency"):
    if not check_user_summary_quota(user_email, plan_limits, feature):
        logger.info(f"[Quota] User {user_email} exceeded monthly summary quota")
        return False
    increment_user_summary_usage(user_email)
    return True

def can_session_summarize(session_id, plan_limits, session_quota=2):
    if not check_session_summary_quota(session_id, plan_limits, quota=session_quota):
        logger.info(f"[Quota] Session {session_id} exceeded session summary quota")
        return False
    increment_session_summary_usage(session_id)
    return True

def should_summarize_alert(alert, plan_limits):
    return True

# ---- THREAT ENGINE CORE LOGIC ----

def extract_source_from_url(url):
    try:
        from urllib.parse import urlparse
        domain = urlparse(url).netloc.lower()
        if "reliefweb" in domain:
            return "ReliefWeb"
        elif "aljazeera" in domain:
            return "Al Jazeera"
        elif "crisis24" in domain:
            return "Crisis24"
        if domain:
            return domain
        return None
    except Exception:
        return None

def save_threat_log(alert, summary, category=None, category_confidence=None, severity=None,
                    country=None, city=None, triggers=None, source="grok-3-mini", error=None):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    log_entry = {
        "timestamp": timestamp,
        "source": source,
        "alert": alert,
        "summary": summary,
        "category": category,
        "category_confidence": category_confidence,
        "severity": severity,
        "country": country,
        "city": city,
        "triggers": triggers,
        "error": error
    }
    os.makedirs("logs", exist_ok=True)
    log_path = "logs/threat_engine_log.json"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

def extract_triggers(alerts):
    keywords = set()
    for alert in alerts:
        for field in ['title', 'summary']:
            text = alert.get(field, "")
            # Use shared keyword logic for precision and explainability
            _, matched_keywords = compute_keyword_weight(text, return_detail=True)
            keywords.update(matched_keywords)
    return list(keywords)

def classify_threat_category(text):
    prompt = THREAT_CATEGORY_PROMPT.format(incident=text)
    messages = [
        {"role": "system", "content": THREAT_CATEGORY_SYSTEM_PROMPT},
        {"role": "user", "content": prompt}
    ]
    try:
        result = grok_chat(messages, temperature=0.0, max_tokens=60)
        if result:
            data = json.loads(result)
            cat = data.get("category", "Other")
            conf = float(data.get("confidence", 0.5))
            if cat not in CATEGORIES:
                cat = "Other"
            return cat, conf
    except Exception as e:
        logger.error(f"[Grok classify error] {e}")
    if openai_client:
        try:
            response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages,
                temperature=0.0,
                max_tokens=60
            )
            reply = response.choices[0].message.content.strip()
            data = json.loads(reply)
            cat = data.get("category", "Other")
            conf = float(data.get("confidence", 0.5))
            if cat not in CATEGORIES:
                cat = "Other"
            return cat, conf
        except Exception as e:
            logger.error(f"[OpenAI classify error] {e}")
    return "Other", 0.5

def extract_subcategory(text, category):
    prompt = THREAT_SUBCATEGORY_PROMPT.format(category=category, incident=text)
    messages = [
        {"role": "system", "content": THREAT_CATEGORY_SYSTEM_PROMPT},
        {"role": "user", "content": prompt}
    ]
    try:
        result = grok_chat(messages, temperature=0.0, max_tokens=16)
        subcat = result.strip()
        if not subcat:
            return "Unspecified"
        return subcat
    except Exception as e:
        logger.error(f"[Grok subcategory error] {e}")
    if openai_client:
        try:
            response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages,
                temperature=0.0,
                max_tokens=16
            )
            subcat = response.choices[0].message.content.strip()
            if not subcat:
                return "Unspecified"
            return subcat
        except Exception as e:
            logger.error(f"[OpenAI subcategory error] {e}")
    return "Unspecified"

def detect_country(text):
    prompt = THREAT_DETECT_COUNTRY_PROMPT.format(incident=text)
    messages = [
        {"role": "system", "content": THREAT_CATEGORY_SYSTEM_PROMPT},
        {"role": "user", "content": prompt}
    ]
    try:
        result = grok_chat(messages, temperature=0.0, max_tokens=20)
        result = result.strip()
        if result and result.lower() != "none":
            return result
    except Exception as e:
        logger.error(f"[Country extraction error, Grok] {e}")
    if openai_client:
        try:
            response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages,
                temperature=0.0,
                max_tokens=20
            )
            reply = response.choices[0].message.content.strip()
            if reply and reply.lower() != "none":
                return reply
        except Exception as e:
            logger.error(f"[Country extraction error, OpenAI] {e}")
    for country in COUNTRY_LIST:
        if re.search(r"\b" + re.escape(country) + r"\b", text, re.IGNORECASE):
            return country
    return None

def detect_city(text):
    prompt = THREAT_DETECT_CITY_PROMPT.format(incident=text)
    messages = [
        {"role": "system", "content": THREAT_CATEGORY_SYSTEM_PROMPT},
        {"role": "user", "content": prompt}
    ]
    try:
        result = grok_chat(messages, temperature=0.0, max_tokens=20)
        result = result.strip()
        if result and result.lower() != "none":
            return result
    except Exception as e:
        logger.error(f"[City extraction error, Grok] {e}")
    if openai_client:
        try:
            response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages,
                temperature=0.0,
                max_tokens=20
            )
            reply = response.choices[0].message.content.strip()
            if reply and reply.lower() != "none":
                return reply
        except Exception as e:
            logger.error(f"[City extraction error, OpenAI] {e}")
    match = fuzzy_match_city(text, CITY_LIST, cutoff=0.8)
    if match:
        return match
    for city in CITY_LIST:
        if re.search(r"\b" + re.escape(city) + r"\b", text, re.IGNORECASE):
            return city
    return None

def alert_hash(alert):
    text = (alert.get("title", "") + "|" + alert.get("summary", "")).strip().lower()
    return hashlib.sha1(text.encode("utf-8")).hexdigest()

def get_embedding(text, openai_client):
    response = openai_client.embeddings.create(
        input=[text],
        model="text-embedding-ada-002"
    )
    return np.array(response.data[0].embedding)

def cosine_similarity(vec1, vec2):
    return float(np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2)))

def update_alert(existing_alert, new_alert):
    if 'history' not in existing_alert:
        existing_alert['history'] = []
    existing_alert['history'].append({k: v for k, v in existing_alert.items() if k != 'history'})
    for key, value in new_alert.items():
        if key != 'history':
            existing_alert[key] = value
    existing_alert['version'] = existing_alert.get('version', 1) + 1
    return existing_alert

def deduplicate_alerts(alerts, existing_alerts, openai_client=None, sim_threshold=SEMANTIC_DEDUP_THRESHOLD, enable_semantic=True):
    known_hashes = {alert_hash(a): a for a in existing_alerts}
    deduped_alerts = []
    known_embeddings = []
    if enable_semantic and openai_client and existing_alerts:
        known_embeddings = [
            get_embedding(a.get("title", "") + " " + a.get("summary", ""), openai_client)
            for a in existing_alerts
        ]
    for alert in alerts:
        h = alert_hash(alert)
        if h in known_hashes:
            existing = known_hashes[h]
            for field in ("title", "summary"):
                if alert.get(field, "") != existing.get(field, ""):
                    update_alert(existing, alert)
                    break
            continue
        if enable_semantic and openai_client and known_embeddings:
            emb = get_embedding(alert.get("title", "") + " " + alert.get("summary", ""), openai_client)
            if any(cosine_similarity(emb, kemb) > sim_threshold for kemb in known_embeddings):
                continue
            known_embeddings.append(emb)
        deduped_alerts.append(alert)
        known_hashes[h] = alert
    return deduped_alerts

# --- New enrichment functions for advanced prompts ---
# NOW USING SHARED ENRICHMENT FUNCTIONS via risk_shared.py
# run_forecast, run_sentiment_analysis, run_legal_risk, run_cyber_ot_risk, run_environmental_epidemic_risk
# Other advanced prompt enrichments left as-is for now

def run_historical_comparison(incident, region):
    prompt = HISTORICAL_COMPARISON_PROMPT.format(incident=incident, region=region)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}]
    try:
        return grok_chat(messages, temperature=0.2, max_tokens=80)
    except Exception as e:
        logger.error(f"[run_historical_comparison error] {e}")
        return "No historical comparison available."

def run_accessibility_inclusion(region, threats, user_message):
    prompt = ACCESSIBILITY_INCLUSION_PROMPT.format(region=region, threats=threats, user_message=user_message)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}]
    try:
        return grok_chat(messages, temperature=0.2, max_tokens=100)
    except Exception as e:
        logger.error(f"[run_accessibility_inclusion error] {e}")
        return "No accessibility/inclusion info available."

def run_profession_aware(profession, region, threats, user_message):
    prompt = PROFESSION_AWARE_PROMPT.format(profession=profession, region=region, threats=threats, user_message=user_message)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}]
    try:
        return grok_chat(messages, temperature=0.2, max_tokens=100)
    except Exception as e:
        logger.error(f"[run_profession_aware error] {e}")
        return "No profession-specific info available."

def summarize_single_alert(alert, user_email=None, plan=None, region=None, user_message=None, profession=None):
    title = alert.get("title", "")
    summary = alert.get("summary", "")
    title = str(title) if not isinstance(title, str) else title
    summary = str(summary) if not isinstance(summary, str) else summary
    full_text = f"{title}\n{summary}".strip()
    combined_text = f"{title} {summary}"

    alert["source_name"] = (
        alert.get("source_name")
        or alert.get("source")
        or extract_source_from_url(alert.get("link", ""))
        or "Unknown"
    )
    if "version" not in alert:
        alert["version"] = 1

    # --- Compute keyword score and add to alert (shared logic) ---
    kw_score, kw_matches = compute_keyword_weight(combined_text, return_detail=True)
    alert["keyword_weight"] = kw_score
    alert["matched_keywords"] = kw_matches

    messages = [
        {"role": "system", "content": THREAT_SUMMARIZE_SYSTEM_PROMPT},
        {"role": "user", "content": full_text}
    ]

    g_summary, g_error = None, None
    try:
        g_summary = grok_chat(messages, temperature=TEMPERATURE)
    except Exception as e:
        g_error = str(e)
        logger.error(f"[Grok summary error] {e}")

    summary_out = g_summary
    source_used = "grok-3-mini"
    if not summary_out and openai_client:
        try:
            response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages,
                temperature=TEMPERATURE
            )
            summary_out = response.choices[0].message.content.strip()
            source_used = "openai"
        except Exception as e:
            logger.error(f"[OpenAI fallback error] {e}")
            summary_out = "⚠️ Failed to generate summary"
            source_used = "final-fail"

    if not summary_out:
        summary_out = "⚠️ Failed to generate summary"
        source_used = "final-fail"

    try:
        category, confidence = classify_threat_category(combined_text)
    except Exception as e:
        logger.error(f"[Categorization error] {e}")
        category, confidence = "Other", 0.5

    try:
        subcategory = extract_subcategory(combined_text, category)
    except Exception as e:
        logger.error(f"[Subcategory extraction error] {e}")
        subcategory = "Unspecified"

    threat_label = alert.get("threat_label") or "Moderate"
    threat_score = alert.get("score") if alert.get("score") is not None else 60
    threat_confidence = alert.get("confidence") if alert.get("confidence") is not None else 0.7
    threat_reasoning = alert.get("reasoning", "")

    try:
        country = detect_country(combined_text)
    except Exception as e:
        logger.error(f"[Country extraction failure] {e}")
        country = None
    try:
        city = detect_city(combined_text)
    except Exception as e:
        logger.error(f"[City extraction failure] {e}")
        city = None

    try:
        triggers = extract_triggers([alert])
    except Exception as e:
        logger.error(f"[Trigger extraction failure] {e}")
        triggers = []

    # --- Advanced enrichment ---
    forecast = run_forecast(region or country, alert, user_message or summary)
    historical = run_historical_comparison(summary, region or country)
    sentiment = run_sentiment_analysis(summary)
    legal_risk = run_legal_risk(summary, region or country)
    inclusion_info = run_accessibility_inclusion(region or country, triggers, user_message or summary)
    profession_info = None
    if profession:
        profession_info = run_profession_aware(profession, region or country, triggers, user_message or summary)
    cyber_ot_risk = run_cyber_ot_risk(summary, region or country)
    environmental_epidemic_risk = run_environmental_epidemic_risk(summary, region or country)

    save_threat_log(
        alert, summary_out, category=category, category_confidence=confidence,
        severity=threat_label, country=country, city=city, triggers=triggers,
        source=source_used, error=g_error
    )

    # Unified enrichment logging (optional, for full audit):
    enrich_log(
        alert,
        region=country,
        city=city,
        source=source_used,
        user_email=user_email
    )

    reasoning = (
        f"Category: {category} ({confidence:.2f}), "
        f"Subcategory: {subcategory}, "
        f"Threat Label: {threat_label}, "
        f"Score: {threat_score}, "
        f"Detected Triggers: {', '.join(triggers) if triggers else 'None'}"
    )

    review_flag = False
    if threat_confidence < 0.5:
        review_flag = True
    if threat_label.lower() == "high" and (not country or not city):
        review_flag = True
    if summary_out.startswith("⚠️"):
        review_flag = True

    if user_email:
        log_threat_engine_usage(
            email=user_email,
            plan=plan,
            action_type="threat_summary",
            status="success" if not summary_out.startswith("⚠️") else "error",
            region=country or None,
            summary_text=summary_out
        )

    return (
        summary_out, category, subcategory, confidence, threat_label, threat_score,
        threat_confidence, reasoning, country, city, triggers, review_flag,
        forecast, historical, sentiment, legal_risk, inclusion_info, profession_info,
        cyber_ot_risk, environmental_epidemic_risk
    )

def summarize_single_alert_with_retries(alert, user_email=None, plan=None, region=None, user_message=None, profession=None, max_retries=3):
    attempt = 0
    while attempt < max_retries:
        try:
            return summarize_single_alert(alert, user_email=user_email, plan=plan, region=region, user_message=user_message, profession=profession)
        except Exception as e:
            attempt += 1
            logger.error(f"[summarize_single_alert] Retry {attempt} failed: {e}")
    return None

def summarize_alerts(
    alerts,
    user_email,
    session_id,
    cache_path="cache/enriched_alerts.json",
    enable_semantic=ENABLE_SEMANTIC_DEDUP,
    failed_cache_path="cache/alerts_failed.json",
    user_message=None,
    profession=None
):
    if not user_email:
        raise ValueError("user_email is required for plan-based logic.")
    plan_limits = get_plan_limits(user_email)
    plan = plan_limits.get("plan", "FREE") if isinstance(plan_limits, dict) else "FREE"
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            cached_alerts = json.load(f)
    else:
        cached_alerts = []

    new_alerts = deduplicate_alerts(
        alerts,
        existing_alerts=cached_alerts,
        openai_client=openai_client if enable_semantic else None,
        sim_threshold=SEMANTIC_DEDUP_THRESHOLD,
        enable_semantic=enable_semantic,
    )

    if not new_alerts:
        return cached_alerts

    summarized = []
    failed_alerts = []
    failed_alerts_lock = threading.Lock()

    def process(alert):
        if should_summarize_alert(alert, plan_limits):
            user_ok = can_user_summarize(user_email, plan_limits)
            session_ok = can_session_summarize(session_id, plan_limits)
            if user_ok and session_ok:
                result = summarize_single_alert_with_retries(
                    alert,
                    user_email=user_email,
                    plan=plan,
                    region=alert.get("country"),
                    user_message=user_message,
                    profession=profession,
                    max_retries=3
                )
                if result is None:
                    with failed_alerts_lock:
                        failed_alerts.append(alert)
                    log_threat_engine_usage(
                        email=user_email,
                        plan=plan,
                        action_type="threat_summary",
                        status="error",
                        region=alert.get("country"),
                        summary_text=None
                    )
                    return None
                (
                    summary, category, subcategory, confidence, threat_label, threat_score,
                    threat_confidence, reasoning, country, city, triggers, review_flag,
                    forecast, historical, sentiment, legal_risk, inclusion_info, profession_info,
                    cyber_ot_risk, environmental_epidemic_risk
                ) = result
                alert_copy = alert.copy()
                alert_copy["gpt_summary"] = summary
                alert_copy["category"] = category
                alert_copy["subcategory"] = subcategory
                alert_copy["category_confidence"] = confidence
                alert_copy["threat_label"] = threat_label if threat_label else "Moderate"
                alert_copy["score"] = threat_score if threat_score is not None else 60
                alert_copy["confidence"] = threat_confidence if threat_confidence is not None else 0.7
                alert_copy["reasoning"] = reasoning
                alert_copy["country"] = country
                alert_copy["city"] = city
                alert_copy["triggers"] = triggers
                alert_copy["review_flag"] = review_flag
                alert_copy["analyst_review"] = alert.get("analyst_review", "")
                alert_copy["hash"] = alert_hash(alert)
                alert_copy["source_name"] = (
                    alert.get("source_name")
                    or alert.get("source")
                    or extract_source_from_url(alert.get("link", ""))
                    or "Unknown"
                )
                alert_copy["version"] = alert.get("version", 1)
                # New prompt enrichments
                alert_copy["forecast"] = forecast
                alert_copy["historical_context"] = historical
                alert_copy["sentiment"] = sentiment
                alert_copy["legal_risk"] = legal_risk
                alert_copy["inclusion_info"] = inclusion_info
                alert_copy["profession_info"] = profession_info
                alert_copy["cyber_ot_risk"] = cyber_ot_risk
                alert_copy["environmental_epidemic_risk"] = environmental_epidemic_risk
                return alert_copy
            else:
                alert_copy = alert.copy()
                alert_copy["gpt_summary"] = "Quota exceeded for this user or session."
                alert_copy["review_flag"] = True
                alert_copy["reasoning"] = "Quota exceeded for user/session."
                alert_copy["analyst_review"] = alert.get("analyst_review", "")
                alert_copy["hash"] = alert_hash(alert)
                alert_copy["source_name"] = (
                    alert.get("source_name")
                    or alert.get("source")
                    or extract_source_from_url(alert.get("link", ""))
                    or "Unknown"
                )
                alert_copy["version"] = alert.get("version", 1)
                logger.info(f"Quota exceeded for {user_email=} or {session_id=}")
                log_threat_engine_usage(
                    email=user_email,
                    plan=plan,
                    action_type="threat_summary",
                    status="quota_exceeded",
                    region=alert.get("country"),
                    summary_text=None
                )
                return alert_copy
        else:
            alert_copy = alert.copy()
            alert_copy["gpt_summary"] = ""
            alert_copy["review_flag"] = False
            alert_copy["analyst_review"] = alert.get("analyst_review", "")
            alert_copy["hash"] = alert_hash(alert)
            alert_copy["source_name"] = (
                alert.get("source_name")
                or alert.get("source")
                or extract_source_from_url(alert.get("link", ""))
                or "Unknown"
            )
            alert_copy["version"] = alert.get("version", 1)
            return alert_copy

    with ThreadPoolExecutor(max_workers=min(5, len(new_alerts))) as executor:
        processed = list(executor.map(process, new_alerts))

    summarized.extend([res for res in processed if res is not None])

    all_alerts = cached_alerts + summarized
    seen = set()
    unique_alerts = []
    for alert in all_alerts:
        h = alert.get("hash", alert_hash(alert))
        if h not in seen:
            unique_alerts.append(alert)
            seen.add(h)

    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(unique_alerts, f, indent=2, ensure_ascii=False)

    if failed_alerts:
        os.makedirs(os.path.dirname(failed_cache_path), exist_ok=True)
        try:
            if os.path.exists(failed_cache_path):
                with open(failed_cache_path, "r", encoding="utf-8") as f:
                    old_failed = json.load(f)
            else:
                old_failed = []
            failed_hashes = {alert_hash(a) for a in old_failed}
            for alert in failed_alerts:
                h = alert_hash(alert)
                if h not in failed_hashes:
                    old_failed.append(alert)
                    failed_hashes.add(h)
            with open(failed_cache_path, "w", encoding="utf-8") as f:
                json.dump(old_failed, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[Failed alert backup error] {e}")

    return unique_alerts