# threat_engine.py — Sentinel Threat Engine
# v2025-08-31 (aligned with rss_processor kw_match + risk_shared.detect_domains)
# - Reads raw_alerts -> enriches -> writes alerts (client-facing)
# - Aligns with your alerts schema (domains, baseline metrics, trend, sources, etc.)
# - Defensive defaults + backward compatibility (is_anomaly -> anomaly_flag, series_id/incident_series -> cluster_id)

from __future__ import annotations

import os
import json
import re
import hashlib
import threading
import fcntl
import tempfile
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pycountry
from dotenv import load_dotenv
from decimal import Decimal  # <-- for safe JSON default

# Structured logging setup
from logging_config import get_logger, get_metrics_logger
logger = get_logger("threat_engine")
metrics = get_metrics_logger("threat_engine")

# Input validation
from validation import validate_alert, validate_alert_batch, validate_enrichment_data

# -------- Optional LLM clients / prompts (do not fail engine if absent) --------
try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # type: ignore

# New: optional wrappers (safe imports)
try:
    from deepseek_client import deepseek_chat
except Exception:
    deepseek_chat = None  # type: ignore

try:
    from openai_client_wrapper import openai_chat
except Exception:
    openai_chat = None  # type: ignore

try:
    # Your existing file — we call grok_chat from here
    from xai_client import grok_chat
except Exception:
    grok_chat = None  # type: ignore

try:
    from prompts import THREAT_SUMMARIZE_SYSTEM_PROMPT
except Exception:
    THREAT_SUMMARIZE_SYSTEM_PROMPT = None

try:
    from vector_dedup import VectorDeduplicator
    from risk_shared import get_embedding as get_managed_embedding
except Exception:
    VectorDeduplicator = None
    get_managed_embedding = None
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
    detect_domains,          # <-- use canonical domains from risk_shared
    relevance_flags,         # <-- sports/info-ops light flags
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

from llm_router import route_llm, route_llm_search

# -------- Centralized Confidence Scoring --------

def _clamp_score(val: float, min_val: float = 0.0, max_val: float = 100.0) -> float:
    try:
        return max(min_val, min(max_val, float(val)))
    except Exception:
        return 0.0

def _parse_timestamp(ts) -> Optional[datetime]:
    """Best-effort timestamp parser for SOCMINT post timestamps."""
    try:
        if ts is None:
            return None
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts)
        if isinstance(ts, str):
            s = ts.strip()
            if s.endswith('Z'):
                s = s.replace('Z', '+00:00')
            try:
                return datetime.fromisoformat(s)
            except Exception:
                # Fallback common formats
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                    try:
                        return datetime.strptime(s, fmt)
                    except Exception:
                        continue
        return None
    except Exception:
        return None

def is_recent(ts, days: int = 7) -> bool:
    dt = _parse_timestamp(ts)
    if not dt:
        return False
    try:
        # Normalize timezone-aware datetimes to naive UTC for safe subtraction
        if getattr(dt, 'tzinfo', None) is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        now_utc = datetime.utcnow()
        return (now_utc - dt).days <= int(days)
    except Exception:
        return False

def contains_ioc(text: str) -> bool:
    """Lightweight IOC detector for post text: IPs, domains, CVEs, hashes, emails."""
    if not text:
        return False
    import re
    patterns = [
        r"\b(?:\d{1,3}\.){3}\d{1,3}\b",                 # IPv4
        r"\bCVE-\d{4}-\d{4,7}\b",                        # CVE
        r"\b[a-f0-9]{32}\b",                              # MD5
        r"\b[a-f0-9]{64}\b",                              # SHA-256
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",  # Email
        r"\b[a-z0-9][-a-z0-9]{1,61}[a-z0-9]\.(com|net|org|io|ru|cn|xyz|info|biz|co|uk|de|jp|fr|in|it|es)\b",
    ]
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)

def calculate_socmint_score(socmint_data: dict) -> float:
    """Compute a 0-100 score from SOCMINT profile/posts per provided rubric."""
    try:
        score = 0.0
        if not isinstance(socmint_data, dict):
            return 0.0
        # Instagram returns 'profile', Facebook returns 'page_info' – normalize
        profile = socmint_data.get('profile') or socmint_data.get('page_info') or {}
        posts = socmint_data.get('posts') or []

        # Follower count threshold (loud actors = higher risk)
        followers = (
            profile.get('followersCount')
            or profile.get('followers')
            or profile.get('likes')
            or 0
        )
        try:
            followers = int(followers or 0)
        except Exception:
            followers = 0
        if followers > 100000:
            score += 15
        elif followers > 10000:
            score += 10
        elif followers > 1000:
            score += 5

        # Verified status (verified actors less likely to be imposters)
        if bool(profile.get('verified')):
            score -= 10

        # Recent activity (stale accounts are lower priority)
        last_post_date = posts[0].get('timestamp') if posts and isinstance(posts[0], dict) else None
        if last_post_date and is_recent(last_post_date, days=7):
            score += 10

        # IOC mention frequency in posts
        try:
            ioc_count = sum(1 for p in posts if contains_ioc((p or {}).get('text', '')))
        except Exception:
            ioc_count = 0
        score += min(ioc_count * 5, 20)  # Cap at 20

        return _clamp_score(score, 0.0, 100.0)
    except Exception:
        return 0.0

