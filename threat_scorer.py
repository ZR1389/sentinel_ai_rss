import json
import os
import re
import threading
from functools import lru_cache
import logging
from datetime import datetime, timedelta
import uuid
from risk_shared import (
    compute_keyword_weight,
    run_sentiment_analysis,
    run_forecast,
    run_legal_risk,
    run_cyber_ot_risk,
    run_environmental_epidemic_risk,
    enrich_log_db,
    extract_threat_category,
    extract_threat_subcategory,
)
from prompts import (
    THREAT_SCORER_SYSTEM_PROMPT,
)
from xai_client import grok_chat
from openai import OpenAI
from db_utils import (
    fetch_past_incidents,
    link_similar_alerts,
    assign_alert_cluster,
    alert_frequency,
)

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

CANONICAL_LABELS = ["Critical", "High", "Medium", "Moderate", "Low", "Unrated"]

def normalize_label(label):
    if not label:
        return "Unrated"
    canonical = label.title().strip()
    if canonical not in CANONICAL_LABELS:
        if canonical.lower() in ("severe", "severely", "emergency"):
            return "Critical"
        if canonical.lower() in ("elevated",):
            return "High"
        return "Unrated"
    return canonical

MEDIUM_KEYWORDS = ["protest", "civil unrest", "looting", "roadblock", "arson", "sabotage"]
CRITICAL_KEYWORDS = ["active shooter", "explosion", "suicide bombing", "mass killing"]
HIGH_KEYWORDS = ["armed robbery", "kidnapping", "hostage", "carjacking"]

def get_safe_prompt(alert_text, triggers, location):
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

# --- Cache for correlated alerts/incidents ---
CORRELATED_ALERT_CACHE = {}
INCIDENT_CLUSTER_CACHE = {}

def cache_correlated_alert(alert, region=None, category=None, cluster_id=None):
    key = alert.get("uuid") or alert.get("series_id") or alert.get("incident_series")
    if not key:
        key = str(hash(alert.get("title", "") + alert.get("summary", "")))
    cluster = cluster_id or alert.get("series_id") or alert.get("incident_series")
    region = region or alert.get("region") or alert.get("city") or alert.get("country")
    category = category or alert.get("category") or alert.get("threat_label")
    CORRELATED_ALERT_CACHE.setdefault(region, {})
    CORRELATED_ALERT_CACHE[region].setdefault(category, [])
    CORRELATED_ALERT_CACHE[region][category].append(alert)
    if cluster:
        INCIDENT_CLUSTER_CACHE.setdefault(cluster, [])
        INCIDENT_CLUSTER_CACHE[cluster].append(alert)

def get_correlated_alerts(region, category, window_days=30):
    result = []
    region_alerts = CORRELATED_ALERT_CACHE.get(region, {})
    cat_alerts = region_alerts.get(category, [])
    if not cat_alerts:
        return []
    cutoff = None
    try:
        cutoff = __import__('datetime').datetime.utcnow() - __import__('datetime').timedelta(days=window_days)
    except Exception:
        cutoff = None
    for a in cat_alerts:
        ts = a.get("published") or a.get("timestamp")
        try:
            dt = __import__('datetime').datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            continue
        if cutoff and dt < cutoff:
            continue
        result.append(a)
    return result

def compute_trend_metrics(incidents):
    trend_direction = compute_trend_direction(incidents)
    future_risk_probability = compute_future_risk_probability(incidents)
    now_risk = compute_now_risk(incidents)
    ewi = early_warning_indicators(incidents)
    incident_density = len(incidents)
    return {
        "current_risk_score": now_risk.get("now_score"),
        "current_risk_label": now_risk.get("now_label"),
        "future_risk_probability": future_risk_probability,
        "trend_direction": trend_direction,
        "early_warning_indicators": ewi,
        "incident_density": incident_density,
    }

def early_warning_indicators(incidents):
    indicators = set()
    scores = [inc.get("score", 0) for inc in incidents if isinstance(inc.get("score", 0), (int, float))]
    if len(scores) < 3:
        return []
    for inc in incidents:
        if inc.get("score", 0) > 70 and "matched_keywords" in inc:
            indicators.update(inc["matched_keywords"])
    return list(indicators)

# --- Incident Clustering ---
def normalize_title(title):
    """Simple normalization for matching titles (lowercase, strip punctuation)."""
    import re
    title = title.lower()
    title = re.sub(r'[^a-z0-9 ]', '', title)
    return title.strip()

