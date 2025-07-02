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

# ✅ Load usage per user per day
def load_usage_data():
    if not os.path.exists(USAGE_FILE):
        return {}
    with open(USAGE_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

# ✅ Save usage log to disk
def save_usage_data(data):
    with open(USAGE_FILE, "w") as f:
        json.dump(data, f, indent=2)

# ✅ Check if user can use chat again
def check_usage_allowed(email, plan_rules):
    usage_data = load_usage_data()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    usage_today = usage_data.get(email, {}).get(today, 0)

    plan_limit = plan_rules.get("chat_limit")
    if plan_limit is None:
        return True
    return usage_today < plan_limit

# ✅ Increment chat usage
def increment_usage(email):
    usage_data = load_usage_data()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if email not in usage_data:
        usage_data[email] = {}
    if today not in usage_data[email]:
        usage_data[email][today] = 0
    usage_data[email][today] += 1
    save_usage_data(usage_data)

# ✅ Translate summaries
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
        print(f"❌ Translation error: {e}")
        return f"[Translation error: {str(e)}]"

# ✅ Main user query handler
def handle_user_query(message, email, lang="en"):
    print(f"📩 Received query: {message} | Email: {email} | Lang: {lang}")
    plan = get_plan(email)
    print(f"✅ Plan: {plan}")

    if message.lower().strip() in ["status", "plan"]:
        return {"plan": plan}

    plan_limits = {
        "Free": {"chat_limit": 3},
        "Pro": {"chat_limit": 15},
        "VIP": {"chat_limit": None}
    }

    if not check_usage_allowed(email, plan_limits.get(plan, {})):
        print("⛔ Usage limit reached")
        return {
            "reply": "⛔ You have reached your daily message limit. Upgrade for unlimited access.",
            "plan": plan,
            "alerts": []
        }

    increment_usage(email)
    print("✅ Usage incremented")

    raw_alerts = get_clean_alerts()
    print(f"✅ Alerts fetched: {len(raw_alerts)}")

    threat_scores = [assess_threat_level(alert) for alert in raw_alerts]
    summaries = summarize_alerts(raw_alerts)
    print("✅ Summaries generated")

    translated_summaries = [translate_text(summary, lang) for summary in summaries]
    print(f"🌍 Summaries translated to {lang}")

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
    print("✅ Fallback advice generated")

    return {
        "reply": fallback,
        "plan": plan,
        "alerts": results
    }
