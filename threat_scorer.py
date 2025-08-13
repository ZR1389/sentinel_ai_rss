# threat_scorer.py — Deterministic risk scoring & signals (Final v2025-08-12)
# Used by Threat Engine (no LLM, no DB writes)

from __future__ import annotations
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta, timezone
import math

# Shared heuristics/taxonomy
from risk_shared import (
    compute_keyword_weight,
    run_sentiment_analysis,
    detect_domains,
    baseline_from_counts,
    ewma_anomaly,
)

# --------------------------- utilities ---------------------------

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

def _bucket_daily_counts(incidents: List[Dict[str, Any]], days: int = 56) -> List[int]:
    """
    Returns a list of length `days`, ordered oldest..newest (each entry = count on that day).
    """
    if days <= 0:
        return []
    end = _today_utc().date()
    start = end - timedelta(days=days - 1)
    buckets = { (start + timedelta(d)): 0 for d in range(days) }
    for inc in incidents or []:
        dt = _parse_dt(inc.get("published"))
        if not dt:
            continue
        d = dt.date()
        if start <= d <= end:
            buckets[d] = buckets.get(d, 0) + 1
    # return in chronological order
    return [buckets[start + timedelta(d)] for d in range(days)]

def _ratio(a: float, b: float, default: float = 1.0) -> float:
    if b <= 0:
        return default
    return a / b

def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x

def _label_from_score(score: float) -> str:
    if score >= 85: return "Critical"
    if score >= 65: return "High"
    if score >= 35: return "Moderate"
    return "Low"

# --------------------------- core API ---------------------------

def compute_now_risk(alert_text: str, triggers: Optional[List[str]] = None, location: Optional[str] = None) -> float:
    """
    Fast heuristic risk (0..100) based on keyword salience, trigger density, and severity terms.
    Deterministic and explainable; tuned for triage (not a medical device).
    """
    text = (alert_text or "")
    kw = compute_keyword_weight(text)              # 0..1
    trig = min(len(triggers or []), 6) / 6.0       # 0..1

    severe_terms = [
        "ied","vbied","suicide","explosion","mass shooting","kidnap","kidnapping","armed","gunfire",
        "curfew","checkpoint","evacuate","emergency","fatal","killed","hostage","ransomware","breach"
    ]
    sev_hits = sum(1 for k in severe_terms if k in text.lower())
    sev = _clamp(sev_hits / 5.0, 0.0, 1.0)

    # Weighted blend → 0..100 (bias slightly high for safety)
    raw = 100.0 * (0.55 * kw + 0.25 * trig + 0.20 * sev)
    # Floor/ceil to avoid flat zeros and make “Low” actionable
    return float(round(_clamp(raw, 5.0, 97.0), 1))

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
      - threat_label (duplicate of label)
      - threat_level (duplicate of label)
    """
    text = alert_text or ""
    score = compute_now_risk(text, triggers, location)

    # Minimal deterministic confidence:
    #   base 0.60 + distance-from-50 + keyword bonus + trigger bonus
    kw = compute_keyword_weight(text)
    trig = min(len(triggers or []), 6) / 6.0
    conf = 0.60 + 0.20 * (abs(score - 50.0) / 50.0) + 0.10 * (1.0 if kw > 0.6 else 0.0) + 0.05 * (1.0 if trig > 0.5 else 0.0)
    confidence = round(_clamp(conf, 0.40, 0.95), 2)

    # Sentiment band for human-readable reasoning
    sentiment = run_sentiment_analysis(text)
    domains = detect_domains(text)

    # Escalation nudges for very specific phrases (bounded)
    if any(k in text.lower() for k in ["suicide bomber","vbied","mass shooting","multiple explosions"]):
        score = min(100.0, score + 10.0)
    if "curfew" in text.lower() and "checkpoint" in text.lower():
        score = min(100.0, score + 5.0)

    label = _label_from_score(score)

    reasoning_bits = []
    reasoning_bits.append(f"salience={kw:.2f}")
    reasoning_bits.append(f"triggers={len(triggers or [])}")
    reasoning_bits.append(f"sentiment='{sentiment}'")
    if domains:
        reasoning_bits.append(f"domains={','.join(domains[:4])}")
    if source_alert and source_alert.get("source"):
        reasoning_bits.append(f"source={source_alert.get('source')}")
    reasoning = "; ".join(reasoning_bits)

    return {
        "label": label,
        "threat_label": label,
        "threat_level": label,
        "score": round(float(score), 1),
        "confidence": confidence,
        "reasoning": reasoning,
    }

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
    Based on recent 7d vs 56d baseline ratio + EWMA spike flag.
    """
    counts_56 = _bucket_daily_counts(incidents, days=56)
    if not counts_56:
        return 0.25  # conservative default

    recent_7 = sum(counts_56[-7:])
    past_56_total = sum(counts_56)  # inclusive of recent_7
    base_avg_7, ratio, _ = baseline_from_counts(recent_7, past_56_total)

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
    """
    vals: List[float] = []
    for inc in incidents or []:
        s = inc.get("score")
        try:
            if s is not None:
                vals.append(float(s))
        except Exception:
            continue
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
            try:
                if float(inc.get("score", 0)) > 75.0:
                    high += 1
            except Exception:
                pass
    if total >= 5 and (high / max(total, 1)) >= 0.4:
        out.append("high_severity_cluster")

    return out