def cluster_alert(alert, window_hours=72):
    """
    Assigns a cluster_id to the alert if there are similar alerts in the window.
    Similarity: same region, same type, normalized title match, within window_hours.
    """
    region = alert.get("region")
    type_ = alert.get("type")
    title = alert.get("title", "")
    published = alert.get("published")
    if not (region and type_ and title and published):
        return str(uuid.uuid4())  # Always assign a cluster_id

    norm_title = normalize_title(title)
    window_start = published - timedelta(hours=window_hours)
    window_end = published + timedelta(hours=window_hours)

    from db_utils import fetch_alerts_from_db  # Local import to avoid circular
    candidates = fetch_alerts_from_db(
        region=region,
        threat_label=type_,
        start_time=window_start,
        end_time=window_end,
        limit=50
    )
    for cand in candidates:
        cand_title = cand.get("title", "")
        if normalize_title(cand_title) == norm_title:
            # Found a matching cluster
            return cand.get("incident_cluster_id") or assign_alert_cluster(region, type_, cand_title, cand.get("published"))
    # No matching cluster found, assign new
    return str(uuid.uuid4())

def enrich_and_cluster_alerts(alerts):
    """
    Assign cluster IDs to alerts and return enriched alerts.
    """
    enriched_alerts = []
    for alert in alerts:
        cluster_id = cluster_alert(alert)
        alert["incident_cluster_id"] = cluster_id
        enriched_alerts.append(alert)
    return enriched_alerts

# --- Data-Based Forecasting ---
def forecast_risk(region, category, hours_recent=48, days_baseline=7):
    """
    Forecasts risk based on recent incident density vs. baseline average.
    Returns dict with stats, summary, and escalation likelihood.
    """
    recent_incidents = fetch_past_incidents(region=region, category=category, days=2, limit=100)
    baseline_incidents = fetch_past_incidents(region=region, category=category, days=days_baseline, limit=200)

    recent_count = len(recent_incidents)
    baseline_count = len(baseline_incidents)
    baseline_avg_per_48h = baseline_count / (days_baseline / 2) if days_baseline >= 2 else baseline_count

    ratio = recent_count / (baseline_avg_per_48h + 1e-6)
    if ratio > 2.5:
        trend = "rising"
        escalation_likelihood = "High"
        arrow = "↑"
    elif ratio < 0.5:
        trend = "falling"
        escalation_likelihood = "Low"
        arrow = "↓"
    else:
        trend = "stable"
        escalation_likelihood = "Moderate"
        arrow = "→"

    category_display = category if category else "events"
    summary = f"{arrow} {recent_count} {category_display} in past {hours_recent}h, "
    summary += f"{ratio:.1f}x the average for this area. "
    summary += f"Based on past incidents, escalation likelihood: {escalation_likelihood}."

    example_titles = [i.get("title") for i in recent_incidents[:2] if i.get("title")]
    if example_titles:
        summary += " Recent examples: " + "; ".join(example_titles)

    return {
        "region": region,
        "category": category,
        "recent_count": recent_count,
        "baseline_count": baseline_count,
        "ratio_to_avg": ratio,
        "trend": trend,
        "escalation_likelihood": escalation_likelihood,
        "summary": summary
    }

# --- Forecasting Engine: Alert Frequency and Prompt Helper ---
def get_alert_frequency(region, threat_type, hours=48):
    """
    Returns the number of alerts in a region/threat_type in the last N hours.
    """
    return alert_frequency(region, threat_type, hours)

def build_forecasting_prompt(region, threat_type):
    """
    Returns prompt for GPT forecasting the next risk in region/threat_type.
    """
    freq = get_alert_frequency(region, threat_type, hours=48)
    prompt = (
        f"Based on {freq} recent alerts in {region} for threat type '{threat_type}', "
        "predict the next likely risk or incident in the next 48 hours. "
        "Give reasoning based on alert frequency, trends, and recent escalation signals."
    )
    return prompt