def compute_confidence(
    alert: dict,
    confidence_type: str = "overall",
    **kwargs
) -> float:
    """
    Centralized confidence scoring function for all threat engine components.
    
    Args:
        alert: Alert dictionary with relevant fields
        confidence_type: Type of confidence to compute
            - "overall": Combined confidence score (default)
            - "category": Category classification confidence
            - "location": Location determination confidence
            - "threat": Threat assessment confidence
            - "custom": Custom confidence with additional parameters
        **kwargs: Additional parameters for specific confidence types
    
    Returns:
        float: Confidence score between 0.0 and 1.0
    """
    
    def _clamp(val: float, min_val: float = 0.0, max_val: float = 1.0) -> float:
        """Helper to clamp values within bounds"""
        return max(min_val, min(max_val, val))
    
    if confidence_type == "category":
        # Category classification confidence
        category = alert.get("category", "")
        category_confidence = float(alert.get("category_confidence", 0.0))
        
        # If already calculated, return it
        if category_confidence > 0:
            return _clamp(category_confidence)
        
        # Calculate based on available signals
        conf = 0.5  # base confidence
        
        # Keyword match strength
        kw_match = alert.get("kw_match", {})
        if isinstance(kw_match, dict):
            rule = (kw_match.get("rule") or "").lower()
            if "broad+impact" in rule and "sentence" in rule:
                conf += 0.2
            elif "broad+impact" in rule:
                conf += 0.15
            elif "specific" in rule:
                conf += 0.1
        
        # Text quality indicators
        text_content = alert.get("summary", "") or alert.get("title", "")
        if len(text_content) > 100:  # Sufficient content
            conf += 0.1
        
        # Domain alignment
        domains = alert.get("domains", [])
        if domains and category:
            # Check if domains align with category
            security_domains = ["security", "military", "cyber", "terror", "crime"]
            if category.lower() in ["security", "terrorism", "cyber"] and any(d in security_domains for d in domains):
                conf += 0.1
        
        return _clamp(conf, 0.2, 0.95)
    
    elif confidence_type == "location":
        # Location determination confidence
        location_method = alert.get("location_method", "none")
        location_confidence = alert.get("location_confidence", "none")
        
        # Standardized location confidence mapping
        confidence_weights = {
            "high": 0.9,      # NER, keywords, coordinates
            "medium": 0.7,    # LLM extraction
            "low": 0.5,       # feed_tag, fuzzy matching
            "none": 0.2       # no location determined
        }
        
        base_conf = confidence_weights.get(location_confidence, 0.2)
        
        # Boost confidence if we have coordinates
        if alert.get("latitude") and alert.get("longitude"):
            base_conf = min(base_conf + 0.1, 1.0)
        
        # Boost confidence if location is mentioned multiple times
        text_content = (alert.get("summary", "") + " " + alert.get("title", "")).lower()
        location_mentions = 0
        for field in ["country", "city", "region"]:
            if alert.get(field) and alert[field].lower() in text_content:
                location_mentions += 1
        
        if location_mentions >= 2:
            base_conf = min(base_conf + 0.05 * location_mentions, 1.0)
        
        return _clamp(base_conf, 0.1, 0.95)
    
    elif confidence_type == "threat":
        # Threat assessment confidence (from threat_scorer logic)
        score = alert.get("threat_score", 0) or 0
        if score is None:
            score = 0
        
        # Base confidence
        conf = 0.6
        
        # Distance from neutral (50) increases confidence, but penalize very low scores
        score_distance = abs(float(score) - 50.0) / 50.0
        if score < 30:
            # Very low scores get confidence penalty
            conf += 0.1 * score_distance - 0.2
        else:
            conf += 0.2 * score_distance
        
        # Keyword weight bonus
        kw_weight = alert.get("keyword_weight", 0) or 0
        if kw_weight is None:
            kw_weight = 0
        if float(kw_weight) > 0.6:
            conf += 0.1
        
        # Trigger bonus
        triggers = alert.get("triggers", []) or []
        if triggers is None:
            triggers = []
        trig_norm = min(len(triggers), 6) / 6.0
        if trig_norm > 0.5:
            conf += 0.05
        
        # kw_rule bonus
        kw_match = alert.get("kw_match", {})
        if isinstance(kw_match, dict):
            rule = (kw_match.get("rule") or "").lower()
            if "broad+impact" in rule and ("sentence" in rule or "sent" in rule):
                conf += 0.05
            elif "broad+impact" in rule and "window" in rule:
                conf += 0.03
        
        # High score confidence floor
        if score >= 85.0:
            conf = max(conf, 0.75)
        
        return _clamp(conf, 0.4, 0.95)
    
    elif confidence_type == "overall":
        # Combined overall confidence
        category_conf = compute_confidence(alert, "category")
        location_conf = compute_confidence(alert, "location")
        threat_conf = compute_confidence(alert, "threat")
        
        # Weighted average with emphasis on threat assessment
        weights = {
            "threat": 0.5,
            "category": 0.3,
            "location": 0.2
        }
        
        overall_conf = (
            threat_conf * weights["threat"] +
            category_conf * weights["category"] +
            location_conf * weights["location"]
        )
        
        # Boost for data completeness
        completeness_score = 0
        required_fields = ["category", "threat_score", "summary"]
        for field in required_fields:
            if alert.get(field):
                completeness_score += 1
        
        completeness_bonus = (completeness_score / len(required_fields)) * 0.1
        overall_conf = min(overall_conf + completeness_bonus, 1.0)
        
        return _clamp(overall_conf, 0.3, 0.95)
    
    elif confidence_type == "custom":
        # Custom confidence calculation with provided parameters
        base_confidence = kwargs.get("base", 0.5)
        
        # Apply custom modifiers
        for modifier, value in kwargs.items():
            if modifier.startswith("boost_") and isinstance(value, (int, float)):
                base_confidence += value
            elif modifier.startswith("penalty_") and isinstance(value, (int, float)):
                base_confidence -= value
        
        return _clamp(base_confidence)
    
    else:
        logger.warning("unknown_confidence_type", confidence_type=confidence_type)
        return 0.5  # default fallback

# ---------- Setup ----------
# Logging already configured in imports

# New: simple per-run counters for model usage & a safe bucket state
_model_usage_counts = {"deepseek": 0, "openai": 0, "grok": 0, "moonshot": 0, "none": 0}
_bucket_daily_counts = {}  # prevents earlier NameError if referenced by external utils

