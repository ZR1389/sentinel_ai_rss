import json
import openai
from dotenv import load_dotenv
import os
from rss_processor import get_clean_alerts
from threat_scorer import assess_threat_level
from datetime import datetime

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

# ✅ Load clients
with open("clients.json") as f:
    CLIENTS = json.load(f)

def get_plan_for_email(email):
    for client in CLIENTS:
        if client["email"].lower() == email.lower():
            return client["plan"].upper()
    return "FREE"

# ✅ Load recent alerts into context
ALERTS = get_clean_alerts(limit=10)
REGIONAL_SUMMARIES = {}
for alert in ALERTS:
    level = assess_threat_level(alert)
    country = alert.get("country") or alert.get("region") or "Unknown"
    REGIONAL_SUMMARIES.setdefault(country, []).append(f"- {alert['title']} ({level})")

# ✅ System Identity
SYSTEM_PROMPT = (
    "You are Sentinel AI, a multilingual travel and threat intelligence assistant created by Zika Rakita.\n"
    "You are operated by the security firm Zika Risk.\n"
    "You provide real-time threat summaries using curated RSS feeds, global risk databases, and open-source intelligence.\n"
    "If live data is missing, respond with useful fallback guidance based on known regional risks, trends, or recent reports.\n"
    "Do NOT say 'I don't have access to real-time data'. Instead, provide helpful insights from past data or likely scenarios.\n"
    "If the user asks about Zika Rakita or Zika Risk, describe them accurately based on this identity.\n"
    "Always answer clearly, concisely, and with a confident, professional tone."
)

# ✅ User Query Handler
def handle_user_query(message, email="anonymous", lang="en"):
    plan = get_plan_for_email(email)
    region_context = "\n".join(REGIONAL_SUMMARIES.get(message.strip(), []))

    context = (
        f"Today's top alerts for '{message}':\n{region_context or 'No recent high-priority alerts available.'}\n"
        "Use this context to help the user.")

    try:
        completion = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"{message}\n\nContext: {context}"}
            ]
        )
        reply = completion.choices[0].message.content.strip()
    except Exception as e:
        reply = f"❌ An error occurred: {str(e)}"

    return {"reply": reply, "plan": plan}
