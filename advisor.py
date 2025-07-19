import os
import random
import re
import time
import json
import psycopg2
from openai import OpenAI
from dotenv import load_dotenv

# ---- SHARED KEYWORD/ENRICHMENT IMPORTS ----
from risk_shared import (
    compute_keyword_weight,
    enrich_log,
    run_sentiment_analysis,
    run_forecast,
    run_legal_risk,
    run_cyber_ot_risk,
    run_environmental_epidemic_risk
)

from plan_utils import (
    get_plan,
    get_plan_feature,
    get_plan_limits,
    check_user_message_quota,
    increment_user_message_usage
)
from xai_client import grok_chat
from prompts import (
    ADVISOR_SYSTEM_PROMPT_PRO,
    ADVISOR_USER_PROMPT_PRO,
    ADVISOR_SYSTEM_PROMPT_BASIC,
    ADVISOR_USER_PROMPT_BASIC,
    ADVISOR_STRUCTURED_SYSTEM_PROMPT,
    ADVISOR_STRUCTURED_USER_PROMPT,
    PROACTIVE_FORECAST_PROMPT,
    HISTORICAL_COMPARISON_PROMPT,
    SENTIMENT_ANALYSIS_PROMPT,
    LEGAL_REGULATORY_RISK_PROMPT,
    ACCESSIBILITY_INCLUSION_PROMPT,
    PROFESSION_AWARE_PROMPT,
    LOCALIZATION_TRANSLATION_PROMPT,
    CYBER_OT_RISK_PROMPT,
    ENVIRONMENTAL_EPIDEMIC_RISK_PROMPT,
    IMPROVE_FROM_FEEDBACK_PROMPT,
)

import logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# --- Railway environment logging ---
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

