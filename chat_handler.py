import json
import os
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI

from rss_processor import get_clean_alerts
from threat_scorer import assess_threat_level

# ✅ Load environment variables
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ✅ Translate text using GPT if needed
def translate_text(text, target_lang="en"):
    if target_lang.lower() == "en":
        return text  # Skip translation
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
        print(f"❌ Translation failed: {e}")
        return text  # Fallback to original

# ✅ Load client plans
with open("clients.json") as f:
    CLIENTS = json.load(f)

def get_plan_for_email(email):
    for client in CLIENTS:
        if client["email"].lower() == email.lower():
            return client["plan"].upper()
    return "FREE"

# ✅ Prepare region-based alert summaries with threat levels
ALERTS = get_clean_alerts(limit=10)
REGIONAL_SUMMARIES = {}
for alert in ALERTS:
    level = assess_threat_level(alert)
    country = alert.get("country") or alert.get("region") or "Unknown"
    REGIONAL_SUMMARIES.setdefault(country, []).append({
        "title": alert['title'],
        "summary": alert['summary'],
        "source": alert['source'],
        "link": alert['link'],
        "level": level
    })

# ✅ Identity and behavior prompt
SYSTEM_PROMPT = (
    "You are Sentinel AI, a multilingual travel and threat intelligence assistant created by Zika Rakita.\n"
    "You are operated by the security firm Zika Risk.\n"
    "You provide real-time threat summaries using curated RSS feeds, global risk databases, and open-source intelligence.\n"
    "If live data is missing, respond with useful fallback guidance based on known regional risks, trends, or recent reports.\n"
    "Do NOT say 'I don't have access to real-time data'. Instead, provide helpful insights from past data or likely scenarios.\n"
    "If the user asks about Zika Rakita or Zika Risk, describe them accurately based on this identity.\n"
    "Always answer clearly, concisely, and with a confident, professional tone."
)

# ✅ Handle user query
def handle_user_query(message, email="anonymous", lang="en"):
    plan = get_plan_for_email(email)
    region_alerts = REGIONAL_SUMMARIES.get(message.strip(), [])

    # Build raw regional summary
    alert_texts = []
    for alert in region_alerts:
        entry = (
            f"🔹 {alert['title']}\n"
            f"{alert['summary']}\n"
            f"Threat Level: {alert['level']}\n"
            f"Source: {alert['source']}\n"
            f"Link: {alert['link']}\n"
        )
        alert_texts.append(entry)

    raw_alert_context = "\n\n".join(alert_texts)
    raw_context = raw_alert_context or "No recent high-priority alerts available."

    # 🔁 Translate context if needed
    translated_context = translate_text(raw_context, target_lang=lang)

    # GPT reply based on translated alert summaries
    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"{message}\n\nContext:\n{translated_context}"}
            ]
        )
        gpt_reply = response.choices[0].message.content.strip()
    except Exception as e:
        gpt_reply = f"❌ An error occurred: {str(e)}"

    # ✅ Translate GPT reply if needed
    translated_reply = translate_text(gpt_reply, target_lang=lang)

    return {
        "reply": translated_reply,
        "plan": plan
    }
