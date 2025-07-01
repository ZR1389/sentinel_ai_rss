
import os
import json
from dotenv import load_dotenv
from openai import OpenAI
from rss_processor import get_clean_alerts

# ✅ Load environment
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ✅ Get user plan from clients.json
def get_plan_for_email(email):
    try:
        with open("clients.json", "r") as f:
            clients = json.load(f)
        for c in clients:
            if c["email"].lower() == email.lower():
                return c["plan"].upper()
    except:
        pass
    return "FREE"

# ✅ Region extractor for location-specific summaries
def extract_region_from_prompt(prompt):
    regions = [
        "Mexico", "France", "Nigeria", "USA", "Serbia", "Germany",
        "China", "Russia", "UK", "Ukraine", "Gaza", "Israel", "Iran", "India"
    ]
    for r in regions:
        if r.lower() in prompt.lower():
            return r
    return None

# ✅ Simple intent classifier: summary or general advice?
def is_summary_request(prompt):
    keywords = [
        "what happened", "threats in", "incidents in", "situation in",
        "alerts", "news from", "summarize", "report", "crisis in"
    ]
    return any(k in prompt.lower() for k in keywords)

# ✅ Core smart handler
def handle_user_prompt(user_prompt, user_email):
    user_plan = get_plan_for_email(user_email)
    region = extract_region_from_prompt(user_prompt)

    # ✅ If it's a news-style query, summarize alerts
    if is_summary_request(user_prompt):
        if user_plan == "FREE":
            alerts = get_clean_alerts(limit=3, region=region)
        elif user_plan == "BASIC":
            alerts = get_clean_alerts(limit=10, region=region)
        elif user_plan == "PRO":
            alerts = get_clean_alerts(limit=20, region=region)
        elif user_plan == "VIP":
            alerts = get_clean_alerts(limit=30, region=region)
        else:
            alerts = get_clean_alerts(limit=3, region=region)

        if not alerts:
            return f"No recent alerts found for '{region or 'your region'}'. Stay safe."

        alert_text = "\n\n".join(f"{a['title']}: {a['summary']}" for a in alerts)
        system_msg = (
            "You are Sentinel AI, a digital security assistant created by Zika Risk. "
            "You specialize in global threat intelligence, risk monitoring, and travel safety. "
            "Summarize verified alerts clearly and quickly, focusing on danger level and affected region."
        )
        user_msg = f"Summarize these threat alerts:\n\n{alert_text}\n\nSummary:"
    else:
        system_msg = (
            "You are Sentinel AI, a security-focused AI developed by Zika Rakita and his company, Zika Risk. "
            "You answer security-related questions, provide personal and travel safety tips, and explain Zika Risk’s services: "
            "travel security management, executive protection, cyber safety, crisis response, secure transportation, and intelligence analysis. "
            "You may also provide context about Zika Rakita, a global security advisor and founder of Zika Risk and Sentinel AI."
        )
        user_msg = user_prompt

    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg}
            ],
            temperature=0.5,
        )
        base_response = response.choices[0].message.content.strip()
        signature = "\n\n— Powered by Zika Risk | Travel Security • Threat Intelligence • Emergency Response\nVisit: zikarisk.com"
        return base_response + signature
    except Exception as e:
        return f"[Sentinel AI error] Could not generate response. Reason: {e}"
