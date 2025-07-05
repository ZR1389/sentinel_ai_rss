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
            "reply": "\u274c You reached your monthly message quota. Please upgrade to get more access.",
            "plan": plan,
            "alerts": []
        }

    increment_usage(email)
    print("Usage incremented")

    raw_alerts = get_clean_alerts(region=region, topic=threat_type, summarize=True)
    print(f"Alerts fetched: {len(raw_alerts)}")
    
    if not raw_alerts:
        # Use region, threat type, and message to generate realistic fallback
        context = f"""
        There are no current alerts available from RSS feeds or Telegram.
        However, the user is asking: "{message}"
        Region: {region or 'unspecified'}
        Threat type: {threat_type or 'unspecified'}
        Based on your intelligence training, offer a professional travel risk advisory.
        """
        try:
            response = client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "You are a threat intelligence advisor. Provide realistic fallback guidance for travelers even when real-time alerts are missing."},
                    {"role": "user", "content": context}
                ],
            temperature=0.5,
            max_tokens=300
            )
            fallback = response.choices[0].message.content.strip()
        except Exception as e:
            fallback = "⚠️ No current data available. Please consult official travel advisories."

        translated_fallback = translate_text(fallback, lang)
        print("No alerts — returning realistic multilingual fallback")
        return {
            "reply": translated_fallback,
            "plan": plan,
            "alerts": []
        }

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
            "type": alert.get("type", ""),
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
