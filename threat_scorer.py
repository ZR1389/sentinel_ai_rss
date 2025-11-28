# threat_scorer.py — Deterministic risk scoring & signals
# v2025-08-31 (aligned with rss_processor matcher + risk_shared taxonomies)
# Used by Threat Engine (no LLM, no DB writes)

from __future__ import annotations
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta, timezone
import math
import re
try:
    from unidecode import unidecode
except ImportError as e:
    import logging
    logging.getLogger("threat_scorer").warning(f"[UNIDECODE] unidecode library not available, text normalization will be degraded: {e}")
    def unidecode(s: str) -> str:  # type: ignore
        return s

# Import defensive score handling
try:
    from score_type_safety import safe_numeric_score, safe_score_comparison
except ImportError:
    # Fallback if score_type_safety not available
    def safe_numeric_score(value, default=0.0, min_val=0.0, max_val=100.0):
        """Fallback safe score conversion"""
        try:
            if value is None:
                return default
            return max(min_val, min(max_val, float(value)))
        except (ValueError, TypeError):
            return default
    
    def safe_score_comparison(score1, score2, operator='>'):
        """Fallback safe score comparison"""
        try:
            s1, s2 = float(score1 or 0), float(score2 or 0)
            if operator == '>': return s1 > s2
            elif operator == '>=': return s1 >= s2
            elif operator == '<': return s1 < s2
            elif operator == '<=': return s1 <= s2
            elif operator == '==': return abs(s1 - s2) < 0.001
            elif operator == '!=': return abs(s1 - s2) >= 0.001
            return False
        except (ValueError, TypeError):
            return False

# Shared heuristics/taxonomy
from risk_shared import (
    compute_keyword_weight,
    run_sentiment_analysis,
    detect_domains,
    baseline_from_counts,
    ewma_anomaly,
    _has_keyword,  # For whole-word keyword matching
)

# --------------------------- utilities ---------------------------

def _norm(text: str) -> str:
    """
    Normalize text once for all checks:
      - convert to lowercase
      - strip accents (unidecode)
      - collapse whitespace
    Ensures 'IED', 'IÉD', 'ied' all match, etc.
    """
    return re.sub(r"\s+", " ", unidecode(text or "").lower()).strip()

def _parse_dt(obj: Any) -> Optional[datetime]:
    """
    Accepts Python datetime or common ISO strings (with/without Z). Returns timezone-aware UTC.
    """
    if not obj:
        return None
    if isinstance(obj, datetime):
        dt = obj
    elif isinstance(obj, str):
        s = obj.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
        except Exception:
            # best-effort coarse parse
            try:
                dt = datetime.strptime(obj[:19], "%Y-%m-%d %H:%M:%S")
            except Exception:
                return None
    else:
        return None
    # normalize to aware UTC
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def _today_utc() -> datetime:
    return datetime.now(timezone.utc)

def _ratio(a: float, b: float, default: float = 1.0) -> float:
    """Safe ratio calculation with fallback."""
    if b == 0:
        return default
    return a / b

def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x

def _label_from_score(score: float) -> str:
    if score >= 85: return "Critical"
    if score >= 65: return "High"
    if score >= 35: return "Moderate"
    return "Low"

def _bucket_daily_counts(incidents: List[Dict[str, Any]], days: int = 28) -> List[int]:
    """
    Bucket incidents into daily counts over the last N days.
    Returns a list of length 'days' where index 0 is oldest day, index -1 is most recent.
    """
    if not incidents:
        return [0] * days
    
    now = datetime.now(timezone.utc)
    # Create buckets for each day
    buckets = [0] * days
    
    for incident in incidents:
        incident_dt = _parse_dt(incident.get("created_at") or incident.get("timestamp"))
        if not incident_dt:
            continue
            
        # Ensure timezone-aware comparison
        if incident_dt.tzinfo is None:
            incident_dt = incident_dt.replace(tzinfo=timezone.utc)
        
        # Calculate days ago (0 = today, 1 = yesterday, etc.)
        delta = now - incident_dt
        days_ago = int(delta.total_seconds() / 86400)  # 86400 seconds in a day
        
        # Place in appropriate bucket (if within range)
        if 0 <= days_ago < days:
            bucket_idx = days - 1 - days_ago  # reverse index (oldest first)
            buckets[bucket_idx] += 1
    
    return buckets

