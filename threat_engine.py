# threat_engine.py — Sentinel Threat Engine (Final v2025-08-22 + Relevance Gate v2025-08-25)
# - Reads raw_alerts -> enriches -> writes alerts (client-facing)
# - Aligns with your alerts schema (domains, baseline metrics, trend, sources, etc.)
# - Defensive defaults + backward compatibility (is_anomaly -> anomaly_flag, series_id/incident_series -> cluster_id)

from __future__ import annotations

import os
import json
import re
import hashlib
import threading
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

import logging
import numpy as np
import pycountry
from dotenv import load_dotenv

# -------- Optional LLM clients / prompts (do not fail engine if absent) --------
try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # type: ignore

try:
    from prompts import THREAT_SUMMARIZE_SYSTEM_PROMPT
except Exception:
    THREAT_SUMMARIZE_SYSTEM_PROMPT = (
        "You are a concise threat analyst. Summarize salient facts, location, "
        "impact to people/operations/mobility, and immediate guidance in 3–5 bullets."
    )

# -------- Project imports --------
from risk_shared import (
    compute_keyword_weight,
    enrich_log,  # kept for compatibility even if unused
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
    compute_now_risk,  # imported for compatibility / potential use
    stats_average_score,
    early_warning_indicators,
)

# ---------- Setup ----------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("threat_engine")

