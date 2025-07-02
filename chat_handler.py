import json
import os
from dotenv import load_dotenv
from openai import OpenAI

from rss_processor import get_clean_alerts
from threat_scorer import assess_threat_level
from threat_engine import summarize_alerts
from usage_logger import check_usage_allowed, increment_usage
from advisor import generate_advice
from clients import get_plan

load_dotenv()
client = OpenAI()

USAGE_FILE = "usage_log.json"

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

    if not check_usage_allowed(email, plan, USAGE_FILE):
        return {
            "reply": "⛔ You have reached your daily message limit. Upgrade for unlimited access.",
            "plan": plan,
            "alerts": []
        }

    increment_usage(email, USAGE_FILE)

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
