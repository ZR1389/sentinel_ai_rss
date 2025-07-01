import os
import json
from dotenv import load_dotenv
from openai import OpenAI
from rss_processor import get_clean_alerts

# ✅ Load environment variables
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

# ✅ Region extractor
def extract_region_from_prompt(prompt):
    regions = [
        "Mexico", "France", "Nigeria", "USA", "Serbia", "Germany",
        "China", "Russia", "UK", "Ukraine", "Gaza", "Israel"
    ]
    for r in regions:
        if r.lower() in prompt.lower():
            return r
    return None

# ✅ Trigger keywords to decide if prompt is about threats
def is_threat_query(prompt):
    keywords = ["threat", "alert", "travel warning", "civil unrest", "kidnap", "terror", "situation", "danger", "explosion", "protest", "evacuation"]
    return any(k in prompt.lower() for k in keywords)

# ✅ GPT-powered response (smart hybrid)
def generate_threat_summary(user_prompt, user_plan="FREE"):
    region = extract_region_from_prompt(user_prompt)

    if is_threat_query(user_prompt):
        # ✅ Use RSS alerts only if it's a threat-related query
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
        prompt = f"Summarize these threat alerts:\n\n{alert_text}\n\nSummary:"
    else:
        # ✅ Use prompt as-is for general security reasoning
        prompt = user_prompt

    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are Sentinel AI, a digital security assistant developed by Zika Risk. "
                        "You specialize in threat intelligence, travel security, risk mitigation, and emergency response. "
                        "If the user asks about Zika Risk or your identity, explain you're part of Zika Rakita's security firm, offering services like executive protection, crisis management, secure transport, and travel threat briefings. "
                        "You are not a health assistant. You do not give virus or medical advice."
                    )
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0.5,
        )
        reply = response.choices[0].message.content.strip()
        return reply + "\n\n— Powered by Zika Risk | www.zikarisk.com"
    except Exception as e:
        return f"[Sentinel AI error] Could not generate response. Reason: {e}"
