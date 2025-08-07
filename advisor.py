import os
import random
import re
import time
import json
import psycopg2
from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime, timedelta

from risk_shared import (
    compute_keyword_weight,
    enrich_log,
    run_sentiment_analysis,
    run_forecast,
    run_legal_risk,
    run_cyber_ot_risk,
    run_environmental_epidemic_risk,
    FALLBACK_ROUTES
)

from plan_utils import (
    get_plan,
    get_plan_feature,
    get_plan_limits,
    require_plan_feature,
    check_user_message_quota,
    increment_user_message_usage,
    fetch_user_preferences,
)
from xai_client import grok_chat
from prompts import (
    ADVISOR_STRUCTURED_SYSTEM_PROMPT,
    ADVISOR_STRUCTURED_USER_PROMPT,
    PROACTIVE_FORECAST_PROMPT,
    HISTORICAL_COMPARISON_PROMPT,
    SENTIMENT_ANALYSIS_PROMPT,
    LEGAL_REGULATORY_RISK_PROMPT,
    ACCESSIBILITY_INCLUSION_PROMPT,
    PROFESSION_AWARE_PROMPT,
    LOCALIZATION_TRANSLATION_PROMPT,
    IMPROVE_FROM_FEEDBACK_PROMPT,
    ESCALATION_WATCH_WINDOW_PROMPT,
    ANOMALY_ALERT_PROMPT,
    ACTION_ALTERNATIVES_PROMPT,
)
from db_utils import fetch_past_incidents, fetch_user_profile
from threat_scorer import compute_trend_direction, compute_future_risk_probability

import logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

RAILWAY_ENV = os.getenv("RAILWAY_ENVIRONMENT")
if RAILWAY_ENV:
    logger.info(f"Running in Railway environment: {RAILWAY_ENV}")
else:
    logger.info("Running outside Railway or RAILWAY_ENVIRONMENT not set.")

load_dotenv()
if not os.getenv("OPENAI_API_KEY"):
    logger.warning("OPENAI_API_KEY not set.")
if not os.getenv("DATABASE_URL"):
    logger.warning("DATABASE_URL not set.")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=15)
DATABASE_URL = os.getenv("DATABASE_URL")

ZIKA_QUOTES = [
    "🧠 Analyst Insight: The true danger often lies in escalation and unpredictability. Overconfidence in 'low risk' areas has led to many avoidable emergencies.",
    "🧠 Analyst Insight: Real security is built on anticipation, not reaction. Always think one step ahead.",
    "🧠 Analyst Insight: Trust your instincts, but verify. Situational awareness is your best defense.",
    "🧠 Analyst Insight: Many emergencies start as minor incidents. Early, calm action prevents escalation.",
    "🧠 Analyst Insight: Complacency is the enemy of safety. Maintain routine checks, even in familiar places.",
    "🧠 Analyst Insight: Local context matters—what feels safe at noon can change after dark.",
    "🧠 Analyst Insight: Official sources are a starting point, but street-level intel can save lives.",
    "🧠 Analyst Insight: If you feel something is off, act early. Regret is a poor substitute for readiness.",
    "🧠 Analyst Insight: Most risks are predictable if you know what to look for. Pattern recognition is your ally.",
    "🧠 Analyst Insight: When in doubt, err on the side of caution. Safety first, always.",
]

def json_default(obj):
    if isinstance(obj, (datetime,)):
        return obj.isoformat()
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

def format_cta(plan):
    links = {
        "FREE": "🚨 <a href='https://buy.stripe.com/5kQ28r6Q6gck9l04dW8so07' target='_blank'>Upgrade to Pro for detailed travel intelligence and regional alerts.</a>",
        "PRO": "🔭 <a href='https://buy.stripe.com/7sY5kD4HY1hq9l0fWE8so06' target='_blank'>Upgrade to Enterprise for unlimited access, custom features, and priority support.</a>",
        "ENTERPRISE": "🧠 <a href='mailto:zika@zikarisk.com?subject=Enterprise+Briefing' target='_blank'>Your Enterprise plan includes direct access to Zika Risk experts. Request your custom briefing now.</a>"
    }
    return links.get(plan.upper(), "")

