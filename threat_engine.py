import os
import time
import json
import re
import hashlib
import threading
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

import pycountry
from dotenv import load_dotenv
import numpy as np
from xai_client import grok_chat
from openai import OpenAI
from prompts import (
    THREAT_SUMMARIZE_SYSTEM_PROMPT,
)
from city_utils import fuzzy_match_city, normalize_city
from plan_utils import (
    get_plan_limits,
    require_plan_feature,
    check_user_summary_quota,
    increment_user_summary_usage
)
import logging

from risk_shared import (
    compute_keyword_weight,
    enrich_log,
    run_sentiment_analysis,
    run_forecast,
    run_legal_risk,
    run_cyber_ot_risk,
    run_environmental_epidemic_risk,
    extract_threat_category,
    extract_threat_subcategory,
)
from db_utils import (
    fetch_raw_alerts_from_db,
    save_alerts_to_db,
    fetch_alerts_from_db,
    fetch_past_incidents,
    save_region_trend,  # <-- ADDED: for trend enrichment
)
from threat_scorer import (
    assess_threat_level,
    compute_trend_direction,
    compute_future_risk_probability,
    compute_now_risk,
    stats_average_score,
    early_warning_indicators,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def json_default(obj):
    if isinstance(obj, (datetime,)):
        return obj.isoformat()
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

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

# --- USAGE LOGGING (plan/quota is enforced here, not at ingestion) ---
def log_threat_engine_usage(email, plan, action_type, status, region=None, summary_text=None):
    try:
        import psycopg2
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

def can_user_summarize(user_email, plan_limits, feature="custom_pdf_briefings_frequency"):
    if not check_user_summary_quota(user_email, plan_limits, feature):
        logger.info(f"[Quota] User {user_email} exceeded monthly summary quota")
        return False
    increment_user_summary_usage(user_email)
    return True

def should_summarize_alert(alert, plan_limits):
    return True

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
        f.write(json.dumps(log_entry, ensure_ascii=False, default=json_default) + "\n")

def alert_hash(alert):
    text = (alert.get("title", "") + "|" + alert.get("summary", "")).strip().lower()
    return hashlib.sha1(text.encode("utf-8")).hexdigest()

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

def fetch_historical_incidents(alert, days=7):
    region = alert.get("region") or alert.get("city") or alert.get("country")
    category = alert.get("category") or alert.get("threat_label") or None
    series_id = alert.get("series_id") or alert.get("incident_series") or None
    return fetch_past_incidents(region=region, category=category, days=days, limit=100)

def compute_developing_situations(alerts, window_hours=72):
    clusters = {}
    for alert in alerts:
        series_id = alert.get("series_id") or alert.get("incident_series")
        if not series_id:
            continue
        if series_id not in clusters:
            clusters[series_id] = []
        clusters[series_id].append(alert)
    cutoff = datetime.utcnow() - timedelta(hours=window_hours)
    filtered_clusters = {}
    for sid, cluster in clusters.items():
        filtered = [
            a for a in cluster
            if (a.get("published") and
                isinstance(a.get("published"), str) and
                datetime.fromisoformat(a["published"].replace("Z", "+00:00")) >= cutoff)
        ]
        if filtered:
            filtered_clusters[sid] = filtered
    return filtered_clusters

def calculate_trend(city, threat_type, days=365):
    incidents = fetch_past_incidents(region=city, category=threat_type, days=days, limit=1000)
    if not incidents or len(incidents) < 8:
        try:
            save_region_trend(
                region=None,
                city=city,
                trend_window_start=datetime.utcnow() - timedelta(days=days),
                trend_window_end=datetime.utcnow(),
                incident_count=0,
                categories=[threat_type] if threat_type else None
            )
        except Exception as e:
            logger.error(f"Failed to save region trend (insufficient data): {e}")
        return 0.5, "Insufficient historical data for escalation probability."
    escalation = [i for i in incidents if i.get("score", 0) > 75]
    ratio = len(escalation) / len(incidents)
    percent = int(ratio * 100)
    msg = (
        f"Based on {len(incidents)} similar events in the past 12 months in {city}, "
        f"escalation was observed in {percent}% of cases."
    )
    try:
        save_region_trend(
            region=None,
            city=city,
            trend_window_start=datetime.utcnow() - timedelta(days=days),
            trend_window_end=datetime.utcnow(),
            incident_count=len(incidents),
            categories=[threat_type] if threat_type else None
        )
    except Exception as e:
        logger.error(f"Failed to save region trend: {e}")
    return ratio, msg

def summarize_single_alert(alert, user_email=None, plan=None, region=None, user_message=None, profession=None, batch_context=None, trend_metrics=None):
    plan_limits = get_plan_limits(user_email)
    advanced_enrich_allowed = require_plan_feature(user_email, "insights")
    title = alert.get("title", "")
    summary = alert.get("summary", "")
    full_text = f"{title}\n{summary}".strip()
    location = alert.get("city") or alert.get("region") or alert.get("country")
    triggers = alert.get("tags", [])
    threat_score_data = assess_threat_level(
        alert_text=full_text,
        triggers=triggers,
        location=location,
        alert_uuid=alert.get("uuid"),
        plan=plan or "FREE",
        enrich=True,
        user_email=user_email,
        source_alert=alert
    )
    for k, v in (threat_score_data or {}).items():
        alert[k] = v

    messages = [
        {"role": "system", "content": THREAT_SUMMARIZE_SYSTEM_PROMPT},
        {"role": "user", "content": full_text}
    ]
    g_summary = None
    try:
        if advanced_enrich_allowed:
            g_summary = grok_chat(messages, temperature=TEMPERATURE)
        else:
            g_summary = ""
    except Exception as e:
        logger.error(f"[Grok summary error] {e}")

    alert["gpt_summary"] = g_summary or ""

    if "label" not in alert:
        alert["label"] = alert.get("threat_label", "Unknown")
    if "score" not in alert:
        alert["score"] = 60
    if "confidence" not in alert:
        alert["confidence"] = 0.7

    if "category" not in alert or "category_confidence" not in alert:
        try:
            cat, cat_conf = extract_threat_category(full_text)
            alert["category"] = cat
            alert["category_confidence"] = cat_conf
        except Exception as e:
            logger.error(f"[ThreatEngine][CategoryFallbackError] {e}")
            alert["category"] = "Other"
            alert["category_confidence"] = 0.5
    if "subcategory" not in alert:
        try:
            alert["subcategory"] = extract_threat_subcategory(full_text, alert["category"])
        except Exception as e:
            logger.error(f"[ThreatEngine][SubcategoryFallbackError] {e}")
            alert["subcategory"] = "Unspecified"

    historical_incidents = fetch_historical_incidents(alert, days=7)
    alert["historical_incidents_count"] = len(historical_incidents)
    alert["avg_severity_past_week"] = stats_average_score(historical_incidents)

    city = alert.get("city")
    threat_type = alert.get("category") or alert.get("threat_label")
    trend_score, trend_score_msg = calculate_trend(city, threat_type)
    alert["trend_score"] = trend_score
    alert["trend_score_msg"] = trend_score_msg

    ewi = early_warning_indicators(historical_incidents)
    alert["early_warning_indicators"] = ewi
    if ewi:
        alert["early_warning_signal"] = (
            f"⚠️ Early warning: {', '.join(ewi)} detected in recent incidents. Escalation possible."
        )

    if batch_context:
        alert["batch_trend_direction"] = batch_context.get("trend_direction")
        alert["batch_future_risk_probability"] = batch_context.get("future_risk_probability")
        alert["batch_now_score"] = batch_context.get("now_score")
        alert["batch_now_label"] = batch_context.get("now_label")
        if alert.get("score") and batch_context.get("now_score") is not None:
            if abs(alert["score"] - batch_context["now_score"]) > 25:
                alert["is_anomaly"] = True
            else:
                alert["is_anomaly"] = False
    if trend_metrics:
        alert.update(trend_metrics)

    return alert

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

    batch_context = {}
    if new_alerts:
        try:
            sorted_alerts = sorted(
                new_alerts,
                key=lambda a: a.get("published") or a.get("timestamp") or "",
                reverse=True
            )
        except Exception:
            sorted_alerts = new_alerts

        batch_context["trend_direction"] = compute_trend_direction(sorted_alerts)
        batch_context["future_risk_probability"] = compute_future_risk_probability(sorted_alerts)
        now_stats = compute_now_risk(sorted_alerts)
        batch_context["now_score"] = now_stats.get("now_score")
        batch_context["now_label"] = now_stats.get("now_label")

        clusters = compute_developing_situations(sorted_alerts, window_hours=72)
        batch_context["developing_situations"] = clusters

        batch_context["avg_severity_past_week"] = stats_average_score(sorted_alerts)
        batch_context["past_week_count"] = len([
            a for a in sorted_alerts
            if a.get("published") and
            isinstance(a.get("published"), str) and
            (datetime.utcnow() - datetime.fromisoformat(a["published"].replace("Z", "+00:00"))).days < 7
        ])

    summarized = []
    failed_alerts = []
    failed_alerts_lock = threading.Lock()

    def process(alert):
        try:
            trend_metrics = {
                "past_week_count": batch_context.get("past_week_count"),
                "avg_severity_past_week": batch_context.get("avg_severity_past_week"),
                "developing_situations": batch_context.get("developing_situations"),
            }
            enriched = summarize_single_alert(
                alert,
                user_email=user_email,
                plan=plan,
                batch_context=batch_context,
                trend_metrics=trend_metrics
            )
            return enriched
        except Exception as e:
            logger.error(f"[ThreatEngine] Failed to enrich alert: {e}")
            with failed_alerts_lock:
                failed_alerts.append(alert)
            return None

    with ThreadPoolExecutor(max_workers=min(5, len(new_alerts))) as executor:
        processed = list(executor.map(process, new_alerts))

    summarized.extend([res for res in processed if res is not None])

    all_alerts = cached_alerts + summarized
    seen = set()
    unique_alerts = []
    for alert in all_alerts:
        h = alert_hash(alert)
        if h not in seen:
            alert["label"] = alert.get("label", alert.get("threat_label", "Unknown"))
            unique_alerts.append(alert)
            seen.add(h)

    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(unique_alerts, f, indent=2, ensure_ascii=False, default=json_default)

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
                    alert["label"] = alert.get("label", alert.get("threat_label", "Unknown"))
                    old_failed.append(alert)
                    failed_hashes.add(h)
            with open(failed_cache_path, "w", encoding="utf-8") as f:
                json.dump(old_failed, f, indent=2, ensure_ascii=False, default=json_default)
        except Exception as e:
            logger.error(f"[Failed alert backup error] {e}")

    return unique_alerts

def get_raw_alerts(
    region=None,
    country=None,
    city=None,
    limit=1000,
):
    return fetch_raw_alerts_from_db(
        region=region,
        country=country,
        city=city,
        limit=limit
    )

def enrich_and_store_alerts(
    region=None,
    country=None,
    city=None,
    limit=1000,
    user_email=None,
    session_id=None,
    user_message=None,
    profession=None,
):
    raw_alerts = get_raw_alerts(region=region, country=country, city=city, limit=limit)
    if not raw_alerts:
        logger.info("No raw alerts to process.")
        return []

    logger.info(f"Fetched {len(raw_alerts)} raw alerts. Starting enrichment and filtering...")
    enriched_alerts = summarize_alerts(
        raw_alerts,
        user_email=user_email,
        session_id=session_id,
        user_message=user_message,
        profession=profession
    )

    if enriched_alerts:
        logger.info(f"Storing {len(enriched_alerts)} enriched alerts to alerts table...")
        save_alerts_to_db(enriched_alerts)
        logger.info("Enriched alerts saved to DB successfully.")
    else:
        logger.info("No enriched alerts to store.")

    return enriched_alerts

def get_clean_alerts(
    region=None,
    country=None,
    city=None,
    threat_level=None,
    threat_label=None,
    limit=10,
    user_email=None,
    session_id=None,
    **kwargs
):
    alerts = fetch_alerts_from_db(
        region=region,
        country=country,
        city=city,
        threat_level=threat_level,
        threat_label=threat_label,
        limit=limit
    )

    clean_alerts = []
    for alert in alerts:
        if not alert.get("summary"):
            continue
        alert["label"] = alert.get("label", alert.get("threat_label", "Unknown"))
        clean_alerts.append(alert)

    return clean_alerts

# --- New: Trend Tracking API helper ---
def get_trend_tracker(region=None, city=None, time_unit="week", days=30):
    """
    Fetches and groups trend data from region_trends table for API or dashboard use.
    Returns: {city: {week: count}} or {region: {week: count}}
    """
    import psycopg2
    trend_data = {}
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        where_clause = []
        params = []
        if region:
            where_clause.append("region = %s")
            params.append(region)
        if city:
            where_clause.append("city = %s")
            params.append(city)
        # Always filter by recent N days
        where_sql = ("WHERE " + " AND ".join(where_clause)) if where_clause else "WHERE 1=1"
        cur.execute(f"""
            SELECT city, region, trend_window_start, incident_count
            FROM region_trends
            {where_sql}
            AND trend_window_start >= %s
        """, params + [(datetime.utcnow() - timedelta(days=days)).isoformat()])
        for city_val, region_val, week, count in cur.fetchall():
            key_city = city_val or "unknown"
            key_week = week[:10] if week else "other"
            trend_data.setdefault(key_city, {})
            trend_data[key_city][key_week] = count
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"[Trend tracker DB error] {e}")
    return trend_data

if __name__ == "__main__":
    logger.info("Running threat engine enrichment pipeline...")
    enrich_and_store_alerts(limit=1000)
    logger.info("Threat engine enrichment done.")