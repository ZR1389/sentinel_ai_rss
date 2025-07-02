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

def check_usage_allowed(email, plan_rules):
    usage_data = load_usage_data()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    usage_today = usage_data.get(email, {}).get(today, 0)

    plan_limit = plan_rules.get("chat_limit")
    if plan_limit is None:
        return True  # Unlimited
    return usage_today < plan_limit

def increment_usage(email):
    usage_data = load_usage_data()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if email not in usage_data:
        usage_data[email] = {}
    if today not in usage_data[email]:
        usage_data[email][today] = 0
    usage_data[email][today] += 1
    save_usage_data(usage_data)

load_dotenv()
client = OpenAI()

def translate_text(text, target_lang="en"):
    if target_lang == "en" or not text:
        return text
    try:
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
        return f"[Translation error: {str(e)}]"

def handle_user_query(message, email, lang="en"):
    plan = get_plan(email)

    if message.lower().strip() in ["status", "plan"]:
        return {"plan": plan}

    if not check_usage_allowed(email, plan):
        return {
            "reply": "⛔ You have reached your daily message limit. Upgrade for unlimited access.",
            "plan": plan,
            "alerts": []
        }

    increment_usage(email)

    raw_alerts = get_clean_alerts()
    threat_scores = [assess_threat_level(alert) for alert in raw_alerts]
    summaries = summarize_alerts(raw_alerts)
    translated_summaries = [translate_text(summary, lang) for summary in summaries]

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

    fallback = generate_advice(message)

    return {
        "reply": fallback,
        "plan": plan,
        "alerts": results
    }