def load_risk_profiles():
    try:
        with open("risk_profiles.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def get_static_profile(region, risk_profiles):
    if not region:
        return None
    region_key = next(
        (k for k in risk_profiles if k.lower() == region.strip().lower()), None
    )
    if region_key:
        entry = risk_profiles.get(region_key)
        if isinstance(entry, dict):
            return entry.get("en") or next(iter(entry.values()), None)
        return entry
    return None

def extract_triggers(alerts):
    triggers_all = set()
    for alert in alerts:
        for field in ['title', 'summary']:
            text = alert.get(field, "")
            _, matches = compute_keyword_weight(text, return_detail=True)
            triggers_all.update(matches)
    return list(triggers_all)

def summarize_sources(alerts):
    sources = []
    for alert in alerts:
        src = alert.get("source_name") or alert.get("source")
        link = alert.get("link")
        if src and link:
            sources.append({"title": src, "link": link})
        elif src:
            sources.append({"title": src, "link": ""})
    seen = set()
    unique_sources = []
    for s in sources:
        if s['title'] not in seen:
            unique_sources.append(s)
            seen.add(s['title'])
    return unique_sources

def summarize_categories(alerts):
    categories = set()
    subcategories = set()
    for alert in alerts:
        cat = alert.get("category")
        subcat = alert.get("subcategory")
        if cat: categories.add(cat)
        if subcat: subcategories.add(subcat)
    return list(categories), list(subcategories)

def get_risk_level_from_profile(profile):
    if not profile or not isinstance(profile, str):
        return "Moderate"
    match = re.search(r"(Low|Moderate|High|Severe)", profile, re.IGNORECASE)
    if match:
        return match.group(1).capitalize()
    return profile.strip().split()[0].capitalize() if profile.strip() else "Moderate"

def save_advisory_log_json(email, region, query, result, risk_level, plan):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    log_entry = {
        "timestamp": timestamp,
        "email": email,
        "region": region,
        "query": query,
        "result": result,
        "risk_level": risk_level,
        "plan": plan
    }
    os.makedirs("logs", exist_ok=True)
    log_path = "logs/advisory_log.json"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False, default=json_default) + "\n")
    enrich_log(
        log_entry,
        region=region,
        city=None,
        source="advisor",
        user_email=email
    )

def log_advisory_usage(email, region, plan, action_type, status, message_excerpt=None):
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO advisory_usage (email, region, plan, action_type, status, message_excerpt)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            email,
            region,
            plan,
            action_type,
            status,
            message_excerpt[:120] if message_excerpt else None
        ))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"[Advisory usage logging error] {e}")

def summarize_incidents_for_prompt(incidents, max_len=700):
    result = []
    for inc in incidents:
        s = f"[{inc.get('timestamp','')}] {inc.get('title','')} ({inc.get('label','')}/{inc.get('score','')}) - {inc.get('summary','')}"
        result.append(s)
    joined = "\n".join(result)
    if len(joined) > max_len:
        return joined[:max_len] + "\n[Truncated]"
    return joined

def parse_watch_window(text):
    match = re.search(r"(Reassess in \d+\s*(?:hours?|days?))", text, re.IGNORECASE)
    if match:
        return match.group(1)
    match = re.search(r"(Check again in \d+\s*(?:hours?|days?))", text, re.IGNORECASE)
    if match:
        return match.group(1)
    return None

def parse_alternate_strategies(text):
    alt_section = None
    alt_regex = re.compile(
        r"(?:^|\n)(Alternate Strategies|Plan ?[BC]:?)(.*?)(?:\n[#\-*=~]{3,}|$|\n\n|\n1\.|\nALERT|\n[A-Z][a-z ]+:)", 
        re.IGNORECASE | re.DOTALL
    )
    matches = alt_regex.findall(text)
    if matches:
        alt_section = max((m[1] for m in matches), key=len)
        return alt_section.strip()
    return None