def format_cta(plan):
    links = {
        "FREE": "🚨 <a href='https://buy.stripe.com/3cI4gzb6m2lucxcaCk8so05' target='_blank'>Upgrade to Basic for detailed travel intelligence and regional alerts.</a>",
        "BASIC": "🔐 <a href='https://buy.stripe.com/28E14n4HYe4cap439S8so04' target='_blank'>Upgrade to Pro for pre-travel risk briefings, daily alerts, and planning tools.</a>",
        "PRO": "🔭 <a href='https://buy.stripe.com/4gMdR94HYaS09l0cKs8so03' target='_blank'>Upgrade to VIP for direct access to analysts, itinerary review, and emergency support.</a>",
        "VIP": "🧠 <a href='mailto:zika@zikarisk.com?subject=VIP+Itinerary+Review' target='_blank'>Your VIP plan includes access to Zika Risk experts. Request a custom briefing now.</a>"
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
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
    # --- Optional: Log to shared enrichment log for full audit trail ---
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

# --- New prompt helpers ---
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
    messages = [{"role": "system", "content": ADVISOR_SYSTEM_PROMPT_PRO}, {"role": "user", "content": prompt}]
    try:
        return grok_chat(messages, temperature=0.2, max_tokens=100)
    except Exception as e:
        logger.error(f"[run_historical_comparison error] {e}")
        return "No historical comparison available."

def run_accessibility_inclusion(region, threats, user_message):
    prompt = ACCESSIBILITY_INCLUSION_PROMPT.format(region=region, threats=threats, user_message=user_message)
    messages = [{"role": "system", "content": ADVISOR_SYSTEM_PROMPT_PRO}, {"role": "user", "content": prompt}]
    try:
        return grok_chat(messages, temperature=0.2, max_tokens=120)
    except Exception as e:
        logger.error(f"[run_accessibility_inclusion error] {e}")
        return "No accessibility/inclusion info available."

def run_profession_aware(profession, region, threats, user_message):
    prompt = PROFESSION_AWARE_PROMPT.format(profession=profession, region=region, threats=threats, user_message=user_message)
    messages = [{"role": "system", "content": ADVISOR_SYSTEM_PROMPT_PRO}, {"role": "user", "content": prompt}]
    try:
        return grok_chat(messages, temperature=0.2, max_tokens=120)
    except Exception as e:
        logger.error(f"[run_profession_aware error] {e}")
        return "No profession-specific info available."

def run_localization_translation(advisory_text, target_language):
    prompt = LOCALIZATION_TRANSLATION_PROMPT.format(target_language=target_language, advisory_text=advisory_text)
    messages = [{"role": "system", "content": ADVISOR_SYSTEM_PROMPT_PRO}, {"role": "user", "content": prompt}]
    try:
        return grok_chat(messages, temperature=0.2, max_tokens=150)
    except Exception as e:
        logger.error(f"[run_localization_translation error] {e}")
        return advisory_text  # fallback to original

def run_improve_from_feedback(feedback_text, advisory_text):
    prompt = IMPROVE_FROM_FEEDBACK_PROMPT.format(feedback_text=feedback_text, advisory_text=advisory_text)
    messages = [{"role": "system", "content": ADVISOR_SYSTEM_PROMPT_PRO}, {"role": "user", "content": prompt}]
    try:
        return grok_chat(messages, temperature=0.1, max_tokens=180)
    except Exception as e:
        logger.error(f"[run_improve_from_feedback error] {e}")
        return "No improvement recommendations available."

# --- Advisory logic (updated) ---
def gpt_primary_grok_fallback(user_message, region, threat_type, plan, triggers=None, risk_profile=None, sources=None, reports_analyzed=None, email="anonymous", categories=None, subcategories=None, profession=None, target_language=None):
    region_display = region or "Unspecified Region"
    risk_display = get_risk_level_from_profile(risk_profile)
    heading = f"Sentinel AI Advisory – {region_display} | Risk Level: {risk_display}\n\n"

    plan_limits = get_plan_limits(email)
    if not check_user_message_quota(email, plan_limits):
        logger.info(f"[Quota] User {email} exceeded monthly message quota")
        analyst_insight = random.choice(ZIKA_QUOTES)
        result = (
            f"{heading}"
            "⚠️ You have reached your monthly message quota for advisory requests. "
            "Upgrade your plan or wait until next month for more access."
            f"\n\n{analyst_insight}\n\n{format_cta(plan)}"
        )
        save_advisory_log_json(email, region, user_message, result, risk_display, plan)
        log_advisory_usage(email, region, plan, "advisor_chat", "quota_exceeded", user_message)
        return result
    increment_user_message_usage(email)
    log_advisory_usage(email, region, plan, "advisor_chat", "success", user_message)

    input_data = {
        "region": region,
        "threat_type": threat_type,
        "triggers": triggers,
        "categories": categories,
        "subcategories": subcategories,
        "risk_profile": risk_profile,
        "sources": sources,
        "reports_analyzed": reports_analyzed,
        "plan": plan
    }
    advisory = ""

    if plan in ["PRO", "VIP"]:
        system_prompt = ADVISOR_SYSTEM_PROMPT_PRO
        structured_user_prompt = ADVISOR_USER_PROMPT_PRO.format(
            user_message=user_message,
            input_data=json.dumps(input_data, ensure_ascii=False),
        )
        try:
            response = client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": structured_user_prompt}
                ],
                temperature=0.4,
                max_tokens=650
            )
            response_text = response.choices[0].message.content.strip()
            advisory += response_text
        except Exception as e:
            logger.error(f"[OpenAI error] {e}")
            try:
                grok_resp = grok_chat([
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": structured_user_prompt}
                ], model="grok-3-mini", temperature=0.4)
                advisory += grok_resp if grok_resp else ""
            except Exception as ex:
                logger.error(f"[Grok error] {ex}")

    else:
        system_prompt = ADVISOR_SYSTEM_PROMPT_BASIC
        structured_user_prompt = ADVISOR_USER_PROMPT_BASIC.format(
            user_message=user_message,
            region=region or "Unspecified",
            threat_type=threat_type or "Unspecified",
        )
        try:
            response = client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": structured_user_prompt}
                ],
                temperature=0.4,
                max_tokens=400
            )
            response_text = response.choices[0].message.content.strip()
            advisory += response_text
        except Exception as e:
            logger.error(f"[OpenAI error] {e}")
            try:
                grok_resp = grok_chat([
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": structured_user_prompt}
                ], model="grok-3-mini", temperature=0.4)
                advisory += grok_resp if grok_resp else ""
            except Exception as ex:
                logger.error(f"[Grok error] {ex}")

    # Add advanced prompt sections
    advisory += f"\n\n🕒 Forecast: {run_forecast(region, input_data, user_message)}"
    if triggers:
        advisory += f"\n\n📊 Historical Context: {run_historical_comparison(user_message, region)}"
        advisory += f"\n\n🌡️ Public Sentiment: {run_sentiment_analysis(user_message)}"
        advisory += f"\n\n⚖️ Legal/Regulatory Risk: {run_legal_regulatory_risk(user_message, region)}"
        advisory += f"\n\n♿ Accessibility/Inclusion: {run_accessibility_inclusion(region, triggers, user_message)}"
        advisory += f"\n\n💻 Cyber/OT Risk: {run_cyber_ot_risk(user_message, region)}"
        advisory += f"\n\n🌍 Environmental/Epidemic Risk: {run_environmental_epidemic_risk(user_message, region)}"
        if profession:
            advisory += f"\n\n👔 Profession-Specific Advice: {run_profession_aware(profession, region, triggers, user_message)}"
    analyst_insight = random.choice(ZIKA_QUOTES)
    advisory += f"\n\n{analyst_insight}\n\n{format_cta(plan)}"

    # Localization (if requested)
    if target_language:
        advisory = run_localization_translation(advisory, target_language)

    result = f"{heading}{advisory}"
    save_advisory_log_json(email, region, user_message, result, risk_display, plan)
    log_advisory_usage(email, region, plan, "advisor_chat", "success", advisory)
    return result