def json_default(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    # Fix: make Decimal JSON-serializable
    if isinstance(obj, Decimal):
        try:
            return float(obj)
        except Exception:
            return str(obj)
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

def _atomic_write_json(path, data):
    """
    Atomic JSON write using temporary file + rename to prevent race conditions.
    
    This prevents concurrent threads from corrupting JSON cache files by:
    1. Writing to a temporary file in the same directory
    2. Using atomic rename operation (POSIX guarantees atomicity)
    3. Cleaning up temp file on failure
    
    Args:
        path: Target file path for JSON data
        data: Data to serialize to JSON
    """
    dir_path = os.path.dirname(path)
    os.makedirs(dir_path, exist_ok=True)
    
    # Create temp file in same directory to ensure same filesystem
    fd, tmp_path = tempfile.mkstemp(suffix='.tmp', dir=dir_path)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=json_default)
        
        # Atomic rename (POSIX guarantees atomicity)
        os.replace(tmp_path, path)
    except Exception:
        # Clean up temp file on any failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass  # Temp file may already be cleaned up
        raise

load_dotenv()


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")  # used by deepseek_client.py
XAI_API_KEY = os.getenv("XAI_API_KEY")          # used by xai_client.py
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
XAI_MODEL = os.getenv("XAI_MODEL", "grok-3-mini")  # hint for your xai client; not enforced here

# Configuration for enrichment pipeline
USE_MODULAR_ENRICHMENT = os.getenv("USE_MODULAR_ENRICHMENT", "true").lower() == "true"

if RAILWAY_ENV:
    logger.info("environment_check", railway_env=RAILWAY_ENV)
else:
    logger.info("environment_check", railway_env=None, mode="local")

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

# New modular enrichment system
try:
    from enrichment_stages import get_enrichment_pipeline, enrich_single_alert as modular_enrich_alert
    MODULAR_ENRICHMENT_AVAILABLE = True
except ImportError as e:
    logger.warning("modular_enrichment_unavailable", error=str(e))
    MODULAR_ENRICHMENT_AVAILABLE = False
    modular_enrich_alert = None

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

def get_embedding(text: str, client=None):
    """
    Legacy embedding function - redirects to managed embedding system.
    Kept for backward compatibility.
    """
    if get_managed_embedding is not None:
        return get_managed_embedding(text, client)
    
    # Fallback to hash-based pseudo-embedding if managed system unavailable
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
    existing_alerts: list[dict] = None,
    openai_client=None,
    sim_threshold: float = SEMANTIC_DEDUP_THRESHOLD,
    enable_semantic: bool = ENABLE_SEMANTIC_DEDUP,
):
    """
    Deduplicate alerts using hash-based and vector-based similarity.
    Uses direct pgvector database queries for efficient semantic deduplication.
    """
    if not alerts:
        return []
    
    # Hash-based deduplication first (fast exact/near-exact matches)
    known_hashes = {alert_hash(a): a for a in (existing_alerts or [])}
    deduped_alerts = []

    for alert in alerts or []:
        h = alert_hash(alert)
        if h in known_hashes:
            # Merge small title/summary updates in-place
            existing = known_hashes[h]
            for field in ("title", "summary"):
                if alert.get(field, "") and alert.get(field) != existing.get(field, ""):
                    existing[field] = alert.get(field, "")
            continue

        # Vector-based semantic deduplication
        if enable_semantic and openai_client:
            try:
                text = f"{alert.get('title','')} {alert.get('summary','')}"[:4096]
                
                # Use the quota-managed embedding system
                from risk_shared import embedding_manager
                emb = embedding_manager.get_embedding_safe(text, openai_client)
                
                # Check vector DB for similarity using pgvector-compatible queries
                if emb:
                    try:
                        # pgvector-compatible approach using REAL[] arrays
                        from db_utils import fetch_one
                        row = fetch_one(
                            "SELECT uuid, 1 - (embedding <=> %s::REAL[]) as similarity FROM alerts WHERE embedding IS NOT NULL AND 1 - (embedding <=> %s::REAL[]) > %s ORDER BY embedding <=> %s::REAL[] LIMIT 1",
                            (emb, emb, sim_threshold, emb)
                        )
                        
                        if row and len(row) >= 2:
                            similarity = float(row[1])
                            duplicate_uuid = row[0]
                            logger.info("semantic_duplicate_detected", 
                                       alert_uuid=alert.get('uuid'),
                                       duplicate_uuid=duplicate_uuid,
                                       similarity=round(similarity, 3),
                                       method="pgvector")
                            continue  # Skip duplicate
                        
                        # Add embedding to alert for persistence by save_alerts_to_db()
                        alert["embedding"] = emb
                        
                    except Exception as e:
                        logger.warning(f"pgvector query failed, trying fallback: {e}")
                        
                        # Fallback to JSONB approach if needed
                        import json
                        embedding_json = json.dumps(emb)
                        magnitude = (sum(x * x for x in emb) ** 0.5)
                        row = fetch_one(
                            "SELECT alert_uuid, similarity FROM find_similar_alerts_fast(%s::JSONB, %s, %s, 1, 0.1)",
                            (embedding_json, magnitude, sim_threshold)
                        )
                        
                        if row and len(row) >= 2:
                            similarity = float(row[1])
                            duplicate_uuid = row[0]
                            logger.info("semantic_duplicate_detected",
                                       alert_uuid=alert.get('uuid'),
                                       duplicate_uuid=duplicate_uuid, 
                                       similarity=round(similarity, 3),
                                       method="fallback")
                            continue  # Skip duplicate
                        
                        alert["embedding"] = emb
                    
            except Exception as e:
                logger.warning(f"Semantic dedup failed for alert, using hash-only: {e}")

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