def run_forecast(region, input_data, user_message):
    return run_forecast(region, input_data, user_message)

def run_sentiment_analysis(incident):
    return run_sentiment_analysis(incident)

def run_legal_regulatory_risk(incident, region):
    return run_legal_risk(incident, region)

def run_cyber_ot_risk(incident, region):
    return run_cyber_ot_risk(incident, region)

def run_environmental_epidemic_risk(incident, region):
    return run_environmental_epidemic_risk(incident, region)

def run_historical_comparison(incident, region):
    prompt = HISTORICAL_COMPARISON_PROMPT.format(incident=incident, region=region)
    messages = [{"role": "system", "content": ADVISOR_STRUCTURED_SYSTEM_PROMPT}, {"role": "user", "content": prompt}]
    try:
        return grok_chat(messages, temperature=0.2, max_tokens=100)
    except Exception as e:
        logger.error(f"[run_historical_comparison error] {e}")
        return "No historical comparison available."

def run_accessibility_inclusion(region, threats, user_message):
    prompt = ACCESSIBILITY_INCLUSION_PROMPT.format(region=region, threats=threats, user_message=user_message)
    messages = [{"role": "system", "content": ADVISOR_STRUCTURED_SYSTEM_PROMPT}, {"role": "user", "content": prompt}]
    try:
        return grok_chat(messages, temperature=0.2, max_tokens=120)
    except Exception as e:
        logger.error(f"[run_accessibility_inclusion error] {e}")
        return "No accessibility/inclusion info available."

def run_profession_aware(profession, region, threats, user_message):
    prompt = PROFESSION_AWARE_PROMPT.format(profession=profession, region=region, threats=threats, user_message=user_message)
    messages = [{"role": "system", "content": ADVISOR_STRUCTURED_SYSTEM_PROMPT}, {"role": "user", "content": prompt}]
    try:
        return grok_chat(messages, temperature=0.2, max_tokens=120)
    except Exception as e:
        logger.error(f"[run_profession_aware error] {e}")
        return "No profession-specific info available."

def run_localization_translation(advisory_text, target_language):
    prompt = LOCALIZATION_TRANSLATION_PROMPT.format(target_language=target_language, advisory_text=advisory_text)
    messages = [{"role": "system", "content": ADVISOR_STRUCTURED_SYSTEM_PROMPT}, {"role": "user", "content": prompt}]
    try:
        return grok_chat(messages, temperature=0.2, max_tokens=150)
    except Exception as e:
        logger.error(f"[run_localization_translation error] {e}")
        return advisory_text

def run_improve_from_feedback(feedback_text, advisory_text):
    prompt = IMPROVE_FROM_FEEDBACK_PROMPT.format(feedback_text=feedback_text, advisory_text=advisory_text)
    messages = [{"role": "system", "content": ADVISOR_STRUCTURED_SYSTEM_PROMPT}, {"role": "user", "content": prompt}]
    try:
        return grok_chat(messages, temperature=0.1, max_tokens=180)
    except Exception as e:
        logger.error(f"[run_improve_from_feedback error] {e}")
        return "No improvement recommendations available."

def run_alternate_strategies(user_message, input_data, advisory_text):
    prompt = (
        "Given the following advisory and threat context, generate 2-3 realistic, actionable alternate strategies (Plan B/C) "
        "for minimizing risk, rerouting, or adjusting operations. For each, give: (1) a concise headline, (2) step-by-step actions, "
        "(3) conditions where it should be used. Avoid generic advice. "
        "If alternates were already included in the advisory, expand or clarify them.\n\n"
        f"User Query: {user_message}\n\nInput Data: {json.dumps(input_data, ensure_ascii=False, default=json_default)}\n\n"
        f"Main Advisory:\n{advisory_text}"
    )
    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are an alternate strategies planner for Sentinel AI."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.45,
            max_tokens=400
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"[Alternate strategies error] {e}")
        return None

