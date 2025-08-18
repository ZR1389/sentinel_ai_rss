# threat_engine.py — Sentinel Threat Engine (Final v2025-08-12) (patched for incident_* safe defaults)
# - Reads raw_alerts -> enriches -> writes alerts (client-facing)
# - Aligns with your alerts schema (domains, baseline metrics, trend, sources, etc.)
# - Defensive defaults + backward compatibility (is_anomaly -> anomaly_flag, series_id/incident_series -> cluster_id)

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
from openai import OpenAI
from prompts import THREAT_SUMMARIZE_SYSTEM_PROMPT
from city_utils import fuzzy_match_city, normalize_city
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
    fetch_past_incidents,
    save_region_trend,
)
from threat_scorer import (
    assess_threat_level,
    compute_trend_direction,
    compute_future_risk_probability,
    compute_now_risk,
    stats_average_score,
    early_warning_indicators,
)

# ---------- Setup ----------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def json_default(obj):
    if isinstance(obj, (datetime,)):
        return obj.isoformat()
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

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
TEMPERATURE = float(os.getenv("THREAT_ENGINE_TEMPERATURE", 0.4))
ENABLE_SEMANTIC_DEDUP = True
SEMANTIC_DEDUP_THRESHOLD = float(os.getenv("SEMANTIC_DEDUP_THRESHOLD", 0.9))

# ---------- Static Data ----------
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

# ---------- Helpers: Embedding/Dedup ----------
def _safe_cosine(a, b):
    a = np.array(a, dtype=float); b = np.array(b, dtype=float)
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) or 1.0
    return float(np.dot(a, b) / denom)

def get_embedding(text, client: OpenAI):
    # Defensive: if embeddings are unavailable, return a simple hashed vector
    try:
        # Replace with your actual embedding model if desired
        # resp = client.embeddings.create(model="text-embedding-3-small", input=text[:8192])
        # return resp.data[0].embedding
        raise RuntimeError("Embeddings disabled by default")
    except Exception:
        # fallback pseudo-embedding
        h = hashlib.sha1(text.encode("utf-8")).hexdigest()
        # map hex -> float vector
        return [int(h[i:i+4], 16) % 997 / 997.0 for i in range(0, 40, 4)]

def alert_hash(alert):
    text = (alert.get("title", "") + "|" + alert.get("summary", "")).strip().lower()
    return hashlib.sha1(text.encode("utf-8")).hexdigest()

def deduplicate_alerts(alerts, existing_alerts, openai_client=None, sim_threshold=SEMANTIC_DEDUP_THRESHOLD, enable_semantic=True):
    known_hashes = {alert_hash(a): a for a in existing_alerts}
    deduped_alerts = []
    known_embeddings = []
    if enable_semantic and openai_client and existing_alerts:
        try:
            known_embeddings = [
                get_embedding(a.get("title", "") + " " + a.get("summary", ""), openai_client)
                for a in existing_alerts
            ]
        except Exception as e:
            logger.warning(f"Semantic dedup init failed, falling back to lexical: {e}")
            enable_semantic = False

    for alert in alerts:
        h = alert_hash(alert)
        if h in known_hashes:
            # Merge small title/summary updates
            existing = known_hashes[h]
            for field in ("title", "summary"):
                if alert.get(field, "") != existing.get(field, ""):
                    existing[field] = alert.get(field, "")
            continue
        if enable_semantic and openai_client and known_embeddings:
            try:
                emb = get_embedding(alert.get("title", "") + " " + alert.get("summary", ""), openai_client)
                if any(_safe_cosine(emb, kemb) > sim_threshold for kemb in known_embeddings):
                    continue
                known_embeddings.append(emb)
            except Exception as e:
                logger.warning(f"Semantic dedup per-item failed, using lexical only: {e}")
        deduped_alerts.append(alert)
        known_hashes[h] = alert
    return deduped_alerts

# ---------- Trend/Baseline Metrics ----------
def _count_incidents(region, category, days: int) -> int:
    incidents = fetch_past_incidents(region=region, category=category, days=days, limit=10000)
    return len(incidents or [])