def json_default(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")
RAILWAY_ENV = os.getenv("RAILWAY_ENVIRONMENT")

# Engine controls (explicit + safe defaults)
ENGINE_WRITE_TO_DB = str(os.getenv("ENGINE_WRITE_TO_DB", "true")).lower() in ("1","true","yes","y")
ENGINE_FAIL_CLOSED = str(os.getenv("ENGINE_FAIL_CLOSED", "true")).lower() in ("1","true","yes","y")
ENGINE_CACHE_DIR   = os.getenv("ENGINE_CACHE_DIR", "cache")
ENGINE_MAX_WORKERS = int(os.getenv("ENGINE_MAX_WORKERS", "5"))
ENABLE_SEMANTIC_DEDUP = str(os.getenv("ENGINE_SEMANTIC_DEDUP", "true")).lower() in ("1","true","yes","y")
SEMANTIC_DEDUP_THRESHOLD = float(os.getenv("SEMANTIC_DEDUP_THRESHOLD", "0.9"))
TEMPERATURE = float(os.getenv("THREAT_ENGINE_TEMPERATURE", "0.4"))
GROK_MODEL = os.getenv("GROK_MODEL", "grok-3-mini")  # hint for your xai client; not enforced here

if RAILWAY_ENV:
    logger.info(f"Running in Railway environment: {RAILWAY_ENV}")
else:
    logger.info("Running outside Railway or RAILWAY_ENVIRONMENT not set.")

if not DATABASE_URL:
    msg = "DATABASE_URL not set!"
    if ENGINE_FAIL_CLOSED:
        raise SystemExit(f"{msg} Refusing to run (ENGINE_FAIL_CLOSED=true).")
    logger.warning(f"{msg} Database operations may fail.")

if not ENGINE_WRITE_TO_DB:
    msg = "ENGINE_WRITE_TO_DB is FALSE — alerts will NOT be written."
    if ENGINE_FAIL_CLOSED:
        raise SystemExit(f"{msg} Refusing to run (ENGINE_FAIL_CLOSED=true).")
    logger.warning(f"{msg} Set ENGINE_WRITE_TO_DB=true to enable inserts into alerts.")

# OpenAI client is optional (semantic dedup can still use hashed fallback)
openai_client = OpenAI(api_key=OPENAI_API_KEY) if (OPENAI_API_KEY and OpenAI) else None
if not OPENAI_API_KEY:
    logger.info("OPENAI_API_KEY not set — LLM features will be limited.")
if openai_client is None and ENABLE_SEMANTIC_DEDUP:
    logger.info("OpenAI client unavailable — semantic dedup will use fallback hashing only.")

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

def get_embedding(text: str, client: OpenAI | None):
    """
    Defensive embedding:
    - If real embeddings available, you can enable here.
    - Default: stable hashed pseudo-embedding (no external calls).
    """
    try:
        # Example (disabled by default):
        # resp = client.embeddings.create(model="text-embedding-3-small", input=text[:8192])
        # return resp.data[0].embedding
        raise RuntimeError("Embeddings disabled by default")
    except Exception:
        h = hashlib.sha1(text.encode("utf-8")).hexdigest()
        return [int(h[i:i+4], 16) % 997 / 997.0 for i in range(0, 40, 4)]

def alert_hash(alert: dict) -> str:
    """
    Stable content hash for deduping enriched alerts.
    Include link to avoid duplicate rows when title/summary repeat.
    """
    text = (
        (alert.get("title", "") or "").strip().lower()
        + "|" + (alert.get("summary", "") or "").strip().lower()
        + "|" + (alert.get("link", "") or "").strip().lower()
    )
    return hashlib.sha1(text.encode("utf-8")).hexdigest()

def deduplicate_alerts(
    alerts: list[dict],
    existing_alerts: list[dict],
    openai_client: OpenAI | None = None,
    sim_threshold: float = SEMANTIC_DEDUP_THRESHOLD,
    enable_semantic: bool = ENABLE_SEMANTIC_DEDUP,
):
    known_hashes = {alert_hash(a): a for a in (existing_alerts or [])}
    deduped_alerts = []
    known_embeddings = []

    if enable_semantic and openai_client and existing_alerts:
        try:
            known_embeddings = [
                get_embedding((a.get("title","")+" "+a.get("summary",""))[:4096], openai_client)
                for a in existing_alerts
            ]
        except Exception as e:
            logger.warning(f"Semantic dedup init failed, falling back to lexical only: {e}")
            enable_semantic = False

    for alert in alerts or []:
        h = alert_hash(alert)
        if h in known_hashes:
            # Merge small title/summary updates in-place
            existing = known_hashes[h]
            for field in ("title", "summary"):
                if alert.get(field, "") and alert.get(field) != existing.get(field, ""):
                    existing[field] = alert.get(field, "")
            continue

        if enable_semantic and openai_client and known_embeddings:
            try:
                emb = get_embedding((alert.get("title","")+" "+alert.get("summary",""))[:4096], openai_client)
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
    base_56d = _count_incidents(region, category, days=56)
    baseline_avg_7d = float(base_56d) / 8.0 if base_56d else 0.0
    baseline_ratio = (recent_count_7d / baseline_avg_7d) if baseline_avg_7d > 0 else (1.0 if recent_count_7d > 0 else 0.0)

    try:
        incidents = fetch_past_incidents(region=region, category=category, days=90, limit=1000) or []
        trend_direction = compute_trend_direction(incidents) or "stable"
        if trend_direction not in ("increasing", "stable", "decreasing"):
            trend_direction = "stable"
    except Exception:
        trend_direction = "increasing" if baseline_ratio > 1.25 else "decreasing" if baseline_ratio < 0.8 else "stable"

    return {
        "incident_count_30d": int(incident_count_30d or 0),
        "recent_count_7d": int(recent_count_7d or 0),
        "baseline_avg_7d": round(float(baseline_avg_7d or 0.0), 3),
        "baseline_ratio": round(float(baseline_ratio if baseline_ratio is not None else 1.0), 3),
        "trend_direction": trend_direction or "stable",
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

def classify_domains(alert: dict) -> list[str]:
    text = (alert.get("title", "") + " " + alert.get("summary", "")).lower()
    domains = set()
    for dom, kws in DOMAIN_KEYWORDS.items():
        if any(k in text for k in kws):
            domains.add(dom)

    category = (alert.get("category") or alert.get("threat_label") or "").lower()
    if "cyber" in category:
        domains.add("cyber_it")
    if "unrest" in category:
        domains.update({"civil_unrest", "physical_safety", "travel_mobility"})
    if "terror" in category:
        domains.update({"terrorism", "physical_safety"})
    if "infrastructure" in category:
        domains.add("infrastructure_utilities")
    if "environmental" in category:
        domains.update({"environmental_hazards", "emergency_medical"})
    if "epidemic" in category:
        domains.update({"public_health_epidemic", "emergency_medical"})
    if "crime" in category:
        domains.add("physical_safety")

    if any(k in text for k in ["airport", "flight", "train", "bus", "border", "checkpoint", "curfew", "road", "closure"]):
        domains.add("travel_mobility")

    return sorted(domains)

# ---------- Relevance Filtering ----------
def is_relevant(alert: dict) -> bool:
    """
    Lightweight relevance gate to exclude non-security junk while keeping recall.
    """
    text = (alert.get("title","") + " " + alert.get("summary","")).lower()

    # Sports / entertainment obvious noise
    if any(bad in text for bad in [
        "football","basketball","soccer","tennis","nba","nfl","fifa","cricket","olympics",
        "concert","music festival","award show","box office","celebrity"
    ]):
        return False

    # Business/finance-only chatter
    if any(bad in text for bad in ["stock market","ipo","earnings call","celebrity investor"]):
        return False

    # Non-security "defense" (require security context)
    if "defense" in text and not any(sec in text for sec in [
        "military","army","navy","air force","missile","air defense","cyber","national security","homeland security"
    ]):
        return False

    # Require minimum classification confidence
    if alert.get("category_confidence", 0) < 0.35:
        return False

    # Require at least one domain mapping (post-enrichment)
    if not alert.get("domains"):
        return False

    return True

# ---------- Enrichment Pipeline ----------
def _structured_sources(alert: dict) -> list[dict]:
    src = alert.get("source") or alert.get("source_name")
    link = alert.get("link") or alert.get("source_url")
    if src or link:
        return [{"name": src, "link": link}]
    return []

def _compute_future_risk_prob(historical_incidents: list[dict]) -> float:
    try:
        return float(compute_future_risk_probability(historical_incidents) or 0.0)
    except Exception:
        return 0.0

def summarize_single_alert(alert: dict) -> dict:
    title = alert.get("title", "") or ""
    summary = alert.get("summary", "") or ""
    full_text = f"{title}\n{summary}".strip()
    location = alert.get("city") or alert.get("region") or alert.get("country")
    triggers = alert.get("tags", [])

    # Threat scoring
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

    # risk_shared analytics (best-effort)
    try: alert["sentiment"] = run_sentiment_analysis(full_text)
    except Exception: pass
    try: alert["forecast"] = run_forecast(full_text, location=location)
    except Exception: pass
    try: alert["legal_risk"] = run_legal_risk(full_text)
    except Exception: pass
    try: alert["cyber_ot_risk"] = run_cyber_ot_risk(full_text)
    except Exception: pass
    try: alert["environmental_epidemic_risk"] = run_environmental_epidemic_risk(full_text)
    except Exception: pass
    try: alert["keyword_weight"] = compute_keyword_weight(full_text)
    except Exception: pass

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
    historical_incidents = fetch_past_incidents(
        region=location, category=alert.get("category") or alert.get("threat_label"), days=7, limit=100
    ) or []
    alert["historical_incidents_count"] = len(historical_incidents)
    alert["avg_severity_past_week"] = stats_average_score(historical_incidents)

    # Baseline metrics
    alert.update(_baseline_metrics(alert))

    # Early warnings
    ewi = early_warning_indicators(historical_incidents) or []
    alert["early_warning_indicators"] = ewi
    if ewi:
        alert["early_warning_signal"] = f"⚠️ Early warning: {', '.join(ewi)} detected in recent incidents."

    # Future risk probability
    alert["future_risk_probability"] = _compute_future_risk_prob(historical_incidents)

    # Structured sources + reports analyzed
    alert["sources"] = alert.get("sources") or _structured_sources(alert)
    alert["reports_analyzed"] = alert.get("reports_analyzed") or alert.get("num_reports") or 1

    # Cluster / anomaly flags
    alert["cluster_id"] = alert.get("cluster_id") or alert.get("series_id") or alert.get("incident_series")
    alert["anomaly_flag"] = alert.get("anomaly_flag", alert.get("is_anomaly", False))

    # Region trend (non-critical)
    city = alert.get("city") or alert.get("region") or alert.get("country")
    threat_type = alert.get("category") or alert.get("threat_label")
    try:
        incidents_365 = fetch_past_incidents(region=city, category=threat_type, days=365, limit=1000) or []
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

def summarize_alerts(alerts: list[dict]) -> list[dict]:
    os.makedirs(ENGINE_CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(ENGINE_CACHE_DIR, "enriched_alerts.json")
    failed_cache_path = os.path.join(ENGINE_CACHE_DIR, "alerts_failed.json")

    # --- Robust cache read (handles missing or corrupted JSON) ---
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cached_alerts = json.load(f)
        if not isinstance(cached_alerts, list):
            raise ValueError("Cache file is not a list")
    except FileNotFoundError:
        cached_alerts = []
    except Exception:
        logger.exception("Cache read failed; starting fresh.")
        cached_alerts = []

    new_alerts = deduplicate_alerts(
        alerts,
        existing_alerts=cached_alerts,
        openai_client=openai_client if ENABLE_SEMANTIC_DEDUP else None,
        sim_threshold=SEMANTIC_DEDUP_THRESHOLD,
        enable_semantic=ENABLE_SEMANTIC_DEDUP,
    )

    if not new_alerts:
        # Also filter cached on relevance so old junk doesn't persist
        return [a for a in cached_alerts if is_relevant(a)]

    summarized: list[dict] = []
    failed_alerts: list[dict] = []
    failed_alerts_lock = threading.Lock()

    def process(alert):
        try:
            return summarize_single_alert(alert)
        except Exception as e:
            logger.error(f"[ThreatEngine] Failed to enrich alert: {e}")
            with failed_alerts_lock:
                failed_alerts.append(alert)
            return None

    workers = max(1, min(ENGINE_MAX_WORKERS, len(new_alerts)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        processed = list(executor.map(process, new_alerts))

    # Apply relevance filter to newly processed alerts
    summarized.extend([res for res in processed if res is not None and is_relevant(res)])

    # Merge with cache (de-dup by content hash) — filter cached too
    filtered_cached = [a for a in cached_alerts if is_relevant(a)]
    all_alerts = filtered_cached + summarized
    seen = set()
    unique_alerts = []
    for alert in all_alerts:
        h = alert_hash(alert)
        if h in seen:
            continue
        alert["label"] = alert.get("label", alert.get("threat_label", "Unknown"))
        # Defensive defaults
        alert["incident_count_30d"] = alert.get("incident_count_30d", 0)
        alert["recent_count_7d"] = alert.get("recent_count_7d", 0)
        alert["baseline_avg_7d"] = alert.get("baseline_avg_7d", 0.0)
        alert["baseline_ratio"] = alert.get("baseline_ratio", 1.0)
        alert["trend_direction"] = alert.get("trend_direction", "stable")
        alert["latitude"] = alert.get("latitude")
        alert["longitude"] = alert.get("longitude")
        unique_alerts.append(alert)
        seen.add(h)

    # Persist cache
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(unique_alerts, f, indent=2, ensure_ascii=False, default=json_default)

    # Persist failures (backup)
    if failed_alerts:
        try:
            old_failed = []
            if os.path.exists(failed_cache_path):
                with open(failed_cache_path, "r", encoding="utf-8") as f:
                    old_failed = json.load(f)
            failed_hashes = {alert_hash(a) for a in old_failed}
            for alert in failed_alerts:
                h = alert_hash(alert)
                if h not in failed_hashes:
                    alert["label"] = alert.get("label", alert.get("threat_label", "Unknown"))
                    alert["incident_count_30d"] = alert.get("incident_count_30d", 0)
                    alert["recent_count_7d"] = alert.get("recent_count_7d", 0)
                    alert["baseline_avg_7d"] = alert.get("baseline_avg_7d", 0.0)
                    alert["baseline_ratio"] = alert.get("baseline_ratio", 1.0)
                    alert["trend_direction"] = alert.get("trend_direction", "stable")
                    alert["latitude"] = alert.get("latitude")
                    alert["longitude"] = alert.get("longitude")
                    old_failed.append(alert)
                    failed_hashes.add(h)
            with open(failed_cache_path, "w", encoding="utf-8") as f:
                json.dump(old_failed, f, indent=2, ensure_ascii=False, default=json_default)
        except Exception as e:
            logger.error(f"[Failed alert backup error] {e}")

    return unique_alerts

def get_raw_alerts(region=None, country=None, city=None, limit=1000):
    return fetch_raw_alerts_from_db(region=region, country=country, city=city, limit=limit)

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
    if a.get("incident_count_30d") is None:
        a["incident_count_30d"] = 0
    if a.get("recent_count_7d") is None:
        a["recent_count_7d"] = 0
    a["latitude"] = a.get("latitude")
    a["longitude"] = a.get("longitude")
    return a

def enrich_and_store_alerts(region=None, country=None, city=None, limit=1000, write_to_db: bool = ENGINE_WRITE_TO_DB):
    raw_alerts = get_raw_alerts(region=region, country=country, city=city, limit=limit)
    if not raw_alerts:
        logger.info("No raw alerts to process.")
        return []

    logger.info(f"Fetched {len(raw_alerts)} raw alerts. Starting enrichment and filtering...")
    enriched_alerts = summarize_alerts(raw_alerts)

    if enriched_alerts and write_to_db:
        normalized = [_normalize_for_db(x) for x in enriched_alerts]
        logger.info(f"Storing {len(normalized)} enriched alerts to alerts table...")
        try:
            save_alerts_to_db(normalized)
            logger.info("Enriched alerts saved to DB successfully.")
        except Exception as e:
            logger.error(f"Failed to save alerts to DB: {e}")
            if ENGINE_FAIL_CLOSED:
                raise

    elif enriched_alerts and not write_to_db:
        logger.warning("ENGINE_WRITE_TO_DB is FALSE — skipping DB save.")

    else:
        logger.info("No enriched alerts to store.")

    return enriched_alerts

# ---------- CLI ----------

if __name__ == "__main__":
    logger.info("Running threat engine enrichment pipeline...")
    try:
        out = enrich_and_store_alerts(limit=1000, write_to_db=ENGINE_WRITE_TO_DB)
        logger.info("Threat engine enrichment done. alerts=%s", len(out or []))
    except KeyboardInterrupt:
        import sys; sys.exit(130)
    except Exception:
        logger.exception("Fatal error in threat_engine")
        import sys; sys.exit(1)