def enforce_mandatory_alternatives(advisory_text):
    if re.search(r"\bavoid\b|\bdo not travel\b", advisory_text, re.IGNORECASE) and not re.search(r"Alternate Strategies|Plan B|Plan C", advisory_text, re.IGNORECASE):
        return advisory_text + "\n\n⚠️ Mandatory alternatives required: If avoidance is advised, suggest at least one safe alternative route, timing, or method."
    return advisory_text

def get_action_alternatives(region, user_message):
    routes = FALLBACK_ROUTES.get(region, [])
    if routes:
        alternatives = []
        for r in routes:
            alternatives.append(
                f"Avoid {region}, take {r['route']} via {r['city']} instead. {r['description']}"
            )
        return "\n".join(alternatives)
    # If not available, use GPT to generate
    prompt = ACTION_ALTERNATIVES_PROMPT.format(region=region)
    messages = [
        {"role": "system", "content": "You are a travel safety planner."},
        {"role": "user", "content": f"{prompt}\nUser Query: {user_message}"}
    ]
    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=messages,
            temperature=0.3,
            max_tokens=200
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"[Action alternatives error] {e}")
        return "No alternatives found."

def generate_structured_advisory(user_message, alerts, email="anonymous", region=None, threat_type=None, profession=None, target_language=None):
    assert all('score' in a and 'label' in a for a in alerts), \
        "Advisor expects only enriched alerts (from alerts table, not raw_alerts)!"
    logger.info(f"generate_structured_advisory called with {len(alerts)} alerts (all enriched and scored).")

    plan = get_plan(email)
    plan = (plan or "FREE").upper()
    plan_limits = get_plan_limits(email)
    risk_profiles = load_risk_profiles()
    static_risk_profile = get_static_profile(region, risk_profiles)
    triggers = extract_triggers(alerts)
    sources = summarize_sources(alerts)
    categories, subcategories = summarize_categories(alerts)
    reports_analyzed = len(alerts)
    confidence = min(100, (reports_analyzed * 15) + (10 if any(triggers) else 0))
    if confidence > 100: confidence = 100
    if reports_analyzed < 2:
        confidence = 55 if reports_analyzed == 1 else 35

    region_display = region or "Unspecified Region"
    risk_display = get_risk_level_from_profile(static_risk_profile)
    heading = f"ALERT: Sentinel AI Advisory\nRegion: {region_display}\nRisk Level: {risk_display}\n\n"

    # --- User Profile Injection ---
    user_profile = fetch_user_profile(email) or {}
    user_pref_profile = fetch_user_preferences(email) or {}
    risk_tolerance = user_pref_profile.get("risk_tolerance") or user_profile.get("risk_tolerance")
    asset_type = user_pref_profile.get("asset_type") or user_profile.get("asset_type")
    preferred_alert_types = user_pref_profile.get("preferred_alert_types") or user_profile.get("preferred_alert_types")
    role = user_pref_profile.get("role") or user_profile.get("role", None)
    emphasis_sections = user_pref_profile.get("emphasis_sections", None)

    section_order = [
        "Forecast", "Historical Context", "Public Sentiment", "Legal/Regulatory Risk",
        "Accessibility/Inclusion", "Cyber/OT Risk", "Environmental/Epidemic Risk", "Profession-Specific Advice"
    ]
    if emphasis_sections and isinstance(emphasis_sections, list):
        section_order = emphasis_sections + [s for s in section_order if s not in emphasis_sections]

    if region and categories:
        past_incidents = fetch_past_incidents(region=region, category=categories[0], days=30, limit=15)
    else:
        past_incidents = []
    summarized_past = summarize_incidents_for_prompt(past_incidents, max_len=700)
    trend_direction = compute_trend_direction(past_incidents)
    future_risk_probability = compute_future_risk_probability(past_incidents)
    recommended_watch_window = "Reassess in 6 hours" if trend_direction == "deteriorating" else "Reassess in 12 hours"

    if not check_user_message_quota(email, plan_limits):
        logger.info(f"[Quota] User {email} exceeded monthly message quota")
        analyst_insight = random.choice(ZIKA_QUOTES)
        # Fallback logic: include mandatory action alternatives!
        action_alternatives = get_action_alternatives(region, user_message)
        alt_strategies = run_alternate_strategies(user_message, {}, "")
        fallback_text = (
            f"{heading}"
            "⚠️ You have reached your monthly message quota for advisory requests. "
            "Upgrade your plan or wait until next month for more access."
            f"\n\n{analyst_insight}\n\n{format_cta(plan)}"
            f"\n\n🚦 Action Alternatives:\n{action_alternatives}"
            f"\n\n🧭 Alternate Strategies:\n{alt_strategies if alt_strategies else 'No alternate strategies found.'}"
        )
        result = {
            "advisory_text": fallback_text,
            "watch_window": None,
            "alternate_strategies": alt_strategies,
            "action_alternatives": action_alternatives,
        }
        save_advisory_log_json(email, region, user_message, result, risk_display, plan)
        log_advisory_usage(email, region, plan, "advisor_chat", "quota_exceeded", user_message)
        return result
    increment_user_message_usage(email)
    log_advisory_usage(email, region, plan, "advisor_chat", "success", user_message)

    input_data = {
        "user_message": user_message,
        "region": region,
        "threat_type": threat_type,
        "triggers": triggers,
        "categories": categories,
        "subcategories": subcategories,
        "risk_profile": static_risk_profile,
        "risk_tolerance": risk_tolerance,
        "asset_type": asset_type,
        "preferred_alert_types": preferred_alert_types,
        "role": role,
        "emphasis_sections": section_order,
        "sources": sources,
        "reports_analyzed": reports_analyzed,
        "confidence": confidence,
        "plan": plan,
        "past_incidents": summarized_past,
        "trend_direction": trend_direction,
        "future_risk_probability": future_risk_probability,
        "recommended_watch_window": recommended_watch_window
    }

    personalization_note = ""
    if risk_tolerance:
        personalization_note += f"\n\n[Personalization] Advice tailored for risk tolerance: {risk_tolerance}."
    if asset_type:
        personalization_note += f" Asset focus: {asset_type}."
    if preferred_alert_types:
        personalization_note += f" Preferred alert types: {preferred_alert_types}."
    if role:
        personalization_note += f" Role: {role}."
    if emphasis_sections:
        personalization_note += f" Emphasis: {', '.join(emphasis_sections)}."

    advisory_sections = []

    try:
        system_prompt = ADVISOR_STRUCTURED_SYSTEM_PROMPT + personalization_note
        structured_user_prompt = ADVISOR_STRUCTURED_USER_PROMPT.format(
            user_message=user_message,
            input_data=json.dumps(input_data, ensure_ascii=False, default=json_default)
        )
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": structured_user_prompt}
            ],
            temperature=0.4,
            max_tokens=800
        )
        response_text = response.choices[0].message.content.strip()
        advisory_sections.append(("[System LLM]", response_text))
    except Exception as e:
        logger.error(f"[OpenAI error] {e}")
        try:
            grok_resp = grok_chat([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": structured_user_prompt}
            ], model="grok-3-mini", temperature=0.4)
            advisory_sections.append(("[Grok fallback]", grok_resp if grok_resp else ""))
        except Exception as ex:
            logger.error(f"[Grok error] {ex}")
            analyst_insight = random.choice(ZIKA_QUOTES)
            advisory_sections.append(("[Grok fallback]", f"\n\n{analyst_insight}\n\n{format_cta(plan)}"))

    advisory = ""
    section_map = {
        "Forecast": f"\n\n🕒 Forecast: Probability of escalation: {future_risk_probability*100:.1f}% | Trend: {trend_direction} | {run_forecast(region, input_data, user_message)}",
        "Historical Context": f"\n\n📊 Historical Context: {run_historical_comparison(user_message, region)}",
        "Public Sentiment": f"\n\n🌡️ Public Sentiment: {run_sentiment_analysis(user_message)}",
        "Legal/Regulatory Risk": f"\n\n⚖️ Legal/Regulatory Risk: {run_legal_regulatory_risk(user_message, region)}",
        "Accessibility/Inclusion": f"\n\n♿ Accessibility/Inclusion: {run_accessibility_inclusion(region, triggers, user_message)}",
        "Cyber/OT Risk": f"\n\n💻 Cyber/OT Risk: {run_cyber_ot_risk(user_message, region)}",
        "Environmental/Epidemic Risk": f"\n\n🌍 Environmental/Epidemic Risk: {run_environmental_epidemic_risk(user_message, region)}",
        "Profession-Specific Advice": f"\n\n👔 Profession-Specific Advice: {run_profession_aware(role, region, triggers, user_message)}" if role else "",
    }

    for label, section in advisory_sections:
        advisory += f"\n\n{section}"

    for section_name in section_order:
        section = section_map.get(section_name, "")
        if section:
            advisory += section

    analyst_insight = random.choice(ZIKA_QUOTES)
    advisory += f"\n\n{analyst_insight}\n\n{format_cta(plan)}"

    # ---- Action Alternatives ----
    action_alternatives = get_action_alternatives(region, user_message)
    advisory += f"\n\n🚦 Action Alternatives:\n{action_alternatives}"

    # ---- Alternate Strategies ----
    alt_strategies = run_alternate_strategies(user_message, input_data, advisory)
    if not alt_strategies:
        alt_strategies = parse_alternate_strategies(advisory)
    advisory += f"\n\n🧭 Alternate Strategies:\n{alt_strategies if alt_strategies else 'No alternate strategies found.'}"

    if target_language:
        advisory = run_localization_translation(advisory, target_language)

    advisory = enforce_mandatory_alternatives(advisory)
    watch_window = parse_watch_window(advisory) or recommended_watch_window

    result = {
        "advisory_text": f"{heading}{advisory}",
        "watch_window": watch_window,
        "alternate_strategies": alt_strategies,
        "trend_direction": trend_direction,
        "future_risk_probability": future_risk_probability,
        "risk_tolerance": risk_tolerance,
        "asset_type": asset_type,
        "preferred_alert_types": preferred_alert_types,
        "role": role,
        "emphasis_sections": section_order,
        "action_alternatives": action_alternatives,
    }
    save_advisory_log_json(email, region, user_message, result, risk_display, plan)
    log_advisory_usage(email, region, plan, "advisor_chat", "success", advisory)
    return result

