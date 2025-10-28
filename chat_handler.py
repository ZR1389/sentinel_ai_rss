# chat_handler.py — unmetered advisory orchestrator (client-facing helper) • v2025-08-13
# Notes:
# - Do NOT meter or plan-gate here. /chat route in main.py handles quota after success.
# - This module now includes a *soft* verification guard (defense-in-depth):
#   if user email isn’t verified, we return a structured message with next steps.

from __future__ import annotations
import json
import os
import time
import logging
import uuid
from datetime import datetime, timezone
from hashlib import sha1
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

# DB helpers
from db_utils import (
    fetch_alerts_from_db,
    fetch_past_incidents,
    fetch_user_profile,
)

# Optional single-value fetch for verification fallback
try:
    from db_utils import fetch_one
except Exception:
    fetch_one = None  # best-effort fallback

# Advisor entrypoint (LLM)
from advisor import generate_advice

# Plan/usage are INFO-only here (no gating / no metering)
try:
    from plan_utils import get_plan, get_usage
except Exception:
    get_plan = None
    get_usage = None

from security_log_utils import log_security_event

# Optional city tools (safe fallbacks if missing)
try:
    from city_utils import fuzzy_match_city, normalize_city
except Exception:
    fuzzy_match_city = None
    normalize_city = None

# Optional verification util (preferred)
try:
    from verification_utils import verification_status as _verification_status
except Exception:
    _verification_status = None

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

RAILWAY_ENV = os.getenv("RAILWAY_ENVIRONMENT")
if RAILWAY_ENV:
    log.info(f"Running in Railway environment: {RAILWAY_ENV}")
else:
    log.info("Running outside Railway or RAILWAY_ENVIRONMENT not set.")

load_dotenv()

# ---------------- In-memory cache ----------------
CACHE_TTL = int(os.getenv("CHAT_CACHE_TTL", "3600"))
RESPONSE_CACHE: Dict[str, Any] = {}

def set_cache(key: str, value: Any) -> None:
    RESPONSE_CACHE[key] = (value, time.time())

def get_cache(key: str) -> Optional[Any]:
    entry = RESPONSE_CACHE.get(key)
    if not entry:
        return None
    value, ts = entry
    if time.time() - ts > CACHE_TTL:
        try:
            del RESPONSE_CACHE[key]
        except Exception:
            pass
        return None
    return value

# ---------------- Utils ----------------
def json_default(obj):
    if isinstance(obj, (datetime,)):
        # ISO with 'Z' for UTC
        if obj.tzinfo is None:
            return obj.replace(tzinfo=timezone.utc).isoformat()
        return obj.astimezone(timezone.utc).isoformat()
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

def _ensure_str(val, default: str = "") -> str:
    return default if val is None else str(val)

def _ensure_num(val, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default

def _ensure_label(val, default: str = "Unknown") -> str:
    if not val:
        return default
    s = str(val).strip()
    return s or default

def _ensure_list(val) -> List[Any]:
    if not val:
        return []
    if isinstance(val, list):
        return val
    return list(val) if isinstance(val, (set, tuple)) else [val]

def _iso_date(val) -> str:
    """
    Best-effort normalize date fields to ISO8601 (UTC). Returns '' if unknown.
    Accepts datetime, string, epoch int/float; tries common keys on alert dict.
    """
    if isinstance(val, dict):
        for k in ("published", "date", "timestamp", "pubDate", "published_at"):
            if k in val and val[k]:
                return _iso_date(val[k])
        return ""
    if isinstance(val, datetime):
        if val.tzinfo is None:
            val = val.replace(tzinfo=timezone.utc)
        return val.astimezone(timezone.utc).isoformat()
    if isinstance(val, (int, float)):
        try:
            dt = datetime.fromtimestamp(val, tz=timezone.utc)
            return dt.isoformat()
        except Exception:
            return ""
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return ""
        try:
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        except Exception:
            return s
    return ""

def _normalize_value(val: Optional[str], default: Optional[str] = None) -> Optional[str]:
    if not val or not isinstance(val, str):
        return default
    v = val.strip()
    if not v or v.lower() in ("all", "all regions", "all threats"):
        return default
    return v

def _normalize_region(region: Optional[str], city_list: Optional[List[str]] = None) -> Optional[str]:
    if not region:
        return None
    if fuzzy_match_city and city_list:
        try:
            match = fuzzy_match_city(region, city_list)
            return match if match else region
        except Exception:
            return region
    if normalize_city:
        try:
            return normalize_city(region)
        except Exception:
            return region
    return region

def _session_id(email: str, body: Optional[Dict[str, Any]]) -> str:
    if body and body.get("session_id"):
        return str(body["session_id"])
    if email:
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, email.strip().lower()))
    return str(uuid.uuid4())

