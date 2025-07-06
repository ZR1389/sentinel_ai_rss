import json
import os
from dotenv import load_dotenv
from openai import OpenAI
from datetime import datetime

from rss_processor import get_clean_alerts
from threat_scorer import assess_threat_level
from threat_engine import summarize_alerts
from advisor import generate_advice
from clients import get_plan

USAGE_FILE = "usage_log.json"

load_dotenv()
client = OpenAI()
with open("risk_profiles.json", "r") as f:
    risk_profiles = json.load(f)

# -------------------------
# Load & Save Usage
# -------------------------
def load_usage_data():
    if not os.path.exists(USAGE_FILE):
        return {}
    with open(USAGE_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def save_usage_data(data):
    with open(USAGE_FILE, "w") as f:
        json.dump(data, f, indent=2)

# -------------------------
# Usage Limit Enforcement
# -------------------------
PLAN_LIMITS = {
    "Free": {"chat_limit": 3},
    "Basic": {"chat_limit": 100},
    "Pro": {"chat_limit": 500},
    "VIP": {"chat_limit": None},  # Unlimited
}

def check_usage_allowed(email, plan):
    usage_data = load_usage_data()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    usage_today = usage_data.get(email, {}).get(today, 0)
    limit = PLAN_LIMITS.get(plan, {}).get("chat_limit")
    if limit is None:
        return True
    return usage_today < limit

def increment_usage(email):
    usage_data = load_usage_data()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if email not in usage_data:
        usage_data[email] = {}
    if today not in usage_data[email]:
        usage_data[email][today] = 0
    usage_data[email][today] += 1
    save_usage_data(usage_data)

# -------------------------
# Translation Support
# -------------------------
def translate_text(text, target_lang="en"):
    try:
        if not isinstance(text, str):
            text = str(text)
        text = text.strip()
        if target_lang == "en" or not text:
            return text

        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": f"Translate the following text into {target_lang}."},
                {"role": "user", "content": text}
            ],
            temperature=0.3
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Translation error: {e}")
        return f"[Translation error: {str(e)}]"

# -------------------------
# MAIN ENTRY POINT
# -------------------------
def handle_user_query(message, email, lang="en", region=None, threat_type=None, plan=None):
    print(f"Received query: {message} | Email: {email} | Lang: {lang}")
    plan = get_plan(email)
    print(f"Plan: {plan}")

    if message.lower().strip() in ["status", "plan"]:
        return {"plan": plan}

    if not check_usage_allowed(email, plan):
        print("Usage limit reached")
        return {
            "reply": "❌ You reached your monthly message quota. Please upgrade to get more access.",
            "plan": plan,
            "alerts": []
        }

    increment_usage(email)
    print("Usage incremented")

    raw_alerts = get_clean_alerts(region=region, topic=threat_type, summarize=True)
    print(f"Alerts fetched: {len(raw_alerts)}")

    if not raw_alerts:
        if plan in ["PRO", "VIP"]:
            # GPT fallback (intelligent, Zika-style)
            context = f"""
            No live alerts available, but the user asked: "{message}"
            Region: {region or 'Unspecified'}
            Threat Type: {threat_type or 'Unspecified'}
            Based on professional security logic, provide clear, field-tested travel advisory.
            Use a tone that is expert, direct, and realistic — like Zika Rakita would speak.
            """
            try:
                response = client.chat.completions.create(
                    model="gpt-4",
                    messages=[
                        {
                            "role": "system",
                            "content": "You're a seasoned travel risk advisor trained by Zika Rakita. Deliver professional advice using his tone, logic, and field-tested wisdom."
                        },
                        {
                            "role": "user",
                            "content": context
                        }
                    ],
                    temperature=0.4,
                    max_tokens=400
                )
                fallback = response.choices[0].message.content.strip()
            except Exception as e:
                fallback = "Advisory temporarily unavailable. Please check back soon or consult official channels."

            translated_fallback = translate_text(fallback, lang)
            return {
                "reply": translated_fallback,
                "plan": plan,
                "alerts": []
            }
        else:
            # Static fallback from risk_profiles.json
            region_data = risk_profiles.get(region, {})
            fallback = region_data.get(lang) or region_data.get("en")
            translated = fallback or "No alerts right now. Stay aware and consult regional sources."
            return {
                "reply": translated,
                "plan": plan,
                "alerts": []
            }

    # Process raw alerts
    threat_scores = [assess_threat_level(alert) for alert in raw_alerts]
    summaries = summarize_alerts(raw_alerts)
    print("Summaries generated")

    translated_summaries = [translate_text(summary, lang) for summary in summaries]
    print(f"Summaries translated to {lang}")

    results = []
    for i, alert in enumerate(raw_alerts):
        results.append({
            "title": alert.get("title", ""),
            "summary": alert.get("summary", ""),
            "link": alert.get("link", ""),
            "source": alert.get("source", ""),
            "type": translate_text(alert.get("type", ""), lang),
            "level": threat_scores[i],
            "gpt_summary": translated_summaries[i]
        })

    fallback = generate_advice(message, raw_alerts)
    translated_fallback = translate_text(fallback, lang)
    print("Fallback advice generated and translated")

    return {
        "reply": translated_fallback,
        "plan": plan,
        "alerts": results
    }
