import os
import json
from dotenv import load_dotenv
from openai import OpenAI
from rss_processor import get_clean_alerts

# ✅ Load environment variables
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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

# ✅ GPT summary generator
def generate_threat_summary(user_prompt, user_plan="FREE"):
    region = extract_region_from_prompt(user_prompt)

    if user_plan == "FREE":
        alerts = get_clean_alerts(limit=3, region=region)
    else:
        alerts = get_clean_alerts(limit=15, region=region)

    if not alerts:
        return f"No recent alerts found for '{region or 'your region'}'. Stay safe."

    alert_text = "\n\n".join(f"{a['title']}: {a['summary']}" for a in alerts)

    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a security analyst specializing in threat intelligence."},
                {"role": "user", "content": f"Summarize these threat alerts:\n\n{alert_text}\n\nSummary:"}
            ],
            temperature=0.5,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"[Sentinel AI error] Could not generate summary. Reason: {e}"

