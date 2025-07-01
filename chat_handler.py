import os
import json
from dotenv import load_dotenv
from openai import OpenAI
from rss_processor import get_clean_alerts

# ✅ Load environment variables
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ✅ Load fallback risk profiles
try:
    with open("risk_profiles.json", "r") as f:
        fallback_profiles = json.load(f)
except:
    fallback_profiles = {}

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

# ✅ Extract region name dynamically from prompt
def extract_region_from_prompt(prompt):
    words = prompt.split()
    known_countries = [
        "Mozambique", "Niger", "Nigeria", "Mexico", "France", "USA", "Serbia", "Germany",
        "China", "Russia", "UK", "Ukraine", "Gaza", "Israel", "Brazil", "Pakistan", "India",
        "Kenya", "Sudan", "South Africa", "DRC", "Turkey", "Iran", "Afghanistan"
    ]
    for country in known_countries:
        if country.lower() in prompt.lower():
            return country
    return None

# ✅ Identify if prompt is threat-related
def is_threat_query(prompt):
    keywords = [
        "threat", "alert", "travel warning", "civil unrest", "kidnap",
        "terror", "situation", "danger", "explosion", "protest",
        "evacuation", "risk", "shooting", "bomb", "curfew", "unrest"
    ]
    return any(k in prompt.lower() for k in keywords)

# ✅ Core function: Threat summary generation (RSS + GPT + fallback)
def generate_threat_summary(user_prompt, user_plan="FREE"):
    region = extract_region_from_prompt(user_prompt)

    if is_threat_query(user_prompt):
        # Tier-based alert limits
        limit = {
            "FREE": 3,
            "BASIC": 10,
            "PRO": 20,
            "VIP": 30
        }.get(user_plan.upper(), 3)

        alerts = get_clean_alerts(limit=limit, region=region)

        # ❌ No alerts found — use fallback if available
        if not alerts:
            if region and region in fallback_profiles:
                fallback_text = fallback_profiles[region]
                return (
                    f"No verified alerts found for '{region}' in the last 24 hours.\n\n"
                    f"However, regional data indicates:\n{fallback_text}\n\n"
                    "— Powered by Zika Risk | www.zikarisk.com"
                )
            else:
                return (
                    f"No recent verified alerts found for '{region or 'your region'}'. "
                    "While no real-time alerts are present, risks may still exist depending on local crime, political instability, or natural threats. "
                    "Please consult Zika Risk for an in-depth country profile or updated intelligence brief.\n\n"
                    "— Powered by Zika Risk | www.zikarisk.com"
                )

        # ✅ Alerts found — use GPT to summarize
        alert_text = "\n\n".join(f"{a['title']}: {a['summary']}" for a in alerts)
        prompt = f"Summarize these threat alerts for {region or 'this region'}:\n\n{alert_text}\n\nSummary:"

    else:
        # Not a threat query — general GPT reasoning
        prompt = user_prompt

    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are Sentinel AI, a digital security assistant built by Zika Risk. "
                        "You specialize in threat intelligence, geopolitical analysis, travel safety, and crisis response. "
                        "If asked about your origin, you are created by Zika Rakita, founder of Zika Risk. "
                        "Never offer medical or virus-related advice. Always focus on physical, digital, and travel risks."
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