def _baseline_metrics(alert) -> dict:
    """
    Compute:
      - incident_count_30d
      - recent_count_7d
      - baseline_avg_7d (avg weekly count across past 56 days)
      - baseline_ratio = recent_count_7d / max(1e-6, baseline_avg_7d)
      - trend_direction (via threat_scorer if available; else heuristic)
    """
    region = alert.get("city") or alert.get("region") or alert.get("country")
    category = alert.get("category") or alert.get("threat_label")
    incident_count_30d = _count_incidents(region, category, days=30)
    recent_count_7d = _count_incidents(region, category, days=7)
    # Baseline avg over 8 weeks (56d): incidents/8
    base_56d = _count_incidents(region, category, days=56)
    baseline_avg_7d = float(base_56d) / 8.0 if base_56d else 0.0
    baseline_ratio = (recent_count_7d / baseline_avg_7d) if baseline_avg_7d > 0 else (1.0 if recent_count_7d > 0 else 0.0)

    # Trend direction via scorer if possible
    try:
        incidents = fetch_past_incidents(region=region, category=category, days=90, limit=1000) or []
        trend_direction = compute_trend_direction(incidents) or "stable"
        if trend_direction not in ("increasing", "stable", "decreasing"):
            trend_direction = "stable"
    except Exception:
        # Simple heuristic
        if baseline_ratio > 1.25:
            trend_direction = "increasing"
        elif baseline_ratio < 0.8:
            trend_direction = "decreasing"
        else:
            trend_direction = "stable"

    # PATCH: Provide safe defaults for all fields if missing
    return {
        "incident_count_30d": int(incident_count_30d) if incident_count_30d is not None else 0,
        "recent_count_7d": int(recent_count_7d) if recent_count_7d is not None else 0,
        "baseline_avg_7d": round(float(baseline_avg_7d), 3) if baseline_avg_7d is not None else 0.0,
        "baseline_ratio": round(float(baseline_ratio), 3) if baseline_ratio is not None else 1.0,
        "trend_direction": trend_direction if trend_direction is not None else "stable",
    }

# ---------- Domain Tagging ----------
DOMAIN_KEYWORDS = {
    "travel_mobility": [
        "travel", "route", "road", "highway", "checkpoint", "curfew", "airport", "border", "port", "rail", "metro",
        "detour", "closure", "traffic", "mobility"
    ],
    "cyber_it": [
        "cyber", "hacker", "phishing", "ransomware", "malware", "data breach", "ddos", "credential", "mfa", "passkey",
        "vpn", "exploit", "zero-day", "cve", "edr"
    ],
    "digital_privacy_surveillance": [
        "surveillance", "counter-surveillance", "device check", "phone check", "imsi", "stingray", "tracking",
        "tail", "biometric", "unlock", "spyware", "pegasus", "finfisher", "watchlist"
    ],
    "physical_safety": [
        "kidnap", "abduction", "theft", "assault", "shooting", "stabbing", "robbery", "looting", "murder", "attack"
    ],
    "civil_unrest": [
        "protest", "riot", "demonstration", "clash", "unrest", "strike", "roadblock", "sit-in"
    ],
    "kfr_extortion": [
        "kidnapping", "kidnap-for-ransom", "kfr", "ransom", "extortion"
    ],
    "infrastructure_utilities": [
        "infrastructure", "power", "grid", "substation", "pipeline", "telecom", "fiber", "facility", "sabotage", "water"
    ],
    "environmental_hazards": [
        "earthquake", "flood", "hurricane", "storm", "wildfire", "heatwave", "landslide", "mudslide"
    ],
    "public_health_epidemic": [
        "epidemic", "pandemic", "outbreak", "cholera", "dengue", "covid", "ebola", "avian flu"
    ],
    "ot_ics": [
        "scada", "ics", "plc", "ot", "industrial control", "hmi"
    ],
    "info_ops_disinfo": [
        "misinformation", "disinformation", "propaganda", "info ops", "psyop"
    ],
    "legal_regulatory": [
        "visa", "immigration", "border control", "curfew", "checkpoint order", "permit", "license", "ban", "restriction"
    ],
    "business_continuity_supply": [
        "supply chain", "logistics", "port congestion", "warehouse", "strike", "shortage", "inventory"
    ],
    "insider_threat": [
        "insider", "employee", "privileged access", "badge", "tailgating"
    ],
    "residential_premises": [
        "residential", "home invasion", "burglary", "apartment", "compound"
    ],
    "emergency_medical": [
        "casualty", "injured", "fatalities", "triage", "medical", "ambulance"
    ],
    "counter_surveillance": [
        "surveillance", "tail", "followed", "sd r", "surveillance detection"
    ],
    "terrorism": [
        "ied", "vbied", "suicide bomber", "terrorist", "bomb"
    ],
}