# --------------------------- severity & context terms ---------------------------

# ---------------------- Import keywords from centralized source ----------------------
try:
    from keywords_loader import SEVERE_TERMS, MOBILITY_TERMS, INFRA_TERMS
except ImportError:
    # Fallback keywords if keywords_loader is not available
    SEVERE_TERMS = [
        "ied","vbied","suicide","suicide bomber","explosion","multiple explosions","mass shooting",
        "kidnap","kidnapping","armed","gunfire","shooting","stabbing","grenade","assassination",
        "curfew","checkpoint","evacuate","emergency","fatal","killed","hostage","car bomb","truck bomb","arson",
        "shelling","mortar","drone strike","airstrike","air strike","artillery","bombing","roadside bomb","improvised explosive",
        "ransomware","breach","data leak","data leakage","data breach","zero-day","zero day","cve-","credential stuffing","ddos","wiper","malware",
        "i e d","v b i e d",
    ]
    
    MOBILITY_TERMS = [
        "airport","border","highway","rail","metro","bridge","port","road closure","detour","traffic suspended","service suspended","runway","airspace","notam","ground stop"
    ]
    
    INFRA_TERMS = [
        "substation","grid","pipeline","telecom","fiber","power outage","blackout","water plant","dam","subsea cable","transformer","refinery","substation fire","transformer fire"
    ]

# --------------------------- scoring core ---------------------------

def _kw_rule_bonus(rule: Optional[str]) -> float:
    """
    Bonus points based on matcher rule:
      - broad+impact(sentence)  → +8
      - broad+impact(window)    → +5
      - keyword/other/None      → +0
    Accepts slight spelling variants ('sent').
    """
    if not rule:
        return 0.0
    r = (rule or "").lower()
    if "broad+impact" in r and ("sentence" in r or "sent" in r):
        return 8.0
    if "broad+impact" in r and "window" in r:
        return 5.0
    return 0.0

def _kw_salience_points(text_norm: str) -> float:
    """
    Map compute_keyword_weight (0..1) → 0..55 points.
    Same shape as older scorer (55% weight).
    """
    kw = compute_keyword_weight(text_norm)
    return 55.0 * _clamp(kw, 0.0, 1.0)

def _trigger_points(triggers: Optional[List[str]]) -> float:
    """
    0..25 points, saturates at 6 triggers.
    """
    t = min(len(triggers or []), 6)
    return (25.0 / 6.0) * float(t)

def _severity_points(text_norm: str) -> Tuple[float, int]:
    """
    Each severe hit → +5 points, cap at 20.
    Return (points, hit_count).
    Uses whole-word matching to avoid false positives (e.g., 'shortage' matching 'short').
    """
    hits = sum(1 for k in SEVERE_TERMS if _has_keyword(text_norm, k))
    pts = min(20.0, 5.0 * float(hits))
    return pts, hits

def _mobinfra_bonus(text_norm: str) -> float:
    """
    Mobility/infrastructure presence → small +3 bonus (kept conservative).
    """
    if any(t in text_norm for t in (MOBILITY_TERMS + INFRA_TERMS)):
        return 3.0
    return 0.0

def _nudge_points(text_norm: str) -> float:
    """
    Contextual bounded nudges identical to earlier behavior.
    """
    bonus = 0.0
    if any(k in text_norm for k in ["suicide bomber","vbied","mass shooting","multiple explosions"]):
        bonus += 10.0
    if "curfew" in text_norm and "checkpoint" in text_norm:
        bonus += 5.0
    if ("airport" in text_norm and ("closure" in text_norm or "suspended" in text_norm or "runway" in text_norm)):
        bonus += 5.0
    if (("cve-" in text_norm) or ("zero-day" in text_norm) or ("zero day" in text_norm)) and (("ransomware" in text_norm) or ("breach" in text_norm)):
        bonus += 5.0
    return bonus