def generate_advice(user_message, alerts, email="anonymous", region=None, threat_type=None, profession=None, target_language=None):
    assert all('score' in a and 'label' in a for a in alerts), \
        "Advisor expects only enriched alerts (from alerts table, not raw_alerts)!"
    logger.info(f"generate_advice called with {len(alerts)} alerts (all enriched and scored).")

    plan = get_plan(email)
    if not isinstance(plan, str):
        plan = "FREE"
    plan = plan.upper()
    risk_profiles = load_risk_profiles()

    if not isinstance(user_message, str):
        user_message = str(user_message)
    if region is not None and not isinstance(region, str):
        region = str(region)
    if threat_type is not None and not isinstance(threat_type, str):
        threat_type = str(threat_type)

    if not alerts:
        static = get_static_profile(region, risk_profiles)
        triggers = []
        sources = []
        reports_analyzed = 0
        categories = []
        subcategories = []
        return generate_structured_advisory(
            user_message, alerts, email=email, region=region, threat_type=threat_type, profession=profession, target_language=target_language
        )

    for alert in alerts:
        alert["label"] = alert.get("label", alert.get("threat_label", "Unknown"))

    return generate_structured_advisory(
        user_message, alerts, email=email, region=region, threat_type=threat_type, profession=profession, target_language=target_language
    )