# --- Threat Level Assessment ---
def assess_threat_level(alert_text, triggers=None, location=None, alert_uuid=None, plan="FREE", enrich=True, user_email=None, source_alert=None, historical_incidents=None, correlated_alerts=None):
    triggers = sorted(set(triggers or []))
    alert_text_lower = alert_text.lower()
    kw_score, kw_matches = compute_keyword_weight(alert_text, return_detail=True)
    input_excerpt = alert_text[:200]

    OUTPUT_FIELDS = [
        "label", "threat_label", "score", "confidence", "reasoning", "model_used",
        "keyword_weight", "matched_keywords", "input_excerpt", "location",
        "sentiment", "forecast", "legal_risk", "cyber_ot_risk", "environmental_epidemic_risk",
        "category", "category_confidence", "subcategory",
        "current_risk_score", "future_risk_probability", "trend_direction", "early_warning_indicators",
        "incident_density", "forecast_summary", "forecast_trend", "forecast_escalation_likelihood", "forecast_ratio_to_avg", "forecast_recent_count", "forecast_baseline_count"
    ]

    # --- LLM-based Threat Type and Subcategory Extraction (always run) ---
    try:
        category, category_confidence = extract_threat_category(alert_text)
    except Exception as e:
        log.error(f"[ThreatScorer][CategoryExtractionError] {e}")
        category, category_confidence = "Other", 0.5

    try:
        subcategory = extract_threat_subcategory(alert_text, category)
    except Exception as e:
        log.error(f"[ThreatScorer][SubcategoryExtractionError] {e}")
        subcategory = "Unspecified"

    # --- Historical metrics ---
    if historical_incidents is not None and isinstance(historical_incidents, list) and historical_incidents:
        trend_metrics = compute_trend_metrics(historical_incidents)
    else:
        trend_metrics = {
            "current_risk_score": None,
            "future_risk_probability": None,
            "trend_direction": None,
            "early_warning_indicators": [],
            "incident_density": 0
        }

    # --- Correlated alerts cache (for evidence-based forecasting) ---
    incident_density = trend_metrics.get("incident_density", 0)
    if correlated_alerts is not None and isinstance(correlated_alerts, list):
        incident_density += len(correlated_alerts)
        trend_metrics["incident_density"] = incident_density

    # --- Influence forecast output: if incident_density high, raise probability/score ---
    if incident_density >= 8 and trend_metrics.get("future_risk_probability", 0.5) < 0.8:
        trend_metrics["future_risk_probability"] = min(1.0, trend_metrics.get("future_risk_probability", 0.5) + 0.15)
        trend_metrics["score_boost_reason"] = "Dense cluster of similar incidents detected in last 30 days."
    elif incident_density == 0:
        trend_metrics["future_risk_probability"] = max(0.2, trend_metrics.get("future_risk_probability", 0.5) - 0.1)

    # --- Attach forecast summary to threat output ---
    forecast_stats = forecast_risk(location, category)
    trend_metrics["forecast_summary"] = forecast_stats.get("summary")
    trend_metrics["forecast_trend"] = forecast_stats.get("trend")
    trend_metrics["forecast_escalation_likelihood"] = forecast_stats.get("escalation_likelihood")
    trend_metrics["forecast_ratio_to_avg"] = forecast_stats.get("ratio_to_avg")
    trend_metrics["forecast_recent_count"] = forecast_stats.get("recent_count")
    trend_metrics["forecast_baseline_count"] = forecast_stats.get("baseline_count")

    # --- Rules: CRITICAL
    for kw in CRITICAL_KEYWORDS:
        if re.search(rf'\b{re.escape(kw)}\b', alert_text_lower):
            result = {
                "label": normalize_label("Critical"),
                "threat_label": normalize_label("Critical"),
                "score": 100,
                "confidence": 1.0,
                "reasoning": f"Keyword '{kw}' matched.",
                "model_used": "rules",
                "keyword_weight": kw_score,
                "matched_keywords": kw_matches,
                "input_excerpt": input_excerpt,
                "location": location,
                "source_alert": source_alert,
                "category": category,
                "category_confidence": category_confidence,
                "subcategory": subcategory,
                **trend_metrics
            }
            if enrich:
                result["sentiment"] = run_sentiment_analysis(alert_text)
                result["forecast"] = run_forecast(location, alert_text)
                result["legal_risk"] = run_legal_risk(alert_text, location)
                result["cyber_ot_risk"] = run_cyber_ot_risk(alert_text, location)
                result["environmental_epidemic_risk"] = run_environmental_epidemic_risk(alert_text, location)
            enrich_log_db(result, enrichment_type="critical_rule", user_email=user_email)
            log.info(f"[ThreatScorer] Critical keyword matched: '{kw}' in '{input_excerpt}'")
            for field in OUTPUT_FIELDS:
                if field not in result:
                    result[field] = None
            return result

    # --- Rules: HIGH
    for kw in HIGH_KEYWORDS:
        if re.search(rf'\b{re.escape(kw)}\b', alert_text_lower):
            result = {
                "label": normalize_label("High"),
                "threat_label": normalize_label("High"),
                "score": 85,
                "confidence": 0.95,
                "reasoning": f"Keyword '{kw}' matched.",
                "model_used": "rules",
                "keyword_weight": kw_score,
                "matched_keywords": kw_matches,
                "input_excerpt": input_excerpt,
                "location": location,
                "source_alert": source_alert,
                "category": category,
                "category_confidence": category_confidence,
                "subcategory": subcategory,
                **trend_metrics
            }
            if enrich:
                result["sentiment"] = run_sentiment_analysis(alert_text)
                result["forecast"] = run_forecast(location, alert_text)
                result["legal_risk"] = run_legal_risk(alert_text, location)
                result["cyber_ot_risk"] = run_cyber_ot_risk(alert_text, location)
                result["environmental_epidemic_risk"] = run_environmental_epidemic_risk(alert_text, location)
            enrich_log_db(result, enrichment_type="high_rule", user_email=user_email)
            log.info(f"[ThreatScorer] High keyword matched: '{kw}' in '{input_excerpt}'")
            for field in OUTPUT_FIELDS:
                if field not in result:
                    result[field] = None
            return result

    # --- Rules: MEDIUM
    for kw in MEDIUM_KEYWORDS:
        if re.search(rf'\b{re.escape(kw)}\b', alert_text_lower):
            result = {
                "label": normalize_label("Medium"),
                "threat_label": normalize_label("Medium"),
                "score": 70,
                "confidence": 0.85,
                "reasoning": f"Keyword '{kw}' matched.",
                "model_used": "rules",
                "keyword_weight": kw_score,
                "matched_keywords": kw_matches,
                "input_excerpt": input_excerpt,
                "location": location,
                "source_alert": source_alert,
                "category": category,
                "category_confidence": category_confidence,
                "subcategory": subcategory,
                **trend_metrics
            }
            if enrich:
                result["sentiment"] = run_sentiment_analysis(alert_text)
                result["forecast"] = run_forecast(location, alert_text)
                result["legal_risk"] = run_legal_risk(alert_text, location)
                result["cyber_ot_risk"] = run_cyber_ot_risk(alert_text, location)
                result["environmental_epidemic_risk"] = run_environmental_epidemic_risk(alert_text, location)
            enrich_log_db(result, enrichment_type="medium_rule", user_email=user_email)
            log.info(f"[ThreatScorer] Medium keyword matched: '{kw}' in '{input_excerpt}'")
            for field in OUTPUT_FIELDS:
                if field not in result:
                    result[field] = None
            return result

    # --- LLM scoring fallback ---
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
                    "label": normalize_label(data.get("label", data.get("threat_label", "Unrated"))),
                    "threat_label": normalize_label(data.get("label", data.get("threat_label", "Unrated"))),
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
                    "category": category,
                    "category_confidence": category_confidence,
                    "subcategory": subcategory,
                    **trend_metrics
                }
                if enrich:
                    output["sentiment"] = run_sentiment_analysis(alert_text)
                    output["forecast"] = run_forecast(location, alert_text)
                    output["legal_risk"] = run_legal_risk(alert_text, location)
                    output["cyber_ot_risk"] = run_cyber_ot_risk(alert_text, location)
                    output["environmental_epidemic_risk"] = run_environmental_epidemic_risk(alert_text, location)
                enrich_log_db(output, enrichment_type="llm_grok", user_email=user_email)
                log.info("[ThreatScorer][Grok] LLM scoring completed.")
                for field in OUTPUT_FIELDS:
                    if field not in output:
                        output[field] = None
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
                    "label": normalize_label(data.get("label", data.get("threat_label", "Unrated"))),
                    "threat_label": normalize_label(data.get("label", data.get("threat_label", "Unrated"))),
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
                    "category": category,
                    "category_confidence": category_confidence,
                    "subcategory": subcategory,
                    **trend_metrics
                }
                if enrich:
                    output["sentiment"] = run_sentiment_analysis(alert_text)
                    output["forecast"] = run_forecast(location, alert_text)
                    output["legal_risk"] = run_legal_risk(alert_text, location)
                    output["cyber_ot_risk"] = run_cyber_ot_risk(alert_text, location)
                    output["environmental_epidemic_risk"] = run_environmental_epidemic_risk(alert_text, location)
                enrich_log_db(output, enrichment_type="llm_openai", user_email=user_email)
                log.info("[ThreatScorer][OpenAI] LLM scoring completed.")
                for field in OUTPUT_FIELDS:
                    if field not in output:
                        output[field] = None
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
            "label": normalize_label("Moderate"),
            "threat_label": normalize_label("Moderate"),
            "score": 60 + kw_score,
            "confidence": 0.7,
            "reasoning": "Timed out or no critical/high/medium keywords, rules fallback.",
            "model_used": "timeout",
            "keyword_weight": kw_score,
            "matched_keywords": kw_matches,
            "input_excerpt": input_excerpt,
            "location": location,
            "source_alert": source_alert,
            "category": category,
            "category_confidence": category_confidence,
            "subcategory": subcategory,
            **trend_metrics
        }
        if enrich:
            base["sentiment"] = run_sentiment_analysis(alert_text)
            base["forecast"] = run_forecast(location, alert_text)
            base["legal_risk"] = run_legal_risk(alert_text, location)
            base["cyber_ot_risk"] = run_cyber_ot_risk(alert_text, location)
            base["environmental_epidemic_risk"] = run_environmental_epidemic_risk(alert_text, location)
        enrich_log_db(base, enrichment_type="timeout", user_email=user_email)
        log.warning("[ThreatScorer] LLM scoring timed out. Using rules fallback.")
        for field in OUTPUT_FIELDS:
            if field not in base:
                base[field] = None
        return base
    if result[0]:
        for field in OUTPUT_FIELDS:
            if field not in result[0]:
                result[0][field] = None
        return result[0]

    base = {
        "label": normalize_label("Moderate"),
        "threat_label": normalize_label("Moderate"),
        "score": 60 + kw_score,
        "confidence": 0.7,
        "reasoning": "No critical, high, or medium keywords, rules fallback.",
        "model_used": "rules",
        "keyword_weight": kw_score,
        "matched_keywords": kw_matches,
        "input_excerpt": input_excerpt,
        "location": location,
        "source_alert": source_alert,
        "category": category,
        "category_confidence": category_confidence,
        "subcategory": subcategory,
        **trend_metrics
    }
    if enrich:
        base["sentiment"] = run_sentiment_analysis(alert_text)
        base["forecast"] = run_forecast(location, alert_text)
        base["legal_risk"] = run_legal_risk(alert_text, location)
        base["cyber_ot_risk"] = run_cyber_ot_risk(alert_text, location)
        base["environmental_epidemic_risk"] = run_environmental_epidemic_risk(alert_text, location)
    enrich_log_db(base, enrichment_type="fallback", user_email=user_email)
    log.info("[ThreatScorer] No LLM or keyword match. Using rules fallback.")
    for field in OUTPUT_FIELDS:
        if field not in base:
            base[field] = None
    return base

