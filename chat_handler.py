import json
import os
from openai import OpenAI
from dotenv import load_dotenv
from rss_processor import get_clean_alerts
from advisor import generate_advice
from plan_utils import get_plan, PLAN_RULES
from plan_rules import PLAN_RULES

load_dotenv()
client = OpenAI()

# ✅ Usage file shared across system
USAGE_FILE = "usage.log.json"

def load_usage():
    if os.path.exists(USAGE_FILE):
        with open(USAGE_FILE, "r") as f:
            try:
                data = json.load(f)
                return data.get("usage", {}), data.get("date", "unknown")
            except json.JSONDecodeError:
                return {}, "unknown"
    return {}, "unknown"

def save_usage(usage, current_date):
    with open(USAGE_FILE, "w") as f:
        json.dump({"date": current_date, "usage": usage}, f, indent=2)

def get_plan(email):
    try:
        with open("clients.json", "r") as f:
            clients = json.load(f)
            for client in clients:
                if client["email"].lower() == email.lower():
                    return client.get("plan", "FREE")
    except:
        pass
    return "FREE"

def handle_user_query(message, email="anonymous", lang="en"):
    if message.lower() == "status":
        plan = get_plan(email)
        return {"plan": plan}

    plan = get_plan(email)
    rules = PLAN_RULES.get(plan, PLAN_RULES["FREE"])
    chat_limit = rules["chat_limit"]

    usage, last_date = load_usage()
    current_date = os.getenv("TODAY_DATE_OVERRIDE", "2025-07-01")  # or dynamically use datetime if needed

    # ✅ Reset usage if date changed
    if last_date != current_date:
        usage = {}

    usage[email] = usage.get(email, 0)

    # ✅ Enforce chat limit
    if chat_limit is not None and usage[email] >= chat_limit:
        return {
            "reply": f"🚫 You have reached your monthly message limit for the {plan} plan.\nUpgrade to get more access.",
            "plan": plan,
            "alerts": []
        }

    # ✅ Run advisory engine
    try:
        alerts = get_clean_alerts()
        reply = generate_advice(message, alerts, lang=lang)
        usage[email] += 1
        save_usage(usage, current_date)

        return {
            "reply": reply,
            "plan": plan,
            "alerts": alerts
        }

    except Exception as e:
        return {
            "reply": f"❌ Advisory engine error: {str(e)}",
            "plan": plan,
            "alerts": []
        }