def _is_verified(email: str) -> bool:
    """
    Preferred: verification_utils.verification_status
    Fallback: SELECT users.email_verified
    """
    try:
        if _verification_status:
            ok, _ = _verification_status(email)
            return bool(ok)
    except Exception:
        pass
    if fetch_one:
        try:
            row = fetch_one("SELECT email_verified FROM users WHERE email=%s", (email,))
            return bool(row and row[0])
        except Exception:
            return False
    return False

# ---------------- Core ----------------
def handle_user_query(
    message: str | Dict[str, Any],
    email: str,
    region: Optional[str] = None,
    threat_type: Optional[str] = None,   # maps to alerts.category
    city_list: Optional[List[str]] = None,
    body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Entry: assemble context, fetch alerts, call advisor, and return a structured response.
    - NO metering/gating here — /chat endpoint meters AFTER success.
    - Soft verification guard here (defense-in-depth). If not verified, we return an instruction payload.
    - `threat_type` maps to `alerts.category` (Option A schema).
    """
    log.info("handle_user_query: ENTERED | email=%s", email)

    if not email:
        log_security_event(event_type="missing_email", details="handle_user_query called without email")
        raise ValueError("handle_user_query requires a valid authenticated user email.")

    # ---- Soft verification guard (defense-in-depth) ----
    if not _is_verified(email):
        log_security_event(
            event_type="chat_denied_unverified",
            email=email,
            details="Soft guard in chat_handler blocked unverified user",
        )
        return {
            "error": "Email not verified. Please verify your email to use chat.",
            "verify_required": True,
            "actions": {"send_code": "/auth/verify/send", "confirm_code": "/auth/verify/confirm"},
        }

    # Plan/usage are informational only
    plan_name = "FREE"
    if get_plan:
        try:
            p = get_plan(email)
            plan_name = (p or "FREE").upper()
        except Exception as e:
            log.warning("get_plan failed: %s", e)

    usage_info: Dict[str, Any] = {"email": email}
    if get_usage:
        try:
            usage_info.update(get_usage(email) or {})
        except Exception as e:
            log.warning("get_usage failed: %s", e)

    # Parse query text
    query = message.get("query", "") if isinstance(message, dict) else str(message or "")
    query = (query or "").strip()
    log.info("Query content: %s", query)

    # Normalize region/category
    region = _normalize_value(region, None)
    threat_type = _normalize_value(threat_type, None)
    if region and city_list:
        region = _normalize_region(region, city_list)
    log.debug("Filters | region=%r category(threat_type)=%r", region, threat_type)

    # Session
    session_id = _session_id(email, body)

    # Cache key (after filters)
    cache_key = sha1(json.dumps(
        {"query": query, "region": region, "category": threat_type, "session_id": session_id},
        sort_keys=True, default=json_default
    ).encode("utf-8")).hexdigest()
    cached = get_cache(cache_key)
    if cached is not None:
        log.info("handle_user_query: cache HIT")
        log_security_event(event_type="cache_hit", email=email, plan=plan_name, details=f"cache_key={cache_key}")
        return cached

    # ---------------- Fetch alerts ----------------
    try:
        log.info("DB: fetch_alerts_from_db(...)")
        db_alerts: List[Dict[str, Any]] = fetch_alerts_from_db(
            region=region,
            category=threat_type,  # align with Option A schema
            limit=int(os.getenv("CHAT_ALERTS_LIMIT", "20")),
        )
        count = len(db_alerts or [])
        log.info("DB: fetched %d alerts", count)
        log_security_event(event_type="db_alerts_fetched", email=email, plan=plan_name, details=f"{count} alerts")
    except Exception as e:
        log.error("DB fetch failed: %s", e)
        usage_info["fallback_reason"] = "alert_fetch_error"
        log_security_event(event_type="db_alerts_fetch_failed", email=email, plan=plan_name, details=str(e))
        return {
            "reply": f"System error fetching alerts: {e}",
            "plan": plan_name,
            "alerts": [],
            "usage": usage_info,
            "session_id": session_id,
        }

    # ---------------- Historical context ----------------
    historical_alerts: List[Dict[str, Any]] = []
    history_category = None
    if db_alerts:
        cats = {a.get("category") for a in db_alerts if a.get("category")}
        history_category = next(iter(cats)) if cats else None
    try:
        historical_alerts = fetch_past_incidents(
            region=region, category=history_category, days=int(os.getenv("CHAT_HISTORY_DAYS", "90")), limit=100
        )
        log.info("[HIST] %d historical for region=%s category=%s", len(historical_alerts), region, history_category)
    except Exception as e:
        log.warning("[HIST] fetch_past_incidents failed: %s", e)

    # ---------------- User profile ----------------
    user_profile: Dict[str, Any] = {}
    try:
        user_profile = fetch_user_profile(email) or {}
        log.info("[PROFILE] Loaded profile for %s", email)
    except Exception as e:
        log.warning("[PROFILE] fetch_user_profile failed: %s", e)

    # ---------------- Proactive trigger heuristic ----------------
    all_low = all((a.get("score") or 0) < 55 for a in (db_alerts or [])) if db_alerts else False
    alerts_stale = False
    if db_alerts:
        try:
            latest_iso = max((_iso_date(a) for a in db_alerts), default="")
            if latest_iso:
                dt = datetime.fromisoformat(latest_iso.replace("Z", "+00:00"))
                alerts_stale = (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).days >= 7
        except Exception:
            alerts_stale = False

    # ----------- SMARTER NO-DATA / NO ALERTS GUARD -----------
    if not db_alerts:
        log.info("No alerts found for query='%s', region='%s', threat_type='%s'", query, region, threat_type)
        # PATCH: Always call advisor (LLM) for best-effort situational summary even if no alerts in DB
        try:
            advisor_kwargs = {
                "email": email,
                "region": region,
                "threat_type": threat_type,
                "user_profile": user_profile,
                "historical_alerts": historical_alerts,
            }
            advisory_result = generate_advice(query, [], **advisor_kwargs) or {}
            advisory_result["no_alerts_found"] = True
        except Exception as e:
            log.error("Advisor failed in no-alerts fallback: %s", e)
            advisory_result = {"reply": f"System error generating advice: {e}"}
            usage_info["fallback_reason"] = "advisor_error_no_alerts"
            log_security_event(event_type="advice_generation_failed", email=email, plan=plan_name, details=str(e))

        reply_text = advisory_result.get("reply", "No response generated.") if isinstance(advisory_result, dict) else str(advisory_result)
        payload = {
            "reply": reply_text,
            "plan": plan_name,
            "alerts": [],
            "usage": usage_info,
            "session_id": session_id,
            "no_data": True,
            "metadata": advisory_result if isinstance(advisory_result, dict) else {}
        }
        set_cache(cache_key, payload)
        log_security_event(event_type="response_sent", email=email, plan=plan_name, details=f"query={query[:120]}")
        return payload

    # ---------------- Advisor call ----------------
    advisory_result: Dict[str, Any]
    try:
        advisor_kwargs = {
            "email": email,
            "region": region,
            "threat_type": threat_type,
            "user_profile": user_profile,
            "historical_alerts": historical_alerts,
        }
        if db_alerts and (all_low or alerts_stale):
            log.info("[Proactive Mode] All alerts low or stale → proactive advisory")
            advisory_result = generate_advice(query, db_alerts, **advisor_kwargs) or {}
            advisory_result["proactive_triggered"] = True
            usage_info["proactive_triggered"] = True
        else:
            advisory_result = generate_advice(query, db_alerts, **advisor_kwargs) or {}
            advisory_result["proactive_triggered"] = False
    except Exception as e:
        log.error("Advisor failed: %s", e)
        advisory_result = {"reply": f"System error generating advice: {e}"}
        usage_info["fallback_reason"] = "advisor_error"
        log_security_event(event_type="advice_generation_failed", email=email, plan=plan_name, details=str(e))

    # ---------------- Build alert payloads ----------------
    results: List[Dict[str, Any]] = []
    for alert in db_alerts or []:
        results.append({
            "uuid": _ensure_str(alert.get("uuid", "")),
            "title": _ensure_str(alert.get("title", "")),
            "summary": _ensure_str(alert.get("gpt_summary") or alert.get("summary", "")),
            "link": _ensure_str(alert.get("link", "")),
            "source": _ensure_str(alert.get("source", "")),
            "category": _ensure_str(alert.get("category") or alert.get("type") or ""),
            "subcategory": _ensure_str(alert.get("subcategory", "")),
            "threat_level": _ensure_label(alert.get("threat_level", "")),
            "threat_label": _ensure_label(alert.get("threat_label") or alert.get("label") or ""),
            "score": _ensure_num(alert.get("score", 0)),
            "confidence": _ensure_num(alert.get("confidence", 0)),
            "published": _iso_date(alert),
            "city": _ensure_str(alert.get("city", "")),
            "country": _ensure_str(alert.get("country", "")),
            "region": _ensure_str(alert.get("region", "")),
            "reasoning": _ensure_str(alert.get("reasoning", "")),
            "forecast": _ensure_str(alert.get("forecast", "")),
            "historical_context": _ensure_str(alert.get("historical_context", "")),
            "sentiment": _ensure_str(alert.get("sentiment", "")),
            "legal_risk": _ensure_str(alert.get("legal_risk", "")),
            "cyber_ot_risk": _ensure_str(alert.get("cyber_ot_risk", "")),
            "environmental_epidemic_risk": _ensure_str(alert.get("environmental_epidemic_risk", "")),
            # New schema fields
            "domains": _ensure_list(alert.get("domains")),
            "trend_direction": _ensure_str(alert.get("trend_direction", "")),
            "trend_score": _ensure_num(alert.get("trend_score", 0)),
            "trend_score_msg": _ensure_str(alert.get("trend_score_msg", "")),
            "future_risk_probability": _ensure_num(alert.get("future_risk_probability", 0)),
            "anomaly_flag": bool(alert.get("anomaly_flag") or alert.get("is_anomaly") or False),
            "early_warning_indicators": _ensure_list(alert.get("early_warning_indicators")),
            "reports_analyzed": int(alert.get("reports_analyzed") or 0),
            "sources": _ensure_list(alert.get("sources")),
        })

    log.info("Alerts processed: %d", len(results))
    log_security_event(event_type="alerts_processed", email=email, plan=plan_name, details=f"count={len(results)}")

    # Optional telemetry
    try:
        label_counts: Dict[str, int] = {}
        for a in results:
            lab = a.get("threat_label") or a.get("threat_level") or "Unknown"
            label_counts[lab] = label_counts.get(lab, 0) + 1
        log.info("[METRICS] label_counts=%s", label_counts)
        log_security_event(event_type="alerts_label_count", email=email, plan=plan_name, details=str(label_counts))
    except Exception:
        pass

    # ---------------- Return & cache ----------------
    # Extract reply string from advisory_result (which is a dict)
    reply_text = advisory_result.get("reply", "No response generated.") if isinstance(advisory_result, dict) else str(advisory_result)
    
    payload = {
        "reply": reply_text,
        "plan": plan_name,
        "alerts": results,
        "usage": usage_info,
        "session_id": session_id,
        "metadata": advisory_result if isinstance(advisory_result, dict) else {}
    }
    set_cache(cache_key, payload)
    log_security_event(event_type="response_sent", email=email, plan=plan_name, details=f"query={query[:120]}")
    return payload