# === Analytics/Statistics Helpers ===

def stats_count_by_label(alerts):
    from collections import Counter
    return dict(Counter([a.get("label", "Unknown") for a in alerts]))

def stats_count_by_category(alerts):
    from collections import Counter
    return dict(Counter([a.get("category", "Other") for a in alerts]))

def stats_average_score(alerts):
    scores = [a.get("score", 0) for a in alerts if isinstance(a.get("score"), (int, float))]
    return sum(scores) / len(scores) if scores else 0

def stats_top_keywords(alerts, top_n=10):
    from collections import Counter
    keywords = []
    for a in alerts:
        keywords.extend(a.get("matched_keywords", []))
    return Counter(keywords).most_common(top_n)

def compute_trend_direction(incidents):
    if len(incidents) < 3:
        return "unknown"
    scores = [inc.get("score", 0) for inc in incidents if isinstance(inc.get("score", 0), (int, float))]
    if len(scores) < 3:
        return "unknown"
    mid = len(scores) // 2
    before = scores[mid:]
    after = scores[:mid]
    if not after or not before:
        return "unknown"
    before_avg = sum(before) / len(before)
    after_avg = sum(after) / len(after)
    if after_avg > before_avg + 7:
        return "deteriorating"
    elif after_avg < before_avg - 7:
        return "improving"
    else:
        return "stable"

def compute_future_risk_probability(incidents, window=3):
    if len(incidents) < window + 1:
        return 0.5
    sorted_inc = sorted(incidents, key=lambda x: x.get("timestamp", ""), reverse=True)
    scores = [inc.get("score", 0) for inc in sorted_inc if isinstance(inc.get("score", 0), (int, float))]
    if len(scores) < window * 2:
        return 0.5
    recent = scores[:window]
    previous = scores[window:window*2]
    if not previous or not recent:
        return 0.5
    diff = (sum(recent)/len(recent)) - (sum(previous)/len(previous))
    if diff > 10:
        return 0.9
    if diff > 5:
        return 0.7
    if diff < -10:
        return 0.1
    if diff < -5:
        return 0.3
    return 0.5

def compute_now_risk(incidents):
    if not incidents:
        return {"now_score": None, "now_label": None}
    most_recent = incidents[0]
    return {
        "now_score": most_recent.get("score"),
        "now_label": most_recent.get("label")
    }

def enrich_alert_with_links(alert):
    similar_uuids = link_similar_alerts(alert.get('uuid'))
    alert['correlated_alerts'] = similar_uuids
    return alert