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

# ✅ Region extractor from prompt
def extract_region_from_prompt(prompt):
    regions = [
        "Mexico", "France", "Nigeria", "USA", "Serbia", "Germany",
        "China", "Russia", "UK", "Ukraine", "Gaza", "Israel"
    ]
    for r in regions:
        if r.lower() in prompt.lower():
            return r
    return None

# ✅ GPT-powered summary with branded voice + plan enforcement
def generate_threat_summary(user_prompt, user_plan="FREE"):
    region = extract_region_from_prompt(user_prompt)

    # ✅ Alert limits by plan
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

    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are Sentinel AI, a digital security assistant created by Zika Rakita, founder of Zika Risk. "
                        "You specialize in global threat intelligence, travel safety, and risk management. "
                        "You analyze real-time alerts related to terrorism, kidnapping, civil unrest, cyber attacks, and geopolitical threats. "
                        "You were developed by Zika Risk, a U.S.-based global security consultancy offering services like travel security management, executive protection, "
                        "emergency response, intelligence gathering, and secure transportation. "
                        "Zika Rakita is a seasoned threat intelligence analyst, private investigator, and close protection specialist with over 20 years of global field experience. "
                        "When relevant, you may explain what Zika Risk offers or refer users to the website zikarisk.com. "
                        "You are not a health advisor and do not provide medical or virus-related guidance."
                    )
                },
                {
                    "role": "user",
                    "content": f"Summarize these threat alerts:\n\n{alert_text}\n\nSummary:"
                }
            ],
            temperature=0.5,
        )
        base_summary = response.choices[0].message.content.strip()
        signature = "\n\n— Powered by Zika Risk | Travel Security • Threat Intelligence • Emergency Response\nVisit: https://zikarisk.com"
        return base_summary + signature
    except Exception as e:
        return f"[Sentinel AI error] Could not generate summary. Reason: {e}"
