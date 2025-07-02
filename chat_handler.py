import json
import os
from dotenv import load_dotenv
from openai import OpenAI
from rss_processor import get_clean_alerts

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
            temperature=0.3,
            timeout=30  # ✅ prevent hanging on translation
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

# ✅ Threat type filters by plan
THREAT_FILTERS = {
    "VIP": None,
    "PRO": {"Kidnapping", "Cyber", "Terrorism", "Protest", "Crime"},
    "FREE": {"Protest", "Crime"}
}

# ✅ Get alerts filtered by plan type
def get_filtered_alerts(plan):
    all_alerts = get_clean_alerts(limit=10)  # 🔧 Limit alerts to avoid GPT overload
    allowed_types = THREAT_FILTERS.get(plan)
    filtered = []

    for alert in all_alerts:
        alert_type = alert.get("type", "Unclassified")
        alert["type"] = alert_type
        alert["level"] = "Moderate"  # 🛑 TEMP: Bypass GPT scoring
        if allowed_types is None or alert_type in allowed_types:
            filtered.append(alert)

    # Group by threat type
    grouped = {}
    for alert in filtered:
        grouped.setdefault(alert["type"], []).append(alert)

    return grouped

# ✅ Sentinel AI behavior prompt
SYSTEM_PROMPT = (
    "You are Sentinel AI, a multilingual travel and threat intelligence assistant created by Zika Rakita.\n"
    "You are operated by the security firm Zika Risk.\n"
    "You provide real-time threat summaries using curated RSS feeds, global risk databases, and open-source intelligence.\n"
    "If live data is missing, respond with useful fallback guidance based on known regional risks, trends, or recent reports.\n"
    "Do NOT say 'I don’t have access to real-time data'. Instead, provide helpful insights from past data or likely scenarios.\n"
    "If the user asks about Zika Rakita or Zika Risk, describe them accurately based on this identity.\n"
    "Always answer clearly, concisely, and with a confident, professional tone."
)

# ✅ Handle user query (grouped by threat type + plan filter)
def handle_user_query(message, email="anonymous", lang="en"):
    plan = get_plan_for_email(email)
    threat_groups = get_filtered_alerts(plan)

    # Match query to alerts (region/country/topic), fallback to all if nothing matches
    filtered = {
        k: [a for a in v if message.lower() in a['title'].lower() or message.lower() in a['summary'].lower()]
        for k, v in threat_groups.items()
    }
    filtered = {k: v for k, v in filtered.items() if v}
    if not filtered:
        filtered = threat_groups

    # Build structured context
    sections = []
    flat_alert_list = []

    for threat_type, alerts in filtered.items():
        section_lines = [f"🔸 {threat_type.upper()} ({len(alerts)} alert(s))"]
        for alert in alerts:
            entry = (
                f"🔹 {alert['title']}\n"
                f"{alert['summary']}\n"
                f"Threat Level: {alert['level']}\n"
                f"Source: {alert['source']}\n"
                f"Link: {alert['link']}\n"
            )
            section_lines.append(entry)
            flat_alert_list.append({
                "title": alert["title"],
                "summary": alert["summary"],
                "type": alert["type"],
                "level": alert["level"],
                "link": alert["link"],
                "source": alert["source"]
            })

        sections.append("\n".join(section_lines))

    raw_context = "\n\n".join(sections)
    if not raw_context.strip():
        raw_context = "No recent high-priority alerts available."

    # ✂️ Truncate context before translation
    short_context = raw_context[:4000]
    translated_context = translate_text(short_context, target_lang=lang)

    # 🧠 GPT reply with threat context and timeout
    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"{message}\n\nContext:\n{translated_context}"}
            ],
            timeout=30  # ✅ prevent GPT reply timeout
        )
        gpt_reply = response.choices[0].message.content.strip()
    except Exception as e:
        gpt_reply = f"❌ GPT failed to respond: {str(e)}"

    # 🌍 Translate GPT reply if needed
    translated_reply = translate_text(gpt_reply, target_lang=lang)

    return {
        "reply": translated_reply,
        "plan": plan,
        "alerts": flat_alert_list  # ✅ Used by frontend filters
    }