def _score_components(
    text_norm: str,
    triggers: Optional[List[str]],
    kw_match: Optional[Dict[str, Any]] = None
) -> Tuple[float, Dict[str, float]]:
    """
    Deterministic mapping of signals → points. Returns (total_points, breakdown).
    - keyword salience (0..55)
    - triggers (0..25)
    - severity (0..20)
    - kw_rule bonus (+0/+5/+8)
    - mobility/infra bonus (+3)
    - nudges (+ up to 10)
    """
    breakdown: Dict[str, float] = {}

    breakdown["keywords"] = _kw_salience_points(text_norm)
    breakdown["triggers"] = _trigger_points(triggers)
    sev_pts, _ = _severity_points(text_norm)
    breakdown["severity"] = sev_pts
    breakdown["kw_rule_bonus"] = _kw_rule_bonus((kw_match or {}).get("rule"))
    breakdown["mobinfra_bonus"] = _mobinfra_bonus(text_norm)
    breakdown["nudges"] = _nudge_points(text_norm)

    total = sum(breakdown.values())
    # global clamp for safety
    total = _clamp(total, 5.0, 100.0)
    return total, breakdown

# --------------------------- public API ---------------------------

def compute_now_risk(alert_text: str, triggers: Optional[List[str]] = None, location: Optional[str] = None) -> float:
    """
    Backward-compatible fast heuristic risk (0..100).
    NOTE: For full rule-aware scoring (including kw_match), call assess_threat_level.
    """
    text = _norm(alert_text or "")
    score, _ = _score_components(text, triggers, kw_match=None)
    return float(round(score, 1))