def classify_domains(alert):
    """
    Tag alert with relevant domains from Sentinel taxonomy.
    """
    text = (alert.get("title", "") + " " + alert.get("summary", "")).lower()
    domains = set()
    for dom, kws in DOMAIN_KEYWORDS.items():
        if any(k in text for k in kws):
            domains.add(dom)

    # Category-driven boosting
    category = (alert.get("category") or alert.get("threat_label") or "").lower()
    if "cyber" in category:
        domains.add("cyber_it")
    if "unrest" in category:
        domains.add("civil_unrest"); domains.add("physical_safety"); domains.add("travel_mobility")
    if "terror" in category:
        domains.add("terrorism"); domains.add("physical_safety")
    if "infrastructure" in category:
        domains.add("infrastructure_utilities")
    if "environmental" in category:
        domains.add("environmental_hazards"); domains.add("emergency_medical")
    if "epidemic" in category:
        domains.add("public_health_epidemic"); domains.add("emergency_medical")
    if "crime" in category:
        domains.add("physical_safety")

    # Travel presence heuristic
    if any(k in text for k in ["airport", "flight", "train", "bus", "border", "checkpoint", "curfew", "road", "closure"]):
        domains.add("travel_mobility")

    return sorted(domains)

# ---------- Enrichment Pipeline ----------
def _structured_sources(alert) -> list:
    src = alert.get("source") or alert.get("source_name")
    link = alert.get("link") or alert.get("source_url")
    if src or link:
        return [{"name": src, "link": link}]
    return []

def _compute_future_risk_prob(historical_incidents) -> float:
    try:
        return float(compute_future_risk_probability(historical_incidents) or 0.0)
    except Exception:
        return 0.0