# ---------- Relevance Filtering ----------
def is_relevant(alert: dict) -> bool:
    """
    Lightweight relevance gate to exclude non-security junk while keeping recall.
    More lenient for raw alerts that haven't been enriched yet.
    """
    text = (alert.get("title","") + " " + alert.get("summary","")).lower()
    flags = alert.get("relevance_flags") or relevance_flags(text)

    # Sports / entertainment obvious noise
    if "sports_context" in (flags or []):
        return False
    if any(bad in text for bad in [
        "football","basketball","soccer","tennis","nba","nfl","fifa","cricket","olympics",
        "concert","music festival","award show","box office","celebrity",
        "bundesliga","hsv","bvb","rb leipzig","hoffenheim"
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

    # For raw alerts that haven't been processed yet, be more lenient
    category = alert.get("category")
    domains = alert.get("domains") or []
    category_confidence = float(alert.get("category_confidence") or 0.0)
    
    # If no explicit category confidence, calculate it using centralized function
    if category_confidence == 0.0 and category:
        category_confidence = compute_confidence(alert, "category")
    
    # If this is a raw alert (no category/domains), allow it through for enrichment
    if not category and not domains:
        return True
    
    # For enriched alerts, apply stricter confidence-based filters
    if category_confidence > 0 and category_confidence < 0.35:
        return False

    # Domains must be present for enriched alerts — unless kw_rule flagged a strong broad+impact match
    kw_rule = (alert.get("kw_rule") or "").lower()
    if category and not domains:
        strong_rule = ("broad+impact" in kw_rule)
        if not strong_rule:
            return False

    return True

def is_relevant_for_category(alert: dict, target_category: str = None, target_region: str = None) -> bool:
    """
    Enhanced relevance check that considers category alignment and location relevance.
    More lenient for raw alerts that haven't been enriched yet.
    """
    # For raw alerts without category/domains, apply basic text-based filtering
    alert_category = alert.get("category", "").lower()
    alert_domains = alert.get("domains", [])
    alert_text = (alert.get("title", "") + " " + alert.get("summary", "")).lower()
    
    # Apply basic relevance filter (now more lenient for raw alerts)
    if not is_relevant(alert):
        return False
    
    # If no target category specified, use basic relevance
    if not target_category:
        return True
    
    target_cat_lower = target_category.lower()
    
    # Direct category match (if category is populated)
    if alert_category and target_cat_lower in alert_category:
        return True
    
    # Enhanced category matching with keyword detection for all alerts
    if target_cat_lower == "cybersecurity" or target_cat_lower == "cyber":
        # Check domains first (if present)
        cyber_domains = ["cyber_it", "digital_privacy_surveillance"]
        if alert_domains and any(domain in alert_domains for domain in cyber_domains):
            return True
        
        # Fallback to keyword detection in text (works for raw alerts)
        # Be more strict - require strong cybersecurity indicators
        strong_cyber_keywords = [
            "cyber", "hack", "breach", "malware", "ransomware", "phishing", 
            "ddos", "vulnerability", "exploit", "data theft", "cybersecurity",
            "intrusion", "backdoor", "trojan", "spyware", "botnet"
        ]
        weak_cyber_keywords = [
            "security", "firewall", "antivirus", "encryption", "password", 
            "authentication", "network"
        ]
        
        # Require either strong keywords OR weak keywords with additional context
        has_strong = any(keyword in alert_text for keyword in strong_cyber_keywords)
        has_weak_with_context = (
            any(keyword in alert_text for keyword in weak_cyber_keywords) and
            any(context in alert_text for context in ["threat", "attack", "risk", "incident", "alert", "warning"])
        )
        
        if has_strong or has_weak_with_context:
            return True
    
    elif target_cat_lower == "infrastructure":
        infra_domains = ["infrastructure_utilities", "travel_mobility"]
        if alert_domains and any(domain in alert_domains for domain in infra_domains):
            return True
        
        infra_keywords = [
            "infrastructure", "power grid", "electricity", "water supply",
            "transportation", "railway", "airport", "bridge", "tunnel",
            "energy", "utility", "pipeline", "outage"
        ]
        if any(keyword in alert_text for keyword in infra_keywords):
            return True
    
    elif target_cat_lower == "physical_safety":
        safety_domains = ["physical_safety", "civil_unrest", "terrorism"]
        if alert_domains and any(domain in alert_domains for domain in safety_domains):
            return True
        
        safety_keywords = [
            "violence", "attack", "threat", "terrorism", "protest", "riot",
            "shooting", "bomb", "explosion", "crime", "assault", "murder",
            "kidnapping", "hostage"
        ]
        if any(keyword in alert_text for keyword in safety_keywords):
            return True
    
    elif target_cat_lower == "health" or target_cat_lower == "epidemic":
        health_domains = ["public_health_epidemic", "environmental_hazards"]
        if alert_domains and any(domain in alert_domains for domain in health_domains):
            return True
        
        health_keywords = [
            "disease", "outbreak", "epidemic", "virus", "bacteria", "infection",
            "health", "medical", "hospital", "vaccine", "contamination",
            "pandemic", "illness", "poisoning"
        ]
        if any(keyword in alert_text for keyword in health_keywords):
            return True
    
    # For broad categories, be more inclusive
    elif target_cat_lower in ["crime", "terrorism", "civil unrest"]:
        crime_keywords = [
            "crime", "criminal", "theft", "robbery", "fraud", "murder",
            "terrorism", "terrorist", "bomb", "attack", "threat",
            "protest", "riot", "demonstration", "violence", "unrest"
        ]
        if any(keyword in alert_text for keyword in crime_keywords):
            return True
    
    # Location relevance check (more flexible)
    if target_region:
        alert_region = (alert.get("region") or "").lower()
        alert_country = (alert.get("country") or "").lower()
        alert_city = (alert.get("city") or "").lower()
        target_region_lower = target_region.lower()
        
        location_match = (
            target_region_lower in alert_region or
            target_region_lower in alert_country or
            target_region_lower in alert_city or
            alert_region in target_region_lower or
            alert_country in target_region_lower
        )
        
        # For "Europe", also check for European country names
        if target_region_lower == "europe":
            european_countries = [
                "germany", "france", "italy", "spain", "poland", "romania", 
                "netherlands", "belgium", "greece", "portugal", "czech", 
                "hungary", "sweden", "austria", "belarus", "switzerland",
                "bulgaria", "serbia", "denmark", "finland", "slovakia",
                "norway", "ireland", "croatia", "bosnia", "albania",
                "lithuania", "slovenia", "latvia", "estonia", "macedonia",
                "moldova", "luxembourg", "malta", "iceland", "montenegro",
                "uk", "united kingdom", "britain", "england", "scotland",
                "wales", "ukraine", "russia"
            ]
            if any(country in alert_text or country in alert_country or country in alert_region for country in european_countries):
                location_match = True
        
        if not location_match:
            return False
    
    return True

def get_category_specific_alerts(region=None, country=None, city=None, category=None, limit=1000):
    """
    Fetch raw alerts with enhanced filtering for category and location relevance.
    """
    raw_alerts = fetch_raw_alerts_from_db(region=region, country=country, city=city, limit=limit)
    
    if not category:
        return raw_alerts
    
    # Debug: log sample alert details
    if raw_alerts:
        sample_alert = raw_alerts[0]
        logger.info(f"Sample alert - Category: {sample_alert.get('category')}, Domains: {sample_alert.get('domains')}, "
                   f"Title: {sample_alert.get('title', '')[:100]}...")
    
    # Filter alerts for category relevance
    relevant_alerts = []
    for alert in raw_alerts:
        if is_relevant_for_category(alert, target_category=category, target_region=region):
            relevant_alerts.append(alert)
    
    logger.info(f"Filtered {len(raw_alerts)} raw alerts to {len(relevant_alerts)} category-relevant alerts for {category}")
    return relevant_alerts

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
    """Alert enrichment function with modular pipeline support.
    
    This function uses the new modular enrichment pipeline when available,
    with fallback to legacy behavior for backward compatibility.
    """
    # Use modular enrichment if available and enabled
    if USE_MODULAR_ENRICHMENT and MODULAR_ENRICHMENT_AVAILABLE and modular_enrich_alert:
        try:
            logger.debug("using_modular_enrichment_pipeline", 
                        alert_uuid=alert.get("uuid", "no-uuid"))
            
            result = modular_enrich_alert(alert)
            
            if result is None:
                # Check if this was a validation error vs. content filtering
                from validation import validate_alert
                is_valid, error = validate_alert(alert)
                if not is_valid:
                    raise ValueError(f"Alert validation failed: {error}")
                
                # Otherwise it was content filtering, return None
                logger.info("alert_filtered_by_modular_pipeline", 
                           alert_uuid=alert.get("uuid", "no-uuid"))
                return None
            
            return result
            
        except Exception as e:
            logger.error("modular_enrichment_failed_fallback_to_legacy", 
                        alert_uuid=alert.get("uuid", "no-uuid"),
                        error=str(e))
            # Fall through to legacy enrichment
    
    # Legacy enrichment logic (maintained for backward compatibility)
    logger.debug("using_legacy_enrichment", 
                alert_uuid=alert.get("uuid", "no-uuid"))
    
    # Validate input alert structure
    is_valid, error = validate_alert(alert)
    if not is_valid:
        logger.error("single_alert_validation_failed", 
                    alert_uuid=alert.get("uuid", "no-uuid"),
                    error=error)
        raise ValueError(f"Alert validation failed: {error}")
    
    title = alert.get("title", "") or ""
    summary = alert.get("summary", "") or ""
    full_text = f"{title}\n{summary}".strip()
    location = alert.get("city") or alert.get("region") or alert.get("country")
    triggers = alert.get("tags", [])

    # Enhance with location confidence data
    alert = enhance_location_confidence(alert)

    # Lightweight relevance flags for diagnostics (sports/info-ops)
    try:
        alert["relevance_flags"] = relevance_flags(full_text)
    except Exception:
        alert["relevance_flags"] = []

    # Threat scoring (consumes kw_match if present from rss_processor)
    threat_score_data = assess_threat_level(
        alert_text=full_text,
        triggers=triggers,
        location=location,
        alert_uuid=alert.get("uuid"),
        plan="FREE",
        enrich=True,
        user_email=None,
        source_alert=alert  # passes kw_match through to scorer
    ) or {}

    # Merge score outputs
    for k, v in threat_score_data.items():
        alert[k] = v

    # Calculate overall confidence using centralized function
    try:
        alert["overall_confidence"] = compute_confidence(alert, "overall")
        logger.debug(f"[ThreatEngine][Confidence] Alert {alert.get('uuid', 'N/A')}: "
                    f"overall={alert['overall_confidence']:.2f}, "
                    f"category={alert.get('category_confidence', 0):.2f}, "
                    f"location={alert.get('location_reliability', 0):.2f}")
    except Exception as e:
        logger.warning(f"[ThreatEngine][ConfidenceError] {e}")
        alert["overall_confidence"] = 0.5

    # Augment threat score with SOCMINT signal (30% weight)
    try:
        osint_list = (alert.get('enrichments') or {}).get('osint') or []
        socmint_raw_scores = []
        for entry in osint_list:
            data = (entry or {}).get('data') or {}
            socmint_raw_scores.append(calculate_socmint_score(data))
        if socmint_raw_scores:
            socmint_best = max(socmint_raw_scores)
            socmint_weighted = round(socmint_best * 0.3, 2)
            base_score = float(alert.get('threat_score', 0) or 0)
            alert['threat_score_components'] = {
                **(alert.get('threat_score_components') or {}),
                'socmint_raw': socmint_best,
                'socmint_weighted': socmint_weighted,
                'socmint_weight': 0.3,
            }
            alert['threat_score'] = _clamp_score(base_score + socmint_weighted)
    except Exception as e:
        logger.warning(f"[ThreatEngine][SOCMINT Score Augment Error] {e}")

    # risk_shared analytics (best-effort)
    try: 
        alert["sentiment"] = run_sentiment_analysis(full_text)
    except Exception as e: 
        logger.warning(f"[THREAT_ENGINE] Sentiment analysis failed: {e}")
        alert["sentiment"] = None
        
    try: 
        alert["forecast"] = run_forecast(full_text, location=location)
    except Exception as e: 
        logger.warning(f"[THREAT_ENGINE] Forecast analysis failed: {e}")
        alert["forecast"] = None
        
    try: 
        alert["legal_risk"] = run_legal_risk(full_text)
    except Exception as e: 
        logger.warning(f"[THREAT_ENGINE] Legal risk analysis failed: {e}")
        alert["legal_risk"] = None
        
    try: 
        alert["cyber_ot_risk"] = run_cyber_ot_risk(full_text)
    except Exception as e: 
        logger.warning(f"[THREAT_ENGINE] Cyber OT risk analysis failed: {e}")
        alert["cyber_ot_risk"] = None
        
    try: 
        alert["environmental_epidemic_risk"] = run_environmental_epidemic_risk(full_text)
    except Exception as e: 
        logger.warning(f"[THREAT_ENGINE] Environmental epidemic risk analysis failed: {e}")
        alert["environmental_epidemic_risk"] = None
        
    try: 
        alert["keyword_weight"] = compute_keyword_weight(full_text)
    except Exception as e: 
        logger.warning(f"[THREAT_ENGINE] Keyword weight analysis failed: {e}")
        alert["keyword_weight"] = None

    # Quick LLM summary (now routed & tracked)
    messages = [
    {"role": "system", "content": THREAT_SUMMARIZE_SYSTEM_PROMPT},
    {"role": "user", "content": full_text},
    ]
    g_summary, model_used = route_llm(messages, temperature=TEMPERATURE, usage_counts=_model_usage_counts, task_type="enrichment")
    alert["gpt_summary"] = g_summary or alert.get("gpt_summary") or ""
    alert["model_used"] = model_used  # <-- explicit auditability

    # Category/subcategory (fallbacks if missing)
    if not alert.get("category") or not alert.get("category_confidence"):
        try:
            cat, cat_conf = extract_threat_category(full_text)
            alert["category"] = cat
            alert["category_confidence"] = cat_conf
        except Exception as e:
            logger.error(f"[ThreatEngine][CategoryFallbackError] {e}")
            alert["category"] = alert.get("category", "Other")
            # Use centralized confidence scoring for fallback
            alert["category_confidence"] = compute_confidence(alert, "category")

    # ENHANCED: Sports/Entertainment Filter - reject non-security content
    category = alert.get("category", "")
    title_lower = (alert.get("title", "") or "").lower()
    summary_lower = (alert.get("summary", "") or "").lower()
    
    sports_keywords = [
        "football", "soccer", "basketball", "tennis", "cricket", "rugby", "hockey",
        "champion", "trophy", "tournament", "league", "match", "goal", "score",
        "player", "team", "coach", "stadium", "fifa", "uefa", "olympics",
        "hat-trick", "galatasaray", "ajax", "super lig", "award", "transfer"
    ]
    
    entertainment_keywords = [
        "movie", "film", "actor", "actress", "celebrity", "concert", "music",
        "album", "song", "artist", "entertainment", "show", "tv", "series"
    ]
    
    is_sports = (
        category == "Sports" or
        any(keyword in title_lower for keyword in sports_keywords) or
        any(keyword in summary_lower for keyword in sports_keywords)
    )
    
    is_entertainment = (
        category == "Entertainment" or
        any(keyword in title_lower for keyword in entertainment_keywords) or
        any(keyword in summary_lower for keyword in entertainment_keywords)
    )
    
    if is_sports or is_entertainment:
        logger.info(f"Filtering out sports/entertainment content: {alert.get('title', '')[:80]}")
        return None  # Skip non-security content

    # Domains — canonical via risk_shared (prefer scorer's domains if present)
    try:
        alert["domains"] = alert.get("domains") or detect_domains(full_text)
    except Exception:
        alert["domains"] = alert.get("domains") or []

    # Historical & trend metrics
    historical_incidents = fetch_past_incidents(
        region=location, category=alert.get("category") or alert.get("threat_label"), days=7, limit=100
    ) or []
    alert["historical_incidents_count"] = len(historical_incidents)
    alert["avg_severity_past_week"] = stats_average_score(historical_incidents)

    # Baseline metrics
    alert.update(_baseline_metrics(alert))

    # After baseline metrics calculation - skip zero-incident alerts
    if alert.get("incident_count_30d", 0) == 0 and alert.get("recent_count_7d", 0) == 0:
        logger.info(f"Skipping alert with zero incidents: {alert.get('title', '')[:80]}")
        return None  # Don't enrich zero-incident alerts

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
    start_time = datetime.now()
    
    # Validate input alerts first
    valid_alerts, validation_errors = validate_alert_batch(alerts)
    
    if validation_errors:
        logger.warning("alert_validation_issues", 
                      total_alerts=len(alerts),
                      valid_alerts=len(valid_alerts),
                      validation_errors=len(validation_errors))
        for error in validation_errors[:5]:  # Log first 5 errors
            logger.error("alert_validation_failed", error=error)
    
    if not valid_alerts:
        logger.warning("no_valid_alerts_to_process", 
                      total_input=len(alerts),
                      validation_errors=len(validation_errors))
        return []
    
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
        valid_alerts,
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
        # Additional validation before processing (defensive)
        is_valid, error = validate_alert(alert)
        if not is_valid:
            logger.error("invalid_alert_skipped", 
                        alert_uuid=alert.get("uuid", "no-uuid"), 
                        error=error)
            return None
        
        try:
            start_time = datetime.now()
            result = summarize_single_alert(alert)
            
            if result:
                # Validate enriched result before returning
                is_valid_enriched, enriched_error = validate_enrichment_data(result)
                if not is_valid_enriched:
                    logger.error("enriched_alert_validation_failed",
                                alert_uuid=result.get("uuid", "no-uuid"),
                                error=enriched_error)
                    return None
                
                duration = (datetime.now() - start_time).total_seconds() * 1000
                metrics.alert_enriched(
                    alert_uuid=result.get("uuid"),
                    confidence=result.get("confidence", 0.0),
                    duration_ms=round(duration, 2),
                    location_confidence=result.get("location_confidence")
                )
            
            return result
            
        except Exception as e:
            logger.error("enrichment_failed", 
                        alert_uuid=alert.get("uuid", "no-uuid"),
                        error=str(e))
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
    _atomic_write_json(cache_path, unique_alerts)

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
            _atomic_write_json(failed_cache_path, old_failed)
        except Exception as e:
            logger.error(f"[Failed alert backup error] {e}")

    # End-of-run usage summary (nice for logs / cost tracking)
    try:
        total_proc = len(summarized)
        logger.info(
            "[Model usage summary] deepseek=%s, openai=%s, grok=%s, moonshot=%s, none=%s | Total processed: %s",
            _model_usage_counts["deepseek"],
            _model_usage_counts["openai"],
            _model_usage_counts["grok"],
            _model_usage_counts["moonshot"],
            _model_usage_counts["none"],
            total_proc
        )
    except Exception:
        pass

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
    # Preserve kw_match/kw_rule for observability if present
    if "kw_match" in a and "kw_rule" not in a:
        try:
            rule = (a["kw_match"] or {}).get("rule")
            if rule:
                a["kw_rule"] = rule
        except Exception:
            pass
    return a

def enrich_and_store_alerts(region=None, country=None, city=None, category=None, limit=1000, write_to_db: bool = ENGINE_WRITE_TO_DB):
    """
    Refactored enrichment and storage function with:
    - Atomic cache operations
    - Vector-based deduplication
    - Rate limiting and concurrency control
    - Circuit breaker pattern for DB operations
    - Enhanced error handling and timeouts
    """
    start_time = datetime.now()
    
    # 1. Get raw alerts with validation
    raw_alerts = get_category_specific_alerts(region=region, country=country, city=city, category=category, limit=limit)
    
    if not raw_alerts:
        logger.info("raw_alerts_fetch", count=0, region=region, country=country, city=city, category=category)
        return []

    fetch_duration = (datetime.now() - start_time).total_seconds() * 1000
    logger.info("raw_alerts_fetched", 
               count=len(raw_alerts), 
               region=region, 
               country=country, 
               city=city, 
               category=category,
               fetch_duration_ms=round(fetch_duration, 2))
    
    # 2. Atomic cache read
    cache_path = os.path.join(ENGINE_CACHE_DIR, "enriched_alerts.json")
    cached_alerts = _atomic_read_json(cache_path)
    
    # 3. Vector-based deduplication (fast)
    dedup_start = datetime.now()
    new_alerts = deduplicate_alerts(
        raw_alerts,
        existing_alerts=cached_alerts,
        openai_client=openai_client if ENABLE_SEMANTIC_DEDUP else None,
        sim_threshold=SEMANTIC_DEDUP_THRESHOLD,
        enable_semantic=ENABLE_SEMANTIC_DEDUP,
    )
    dedup_duration = (datetime.now() - dedup_start).total_seconds() * 1000
    
    logger.info("deduplication_completed",
               raw_count=len(raw_alerts),
               new_count=len(new_alerts),
               cached_count=len(cached_alerts),
               dedup_duration_ms=round(dedup_duration, 2))
    
    if not new_alerts:
        logger.info("no_new_alerts_after_deduplication")
        # Return relevant cached alerts
        return [a for a in cached_alerts if is_relevant(a)]
    
    # 4. Process with rate limiting and circuit breakers
    summarized: list[dict] = []
    failed_alerts: list[dict] = []
    failed_alerts_lock = threading.Lock()
    
    # Use ThreadPoolExecutor but with semaphore to limit concurrent LLM calls
    max_llm_workers = 3  # Limit concurrent LLM calls to prevent API throttling
    workers = min(max_llm_workers, len(new_alerts))
    
    enrich_start = datetime.now()
    
    with ThreadPoolExecutor(max_workers=workers) as executor:
        # Submit with timeout
        futures = [executor.submit(summarize_single_alert, alert) for alert in new_alerts]
        
        try:
            # Process with overall timeout of 5 minutes
            for future in as_completed(futures, timeout=300):
                try:
                    # Individual alert timeout of 1 minute
                    result = future.result(timeout=60)
                    if result:  # Our modular pipeline returns None for filtered alerts
                        summarized.append(result)
                except Exception as e:
                    logger.error("alert_processing_timeout", error=str(e))
                    with failed_alerts_lock:
                        failed_alerts.append({"error": str(e), "timestamp": datetime.utcnow().isoformat()})
                        
        except Exception as e:
            logger.error("enrichment_executor_failed", error=str(e))
            # Cancel remaining futures
            for future in futures:
                future.cancel()
    
    enrich_duration = (datetime.now() - enrich_start).total_seconds() * 1000
    
    # Apply relevance filter to newly processed alerts
    relevant_summarized = [res for res in summarized if is_relevant(res)]
    
    logger.info("enrichment_stage_completed",
               new_alerts_count=len(new_alerts),
               enriched_count=len(summarized),
               relevant_count=len(relevant_summarized),
               failed_count=len(failed_alerts),
               workers_used=workers,
               enrichment_duration_ms=round(enrich_duration, 2))
    
    # 5. Normalize for DB
    normalized = [_normalize_for_db(x) for x in relevant_summarized]
    
    # 6. Atomic DB write with circuit breaker
    db_save_success = True
    if write_to_db and normalized:
        save_start = datetime.now()
        try:
            _save_with_circuit(normalized)  # Circuit breaker wrapper
            save_duration = (datetime.now() - save_start).total_seconds() * 1000
            
            logger.info("db_write_success", 
                       count=len(normalized),
                       save_duration_ms=round(save_duration, 2))
            
        except Exception as e:
            db_save_success = False
            logger.error("db_write_failed", 
                        count=len(normalized), 
                        error=str(e),
                        circuit_state=_circuit_breaker["state"])
            if ENGINE_FAIL_CLOSED:
                raise
    
    elif normalized and not write_to_db:
        logger.warning("alerts_not_saved", reason="write_to_db_disabled", count=len(normalized))
    
    # 7. Atomic cache update (combine with existing cached alerts and filter relevant)
    relevant_cached = [a for a in cached_alerts if is_relevant(a)]
    all_alerts = relevant_cached + normalized
    
    # Deduplicate the combined cache to prevent duplicates
    seen = set()
    unique_alerts = []
    for alert in all_alerts:
        h = alert_hash(alert)
        if h not in seen:
            seen.add(h)
            unique_alerts.append(alert)
    
    cache_write_success = _atomic_write_json(cache_path, unique_alerts)
    
    if not cache_write_success:
        logger.warning("cache_update_failed", cache_path=cache_path)
    
    # Log failed alerts to separate cache if any
    if failed_alerts:
        failed_cache_path = os.path.join(ENGINE_CACHE_DIR, "alerts_failed.json")
        existing_failed = _atomic_read_json(failed_cache_path)
        _atomic_write_json(failed_cache_path, existing_failed + failed_alerts)
    
    total_duration = (datetime.now() - start_time).total_seconds() * 1000
    
    logger.info("enrich_and_store_completed",
               raw_count=len(raw_alerts),
               new_after_dedup=len(new_alerts),
               enriched_count=len(summarized),
               relevant_count=len(relevant_summarized),
               normalized_count=len(normalized),
               failed_count=len(failed_alerts),
               db_write_success=db_save_success,
               cache_write_success=cache_write_success,
               total_duration_ms=round(total_duration, 2),
               dedup_duration_ms=round(dedup_duration, 2),
               enrichment_duration_ms=round(enrich_duration, 2))

    return normalized

def enhance_location_confidence(alert: dict) -> dict:
    """
    Use the new location_method and location_confidence fields from RSS processor
    to enhance threat analysis location accuracy. Now uses centralized confidence scoring.
    """
    # Calculate location confidence using centralized function
    location_reliability = compute_confidence(alert, "location")
    
    # Enhance alert with location reliability score
    alert["location_reliability"] = location_reliability
    alert["location_source"] = alert.get("location_method", "none")
    
    # Map confidence to precision categories
    if location_reliability >= 0.8 and alert.get("latitude") and alert.get("longitude"):
        alert["geo_precision"] = "high"
    elif location_reliability >= 0.6:
        alert["geo_precision"] = "medium"
    else:
        alert["geo_precision"] = "low"
    
    return alert

# -------- Atomic Operations and Circuit Breaker Helpers --------

import time
from concurrent.futures import as_completed

# Circuit breaker state
_circuit_breaker = {
    "failure_count": 0,
    "last_failure_time": 0,
    "state": "CLOSED",  # CLOSED, OPEN, HALF_OPEN
    "failure_threshold": 5,
    "recovery_timeout": 60  # seconds
}

def _atomic_read_json(file_path: str) -> list:
    """Atomically read JSON file with proper locking."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)  # Shared lock for reading
            try:
                data = json.load(f)
                if not isinstance(data, list):
                    raise ValueError("Cache file is not a list")
                return data
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except FileNotFoundError:
        return []
    except Exception as e:
        logger.warning("atomic_json_read_failed", file=file_path, error=str(e))
        return []

def _atomic_write_json(file_path: str, data: list) -> bool:
    """Atomically write JSON file with proper locking."""
    try:
        # Write to temporary file first
        temp_path = f"{file_path}.tmp.{threading.current_thread().ident}"
        
        with open(temp_path, "w", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)  # Exclusive lock
            try:
                json.dump(data, f, ensure_ascii=False, indent=2, default=json_default)
                f.flush()
                os.fsync(f.fileno())  # Force write to disk
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        
        # Atomic rename
        os.rename(temp_path, file_path)
        return True
        
    except Exception as e:
        logger.error("atomic_json_write_failed", file=file_path, error=str(e))
        # Clean up temp file
        try:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        except:
            pass
        return False

def _check_circuit_breaker() -> bool:
    """Check if circuit breaker allows operation."""
    global _circuit_breaker
    
    current_time = time.time()
    
    if _circuit_breaker["state"] == "OPEN":
        # Check if we should try to recover
        if current_time - _circuit_breaker["last_failure_time"] > _circuit_breaker["recovery_timeout"]:
            _circuit_breaker["state"] = "HALF_OPEN"
            logger.info("circuit_breaker_half_open", 
                       failure_count=_circuit_breaker["failure_count"])
            return True
        return False
    
    return True

def _record_circuit_success():
    """Record successful operation."""
    global _circuit_breaker
    _circuit_breaker["failure_count"] = 0
    _circuit_breaker["state"] = "CLOSED"

def _record_circuit_failure():
    """Record failed operation."""
    global _circuit_breaker
    _circuit_breaker["failure_count"] += 1
    _circuit_breaker["last_failure_time"] = time.time()
    
    if _circuit_breaker["failure_count"] >= _circuit_breaker["failure_threshold"]:
        _circuit_breaker["state"] = "OPEN"
        logger.error("circuit_breaker_opened", 
                    failure_count=_circuit_breaker["failure_count"])

def _save_with_circuit(alerts: list) -> bool:
    """Save alerts to database with circuit breaker protection."""
    if not _check_circuit_breaker():
        logger.warning("circuit_breaker_blocked_db_save", count=len(alerts))
        raise Exception("Circuit breaker is OPEN - database operations blocked")
    
    try:
        save_alerts_to_db(alerts)
        _record_circuit_success()
        
        # Log success metrics
        metrics.database_operation(
            operation="save_alerts",
            table="alerts", 
            duration_ms=0,  # Duration tracked in save_alerts_to_db
            rows_affected=len(alerts)
        )
        
        return True
        
    except Exception as e:
        _record_circuit_failure()
        logger.error("circuit_breaker_db_save_failed", 
                    count=len(alerts), 
                    error=str(e),
                    circuit_state=_circuit_breaker["state"])
        raise

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
