import os
import random
import re
import time
import json
from openai import OpenAI
from dotenv import load_dotenv
from plan_rules import PLAN_RULES
from plan_utils import get_plan
from xai_client import grok_chat
from prompts import (
    ADVISOR_SYSTEM_PROMPT_PRO,
    ADVISOR_USER_PROMPT_PRO,
    ADVISOR_SYSTEM_PROMPT_BASIC,
    ADVISOR_USER_PROMPT_BASIC,
    ADVISOR_STRUCTURED_SYSTEM_PROMPT,
    ADVISOR_STRUCTURED_USER_PROMPT,
)

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=15)

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
    """Use cached triggers field if present, else extract from summary/title."""
    triggers_all = set()
    for alert in alerts:
        if "triggers" in alert and alert["triggers"]:
            triggers_all.update(alert["triggers"])
        else:
            for field in ['title', 'summary']:
                text = alert.get(field, "")
                for trigger in [
                    "armed robbery", "civil unrest", "kidnapping", "protest", "evacuation",
                    "martial law", "carjacking", "load shedding", "corruption", "terrorism",
                    "shooting", "power outage"
                ]:
                    if trigger.lower() in text.lower():
                        triggers_all.add(trigger)
    return list(triggers_all)

def summarize_sources(alerts):
    """Use new source_name and link fields if present."""
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
    """Summarize detected categories and subcategories from alerts."""
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

def gpt_primary_grok_fallback(
    user_message, region, threat_type, plan, triggers=None, risk_profile=None, sources=None, reports_analyzed=None, email="anonymous", categories=None, subcategories=None
):
    region_display = region or "Unspecified Region"
    risk_display = get_risk_level_from_profile(risk_profile)
    heading = f"Sentinel AI Advisory – {region_display} | Risk Level: {risk_display}\n\n"

    if plan in ["PRO", "VIP"]:
        system_prompt = ADVISOR_SYSTEM_PROMPT_PRO
        structured_user_prompt = ADVISOR_USER_PROMPT_PRO.format(
            user_message=user_message,
            input_data=json.dumps(
                {
                    "region": region,
                    "threat_type": threat_type,
                    "triggers": triggers,
                    "categories": categories,
                    "subcategories": subcategories,
                    "risk_profile": risk_profile,
                    "sources": sources,
                    "reports_analyzed": reports_analyzed,
                    "plan": plan,
                },
                ensure_ascii=False,
            ),
        )
    else:
        system_prompt = ADVISOR_SYSTEM_PROMPT_BASIC
        structured_user_prompt = ADVISOR_USER_PROMPT_BASIC.format(
            user_message=user_message,
            region=region or "Unspecified",
            threat_type=threat_type or "Unspecified",
        )

    max_retries = 3
    retry_delay = 4
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": structured_user_prompt}
                ],
                temperature=0.4,
                max_tokens=600
            )
            response_text = response.choices[0].message.content.strip()
            analyst_insight = random.choice(ZIKA_QUOTES)
            result = f"{heading}{response_text}\n\n{analyst_insight}\n\n{format_cta(plan)}"
            save_advisory_log_json(email, region, user_message, result, risk_display, plan)
            return result
        except Exception as e:
            print(f"[OpenAI error] {e}")
            try:
                grok_resp = grok_chat([
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": structured_user_prompt}
                ], model="grok-3-mini", temperature=0.4)
            except Exception as ex:
                print(f"[Grok error] {ex}")
                grok_resp = None
            if grok_resp:
                result = f"{heading}{grok_resp}\n\n{format_cta(plan)}"
                save_advisory_log_json(email, region, user_message, result, risk_display, plan)
                return result
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                retry_delay *= 2
            else:
                fallback_rating = risk_display
                result = (
                    f"{heading}"
                    f"⚠️ Live intelligence unavailable right now. Based on past risk profiles, "
                    f"{region_display} is generally rated {fallback_rating}. "
                    "Avoid hotspots, monitor news, and use secure transportation where possible."
                )
                save_advisory_log_json(email, region, user_message, result, risk_display, plan)
                return result

def generate_structured_advisory(user_message, alerts, email="anonymous", region=None, threat_type=None):
    plan = get_plan(email)
    plan = (plan or "FREE").upper()
    insight_level = PLAN_RULES.get(plan, {}).get("insights", False)
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

    if insight_level and plan != "FREE":
        try:
            system_prompt = ADVISOR_STRUCTURED_SYSTEM_PROMPT
            content = {
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
            structured_user_prompt = ADVISOR_STRUCTURED_USER_PROMPT.format(
                user_message=user_message,
                input_data=json.dumps(content, ensure_ascii=False)
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
            analyst_insight = random.choice(ZIKA_QUOTES)
            response_text += f"\n\n{analyst_insight}"
            result = f"{heading}{response_text}\n\n{format_cta(plan)}"
            save_advisory_log_json(email, region, user_message, result, risk_display, plan)
            return result
        except Exception as e:
            print(f"[OpenAI error] {e}")
            try:
                grok_resp = grok_chat([
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": structured_user_prompt}
                ], model="grok-3-mini", temperature=0.4)
            except Exception as ex:
                print(f"[Grok error] {ex}")
                grok_resp = None
            if grok_resp:
                result = f"{heading}{grok_resp}\n\n{format_cta(plan)}"
                save_advisory_log_json(email, region, user_message, result, risk_display, plan)
                return result
            fallback_rating = risk_display
            result = (
                f"{heading}"
                f"⚠️ Live intelligence unavailable right now. Based on past risk profiles, "
                f"{region_display} is generally rated {fallback_rating}. "
                "Avoid hotspots, monitor news, and use secure transportation where possible."
            )
            save_advisory_log_json(email, region, user_message, result, risk_display, plan)
            return result
    else:
        analyst_insight = random.choice(ZIKA_QUOTES)
        result = (
            f"{heading}"
            "🛡️ Basic safety alert summary:\n"
            "- Monitor your surroundings.\n"
            "- Follow official travel advisories.\n"
            "- Upgrade to receive personalized threat analysis."
            f"\n\n{analyst_insight}\n\n{format_cta(plan)}"
        )
        save_advisory_log_json(email, region, user_message, result, risk_display, plan)
        return result

def generate_advice(user_message, alerts, email="anonymous", region=None, threat_type=None):
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
            subcategories=subcategories
        )

    return generate_structured_advisory(
        user_message, alerts, email=email, region=region, threat_type=threat_type
    )