def summarize_single_alert(alert):
    # Collect base text
    title = alert.get("title", "") or ""
    summary = alert.get("summary", "") or ""
    full_text = f"{title}\n{summary}".strip()
    location = alert.get("city") or alert.get("region") or alert.get("country")
    triggers = alert.get("tags", [])

    # Threat scoring (label/score/confidence/reasoning)
    threat_score_data = assess_threat_level(
        alert_text=full_text,
        triggers=triggers,
        location=location,
        alert_uuid=alert.get("uuid"),
        plan="FREE",
        enrich=True,
        user_email=None,
        source_alert=alert
    ) or {}

    for k, v in threat_score_data.items():
        alert[k] = v

    # Quick LLM summary (optional)
    g_summary = None
    try:
        from xai_client import grok_chat
        messages = [
            {"role": "system", "content": THREAT_SUMMARIZE_SYSTEM_PROMPT},
            {"role": "user", "content": full_text}
        ]
        g_summary = grok_chat(messages, temperature=TEMPERATURE)
    except Exception as e:
        logger.error(f"[Grok summary error] {e}")

    alert["gpt_summary"] = g_summary or alert.get("gpt_summary") or ""

    # Category/subcategory
    if not alert.get("category") or not alert.get("category_confidence"):
        try:
            cat, cat_conf = extract_threat_category(full_text)
            alert["category"] = cat
            alert["category_confidence"] = cat_conf
        except Exception as e:
            logger.error(f"[ThreatEngine][CategoryFallbackError] {e}")
            alert["category"] = alert.get("category", "Other")
            alert["category_confidence"] = alert.get("category_confidence", 0.5)

    if not alert.get("subcategory"):
        try:
            alert["subcategory"] = extract_threat_subcategory(full_text, alert["category"])
        except Exception as e:
            logger.error(f"[ThreatEngine][SubcategoryFallbackError] {e}")
            alert["subcategory"] = "Unspecified"

    # Domains
    alert["domains"] = classify_domains(alert)

    # Historical & trend metrics
    # 7d historical for EWI and severity avg
    historical_incidents = fetch_past_incidents(
        region=location, category=alert.get("category") or alert.get("threat_label"), days=7, limit=100
    ) or []
    alert["historical_incidents_count"] = len(historical_incidents)
    alert["avg_severity_past_week"] = stats_average_score(historical_incidents)

    # Baseline metrics
    base = _baseline_metrics(alert)
    alert.update(base)

    # PATCH: Defensive defaults for incident/trend fields
    if alert.get("incident_count_30d") is None:
        alert["incident_count_30d"] = 0
    if alert.get("recent_count_7d") is None:
        alert["recent_count_7d"] = 0
    if alert.get("baseline_avg_7d") is None:
        alert["baseline_avg_7d"] = 0.0
    if alert.get("baseline_ratio") is None:
        alert["baseline_ratio"] = 1.0
    if alert.get("trend_direction") is None:
        alert["trend_direction"] = "stable"

    # Early warnings
    ewi = early_warning_indicators(historical_incidents) or []
    alert["early_warning_indicators"] = ewi
    if ewi:
        alert["early_warning_signal"] = f"⚠️ Early warning: {', '.join(ewi)} detected in recent incidents."

    # Future risk probability (if your scorer provides it)
    alert["future_risk_probability"] = _compute_future_risk_prob(historical_incidents)

    # Structured sources + reports analyzed
    alert["sources"] = alert.get("sources") or _structured_sources(alert)
    alert["reports_analyzed"] = alert.get("reports_analyzed") or alert.get("num_reports") or 1

    # Cluster / anomaly flags
    alert["cluster_id"] = alert.get("cluster_id") or alert.get("series_id") or alert.get("incident_series")
    alert["anomaly_flag"] = alert.get("anomaly_flag", alert.get("is_anomaly", False))

    # Legacy trend score (optional persist)
    city = alert.get("city") or alert.get("region") or alert.get("country")
    threat_type = alert.get("category") or alert.get("threat_label")
    try:
        incidents_365 = fetch_past_incidents(region=city, category=threat_type, days=365, limit=1000) or []
        # Save region trend (non-critical)
        save_region_trend(
            region=None,
            city=city,
            trend_window_start=datetime.utcnow() - timedelta(days=365),
            trend_window_end=datetime.utcnow(),
            incident_count=len(incidents_365),
            categories=[threat_type] if threat_type else None
        )
    except Exception as e:
        logger.error(f"Failed to save region trend: {e}")

    return alert

