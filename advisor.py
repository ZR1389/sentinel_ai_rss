import os
from openai import OpenAI
from dotenv import load_dotenv
from plan_rules import PLAN_RULES
from plan_utils import get_plan
from xai_client import grok_chat
import json
import time

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=15)

def load_risk_profiles():
    try:
        with open("risk_profiles.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def get_static_profile(region, risk_profiles):
    if not region:
        return None
    # Try exact, case-insensitive match
    region_key = next(
        (k for k in risk_profiles if k.lower() == region.strip().lower()), None
    )
    if region_key:
        entry = risk_profiles.get(region_key)
        if isinstance(entry, dict):
            return entry.get("en") or next(iter(entry.values()), None)
        return entry
    return None

def gpt_fallback(user_message, region, threat_type, plan):
    if plan in ["PRO", "VIP"]:
        system_prompt = (
            "You're Zika Rakita, a global security advisor with 20+ years of experience. "
            "Deliver professional travel security advice using a direct, realistic tone. "
            "Incorporate general security knowledge and static risk profiles if needed."
        )
        user_prompt = (
            f"No live alerts available, but the user asked: '{user_message}'\n"
            f"Region: {region or 'Unspecified'}\n"
            f"Threat Type: {threat_type or 'Unspecified'}\n"
            f"Based on professional security logic, provide clear, field-tested travel advisory."
        )
    else:
        system_prompt = (
            "You are a security risk assistant. Give a short, clear summary of the main risks for the given region. "
            "If risk is low, say so. Do NOT say 'no alerts' or 'no information'."
        )
        user_prompt = (
            f"User query: {user_message}\n"
            f"Region: {region or 'Unspecified'}\n"
            f"Threat Type: {threat_type or 'Unspecified'}\n"
            f"Provide a brief, actionable summary for a traveler."
        )

    max_retries = 3
    retry_delay = 4
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.4,
                max_tokens=400
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"[OpenAI error] {e}")
            # Fallback to Grok-3-mini
            grok_resp = grok_chat([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ], model="grok-3-mini", temperature=0.4, max_tokens=400)
            if grok_resp:
                return grok_resp
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                retry_delay *= 2
            else:
                return "Advisory temporarily unavailable. Please check back soon or consult official channels."

def generate_advice(user_message, alerts, email="anonymous", region=None, threat_type=None):
    if not isinstance(user_message, str):
        user_message = str(user_message)
    if region is not None and not isinstance(region, str):
        region = str(region)
    if threat_type is not None and not isinstance(threat_type, str):
        threat_type = str(threat_type)

    plan = get_plan(email)
    if not isinstance(plan, str):
        plan = "FREE"
    plan = plan.upper()
    insight_level = PLAN_RULES.get(plan, {}).get("insights", False)

    risk_profiles = load_risk_profiles()

    # Fallback logic when no alerts
    if not alerts:
        # 1. Try static profile
        static = get_static_profile(region, risk_profiles)
        if static:
            return static
        # 2. Otherwise, always use GPT fallback for everyone
        return gpt_fallback(user_message, region, threat_type, plan)

    # If alerts exist and plan allows insights, use GPT for tailored advice
    if insight_level and plan != "FREE":
        try:
            content = (
                "You are a global security advisor. Based on the following user message and alerts, provide a clear, practical safety briefing for a traveler:\n\n"
                f"User message: {user_message}\n\n"
                "Alerts:\n"
            )
            for alert in alerts[:5]:
                title = alert.get('title', '')
                summary = alert.get('summary', '')
                content += f"- {str(title)}: {str(summary)}\n"

            response = client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {
                        "role": "system",
                        "content": "Respond as a travel security expert. Be concise, realistic, and actionable."
                    },
                    {"role": "user", "content": content}
                ],
                temperature=0.5
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"[OpenAI error] {e}")
            # Fallback to Grok-3-mini
            grok_resp = grok_chat([
                {"role": "system", "content": "Respond as a travel security expert. Be concise, realistic, and actionable."},
                {"role": "user", "content": content}
            ], model="grok-3-mini", temperature=0.5, max_tokens=400)
            if grok_resp:
                return grok_resp
            return f"Error generating advisory: {str(e)}"

    # Fallback for non-insight plans
    return (
        "🛡️ Basic safety alert summary:\n"
        "- Monitor your surroundings.\n"
        "- Follow official travel advisories.\n"
        "- Upgrade to receive personalized threat analysis."
    )