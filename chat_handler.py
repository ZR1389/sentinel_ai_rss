import json
import os
from datetime import datetime
from openai import OpenAI
from rss_processor import get_clean_alerts
from threat_scorer import assess_threat_level

# Load API key
client = OpenAI()

# Constants
USAGE_FILE = "usage_log.json"
CLIENTS_FILE = "clients.json"
MAX_FREE_MESSAGES_PER_DAY = 3

# Load clients
with open(CLIENTS_FILE) as f:
    CLIENTS = {entry["email"]: entry["plan"].upper() for entry in json.load(f)}

# Load or init usage log
if os.path.exists(USAGE_FILE):
    with open(USAGE_FILE, "r") as f:
        usage_log = json.load(f)
else:
    usage_log = {}

# Reset daily usage if needed
def reset_daily_usage():
    today = datetime.now().strftime("%Y-%m-%d")
    if usage_log.get("date") != today:
        usage_log.clear()
        usage_log["date"] = today
        save_usage_log()

def save_usage_log():
    with open(USAGE_FILE, "w") as f:
        json.dump(usage_log, f, indent=2)

# MAIN CHAT HANDLER FUNCTION
def handle_user_query(message, email="anonymous", lang="en"):
    reset_daily_usage()

    plan = CLIENTS.get(email, "FREE")
    key = email.lower()

    # Usage tracking for FREE plan
    if plan == "FREE":
        usage_log.setdefault(key, 0)
        if usage_log[key] >= MAX_FREE_MESSAGES_PER_DAY:
            return {
                "reply": "⚠️ You’ve reached your daily message limit. Upgrade to continue.",
                "plan": "FREE"
            }
        usage_log[key] += 1
        save_usage_log()

    # Handle GPT-powered answer (for all plans)
    alerts = get_clean_alerts()
    response = run_gpt_response(message, alerts)

    return {
        "reply": response,
        "plan": plan
    }

# GPT Response Logic
def run_gpt_response(message, alerts):
    prompt = f"""
You're a multilingual AI security assistant for travelers. A user asked:

{message}

Respond using recent intelligence and global alerts like:
{json.dumps(alerts[:3], indent=2)}

Be concise. Show intelligence. Add travel advisory if relevant.
"""

    completion = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are a security-focused AI assistant."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.6,
    )

    return completion.choices[0].message.content.strip()