def assess_threat_level(
    alert_text: str,
    triggers: Optional[List[str]],
    location: Optional[str],
    alert_uuid: Optional[str] = None,
    plan: Optional[str] = None,
    enrich: bool = True,
    user_email: Optional[str] = None,
    source_alert: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Main scoring function used by the Threat Engine.
    Returns keys consumed by the engine/advisor:
      - label (Low/Moderate/High/Critical)
      - score (0..100)
      - confidence (0..1)
      - reasoning (short string)
      - sentiment (aux)
      - domains (aux)
      - kw_rule (aux, for debugging)
      - score_breakdown (aux dict of point buckets)
    """
    text = _norm(alert_text or "")
    kw_match = (source_alert or {}).get("kw_match") if source_alert else None

    # Points
    score, breakdown = _score_components(text, triggers, kw_match=kw_match)

    # Confidence:
    # base 0.60 + distance-from-50 + keyword bonus + trigger bonus + kw_rule bonus
    kw_weight = compute_keyword_weight(text)              # 0..1
    trig_norm = min(len(triggers or []), 6) / 6.0         # 0..1

    conf = 0.60
    conf += 0.20 * (abs(score - 50.0) / 50.0)
    conf += 0.10 * (1.0 if kw_weight > 0.60 else 0.0)
    conf += 0.05 * (1.0 if trig_norm > 0.50 else 0.0)
    if kw_match and isinstance(kw_match.get("rule"), str):
        r = kw_match["rule"].lower()
        if "broad+impact" in r and ("sentence" in r or "sent" in r):
            conf += 0.05
        elif "broad+impact" in r and "window" in r:
            conf += 0.03
    confidence = round(_clamp(conf, 0.40, 0.95), 2)

    # Sentiment & domains (aux)
    sentiment = run_sentiment_analysis(text)
    domains = detect_domains(text)

    # Slight confidence floor for very high scores
    if score >= 85.0:
        confidence = max(confidence, 0.75)

    label = _label_from_score(score)

    # Reasoning: concise and deterministic
    sev_hits = sum(1 for k in SEVERE_TERMS if _has_keyword(text, k))
    reasoning_bits = [
        f"score={round(score,1)}",
        f"salience={kw_weight:.2f}",
        f"sev_hits={sev_hits}",
        f"triggers={len(triggers or [])}",
        f"sentiment='{sentiment}'"
    ]
    if domains:
        reasoning_bits.append(f"domains={','.join(domains[:4])}")
    if kw_match and kw_match.get("rule"):
        reasoning_bits.append(f"kw_rule={kw_match.get('rule')}")
    if source_alert and source_alert.get("source"):
        reasoning_bits.append(f"source={source_alert.get('source')}")
    reasoning = "; ".join(reasoning_bits)

    # Attach a compact view of kw matches for debugging
    kw_rule = (kw_match or {}).get("rule")
    kw_matches = (kw_match or {}).get("matches") or {}
    # For readability, trim any huge lists
    trimmed_matches = {}
    for k, v in kw_matches.items():
        try:
            if isinstance(v, list) and len(v) > 8:
                trimmed_matches[k] = v[:8] + ["+more"]
            else:
                trimmed_matches[k] = v
        except Exception:
            continue

    return {
        "label": label,
        "threat_label": label,
        "threat_level": label,
        "score": round(float(score), 1),
        "confidence": confidence,
        "reasoning": reasoning,
        "sentiment": sentiment,
        "domains": domains,
        # extras (non-breaking)
        "kw_rule": kw_rule,
        "kw_matches": trimmed_matches,
        "score_breakdown": {k: round(v, 1) for k, v in breakdown.items()},
    }

# --------------------------- trends & stats (unchanged) ---------------------------

def compute_trend_direction(incidents: List[Dict[str, Any]]) -> str:
    """
    Direction from recent 7d vs baseline (previous 21d normalized to 7d).
    """
    if not incidents:
        return "stable"
    counts_28 = _bucket_daily_counts(incidents, days=28)  # oldest..newest
    recent_7 = sum(counts_28[-7:])
    prev_21 = sum(counts_28[:-7])
    baseline_7 = prev_21 / 3.0 if prev_21 else 0.0
    ratio = _ratio(recent_7, baseline_7, default=(1.0 if recent_7 > 0 else 0.0))

    if ratio > 1.25:
        return "increasing"
    if ratio < 0.80:
        return "decreasing"
    return "stable"

def compute_future_risk_probability(incidents: List[Dict[str, Any]]) -> float:
    """
    Probability (0..1) of another incident within next 48h.
    Based on recent 7d vs *previous 49d* baseline ratio (excludes leakage) + EWMA spike flag.
    """
    counts_56 = _bucket_daily_counts(incidents, days=56)
    if not counts_56:
        return 0.25  # conservative default

    recent_7 = sum(counts_56[-7:])       # last week
    prev_49 = sum(counts_56[:-7])        # exclude last week from baseline
    base_avg_7 = (prev_49 / 7.0) if prev_49 else 0.0
    ratio = (recent_7 / base_avg_7) if base_avg_7 > 0 else (1.0 if recent_7 > 0 else 0.0)

    # EWMA anomaly check on last 21 days
    ewma_spike = ewma_anomaly(counts_56[-21:], alpha=0.4, k=2.5)

    # Logistic-ish mapping from ratio + spike → probability
    # Center at 1.0x baseline; scale to keep within 0.2..0.95
    x = (ratio - 1.0) * 1.1
    p = 0.5 * (1.0 + math.tanh(x))  # 0..1
    if ewma_spike:
        p += 0.1
    return round(_clamp(p, 0.20, 0.95), 2)

def stats_average_score(incidents: List[Dict[str, Any]]) -> float:
    """
    Average of 'score' field over incidents (ignoring missing/invalid).
    Uses safe score conversion to handle TEXT score columns.
    """
    vals: List[float] = []
    for inc in incidents or []:
        s = inc.get("score")
        # Use safe score conversion instead of raw float()
        safe_val = safe_numeric_score(s, default=None)
        if safe_val is not None:
            vals.append(safe_val)
    if not vals:
        return 0.0
    return round(sum(vals) / len(vals), 1)

def early_warning_indicators(incidents: List[Dict[str, Any]]) -> List[str]:
    """
    Cheap, useful flags from time clustering and severity.
    Emits subset of: burst_48h, ewma_spike, high_severity_cluster
    """
    out: List[str] = []
    if not incidents:
        return out

    # Time burst (>=3 incidents in 48h)
    now = _today_utc()
    window_48 = now - timedelta(hours=48)
    recent48 = [i for i in incidents if (_parse_dt(i.get("published")) or now) >= window_48]
    if len(recent48) >= 3:
        out.append("burst_48h")

    # EWMA spike on last 14 days
    counts_14 = _bucket_daily_counts(incidents, days=14)
    if ewma_anomaly(counts_14, alpha=0.4, k=2.5):
        out.append("ewma_spike")

    # High severity share over last 14 days (score>75)
    high = 0
    total = 0
    for inc in incidents:
        dt = _parse_dt(inc.get("published"))
        if not dt:
            continue
        if dt >= now - timedelta(days=14):
            total += 1
            # Use safe score comparison to handle TEXT scores from database
            score_value = inc.get("score", 0)
            if safe_score_comparison(score_value, 75.0, '>'):
                high += 1
    if total >= 5 and (high / max(total, 1)) >= 0.4:
        out.append("high_severity_cluster")

    return out