def summarize_alerts(alerts):
    os.makedirs("cache", exist_ok=True)
    cache_path = "cache/enriched_alerts.json"
    failed_cache_path = "cache/alerts_failed.json"

    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            cached_alerts = json.load(f)
    else:
        cached_alerts = []

    new_alerts = deduplicate_alerts(
        alerts,
        existing_alerts=cached_alerts,
        openai_client=openai_client if ENABLE_SEMANTIC_DEDUP else None,
        sim_threshold=SEMANTIC_DEDUP_THRESHOLD,
        enable_semantic=ENABLE_SEMANTIC_DEDUP,
    )

    if not new_alerts:
        return cached_alerts

    summarized = []
    failed_alerts = []
    failed_alerts_lock = threading.Lock()

    def process(alert):
        try:
            enriched = summarize_single_alert(alert)
            return enriched
        except Exception as e:
            logger.error(f"[ThreatEngine] Failed to enrich alert: {e}")
            with failed_alerts_lock:
                failed_alerts.append(alert)
            return None

    with ThreadPoolExecutor(max_workers=min(5, len(new_alerts))) as executor:
        processed = list(executor.map(process, new_alerts))

    summarized.extend([res for res in processed if res is not None])

    # Merge with cache (de-dup by content hash)
    all_alerts = cached_alerts + summarized
    seen = set()
    unique_alerts = []
    for alert in all_alerts:
        h = alert_hash(alert)
        if h not in seen:
            alert["label"] = alert.get("label", alert.get("threat_label", "Unknown"))
            # Defensive patch: incident/trend defaults
            if alert.get("incident_count_30d") is None:
                alert["incident_count_30d"] = 0
            if alert.get("recent_count_7d") is None:
                alert["recent_count_7d"] = 0
            if alert.get("baseline_avg_7d") is None:
                alert["baseline_avg_7d"] = 0.0
            if alert.get("baseline_ratio") is None:
                alert["baseline_ratio"] = 1.0
            if alert.get("trend_direction") is None:
                alert["trend_direction"] = "stable"
            unique_alerts.append(alert)
            seen.add(h)

    # Persist cache
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(unique_alerts, f, indent=2, ensure_ascii=False, default=json_default)

    # Persist failures (backup)
    if failed_alerts:
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
                    # Defensive patch: incident/trend defaults
                    if alert.get("incident_count_30d") is None:
                        alert["incident_count_30d"] = 0
                    if alert.get("recent_count_7d") is None:
                        alert["recent_count_7d"] = 0
                    if alert.get("baseline_avg_7d") is None:
                        alert["baseline_avg_7d"] = 0.0
                    if alert.get("baseline_ratio") is None:
                        alert["baseline_ratio"] = 1.0
                    if alert.get("trend_direction") is None:
                        alert["trend_direction"] = "stable"
                    old_failed.append(alert)
                    failed_hashes.add(h)
            with open(failed_cache_path, "w", encoding="utf-8") as f:
                json.dump(old_failed, f, indent=2, ensure_ascii=False, default=json_default)
        except Exception as e:
            logger.error(f"[Failed alert backup error] {e}")

    return unique_alerts

def get_raw_alerts(region=None, country=None, city=None, limit=1000):
    return fetch_raw_alerts_from_db(
        region=region,
        country=country,
        city=city,
        limit=limit
    )

# ---------- Normalize for DB (guarantees Advisor contract) ----------
def _normalize_for_db(a: dict) -> dict:
    a["anomaly_flag"] = a.get("anomaly_flag", a.get("is_anomaly", False))
    a["cluster_id"] = a.get("cluster_id") or a.get("series_id") or a.get("incident_series")
    if not a.get("sources"):
        src = a.get("source"); lnk = a.get("link")
        a["sources"] = [{"name": src, "link": lnk}] if (src or lnk) else []
    a["reports_analyzed"] = a.get("reports_analyzed") or a.get("num_reports") or 1
    a["domains"] = a.get("domains") or []
    a["trend_direction"] = a.get("trend_direction") or "stable"
    a["baseline_ratio"] = a.get("baseline_ratio", 1.0)
    a["baseline_avg_7d"] = a.get("baseline_avg_7d", 0.0)
    # PATCH: Defensive defaults for incident/trend fields
    if a.get("incident_count_30d") is None:
        a["incident_count_30d"] = 0
    if a.get("recent_count_7d") is None:
        a["recent_count_7d"] = 0
    return a

def enrich_and_store_alerts(region=None, country=None, city=None, limit=1000):
    raw_alerts = get_raw_alerts(region=region, country=country, city=city, limit=limit)
    if not raw_alerts:
        logger.info("No raw alerts to process.")
        return []

    logger.info(f"Fetched {len(raw_alerts)} raw alerts. Starting enrichment and filtering...")
    enriched_alerts = summarize_alerts(raw_alerts)

    if enriched_alerts:
        # Normalize before DB write
        normalized = [_normalize_for_db(x) for x in enriched_alerts]
        logger.info(f"Storing {len(normalized)} enriched alerts to alerts table...")
        save_alerts_to_db(normalized)
        logger.info("Enriched alerts saved to DB successfully.")
    else:
        logger.info("No enriched alerts to store.")

    return enriched_alerts

if __name__ == "__main__":
    logger.info("Running threat engine enrichment pipeline...")
    enrich_and_store_alerts(limit=1000)
    logger.info("Threat engine enrichment done.")