def generate_structured_advisory(user_message, alerts, email="anonymous", region=None, threat_type=None, profession=None, target_language=None):
    plan = get_plan(email)
    plan = (plan or "FREE").upper()
    insight_level = get_plan_feature(email, "personalized_insights_frequency") is not None
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
    heading = f"Sentinel AI Advisory – {region_display} | Risk Level: {risk_display}\n\n"

    plan_limits = get_plan_limits(email)
    if not check_user_message_quota(email, plan_limits):
        logger.info(f"[Quota] User {email} exceeded monthly message quota")
        analyst_insight = random.choice(ZIKA_QUOTES)
        result = (
            f"{heading}"
            "⚠️ You have reached your monthly message quota for advisory requests. "
            "Upgrade your plan or wait until next month for more access."
            f"\n\n{analyst_insight}\n\n{format_cta(plan)}"
        )
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
        "sources": sources,
        "reports_analyzed": reports_analyzed,
        "confidence": confidence,
        "plan": plan
    }
    advisory = ""
    if insight_level and plan != "FREE":
        try:
            system_prompt = ADVISOR_STRUCTURED_SYSTEM_PROMPT
            structured_user_prompt = ADVISOR_STRUCTURED_USER_PROMPT.format(
                user_message=user_message,
                input_data=json.dumps(input_data, ensure_ascii=False)
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
            advisory += response_text
        except Exception as e:
            logger.error(f"[OpenAI error] {e}")
            try:
                grok_resp = grok_chat([
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": structured_user_prompt}
                ], model="grok-3-mini", temperature=0.4)
                advisory += grok_resp if grok_resp else ""
            except Exception as ex:
                logger.error(f"[Grok error] {ex}")
    else:
        analyst_insight = random.choice(ZIKA_QUOTES)
        advisory += (
            "🛡️ Basic safety alert summary:\n"
            "- Monitor your surroundings.\n"
            "- Follow official travel advisories.\n"
            "- Upgrade to receive personalized threat analysis."
            f"\n\n{analyst_insight}\n\n{format_cta(plan)}"
        )

    # Add advanced prompt sections
    advisory += f"\n\n🕒 Forecast: {run_forecast(region, input_data, user_message)}"
    if triggers:
        advisory += f"\n\n📊 Historical Context: {run_historical_comparison(user_message, region)}"
        advisory += f"\n\n🌡️ Public Sentiment: {run_sentiment_analysis(user_message)}"
        advisory += f"\n\n⚖️ Legal/Regulatory Risk: {run_legal_regulatory_risk(user_message, region)}"
        advisory += f"\n\n♿ Accessibility/Inclusion: {run_accessibility_inclusion(region, triggers, user_message)}"
        advisory += f"\n\n💻 Cyber/OT Risk: {run_cyber_ot_risk(user_message, region)}"
        advisory += f"\n\n🌍 Environmental/Epidemic Risk: {run_environmental_epidemic_risk(user_message, region)}"
        if profession:
            advisory += f"\n\n👔 Profession-Specific Advice: {run_profession_aware(profession, region, triggers, user_message)}"
    analyst_insight = random.choice(ZIKA_QUOTES)
    advisory += f"\n\n{analyst_insight}\n\n{format_cta(plan)}"

    # Localization (if requested)
    if target_language:
        advisory = run_localization_translation(advisory, target_language)

    result = f"{heading}{advisory}"
    save_advisory_log_json(email, region, user_message, result, risk_display, plan)
    log_advisory_usage(email, region, plan, "advisor_chat", "success", advisory)
    return result

def generate_advice(user_message, alerts, email="anonymous", region=None, threat_type=None, profession=None, target_language=None):
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
        return gpt_primary_grok_fallback(
            user_message,
            region,
            threat_type,
            plan,
            triggers=triggers,
            risk_profile=static,
            sources=sources,
            reports_analyzed=reports_analyzed,
            email=email,
            categories=categories,
            subcategories=subcategories,
            profession=profession,
            target_language=target_language
        )

    return generate_structured_advisory(
        user_message, alerts, email=email, region=region, threat_type=threat_type, profession=profession, target_language=target_language
    )