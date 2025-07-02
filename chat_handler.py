import json
import os
from dotenv import load_dotenv
from advisor import get_advisory
from threat_engine import get_structured_alerts

# ✅ Load environment variables
load_dotenv()

# ✅ GPT client setup
from openai import OpenAI
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ✅ Translate GPT output if needed
def translate_text(text, target_lang="en"):
    if target_lang.lower() == "en":
        return text
    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": f"Translate the following text into {target_lang}."},
                {"role": "user", "content": text}
            ],
            temperature=0.3,
            timeout=30
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"❌ Translation failed: {e}")
        return text

# ✅ Load client plans from JSON
with open("clients.json") as f:
    CLIENTS = json.load(f)

def get_plan_for_email(email):
    for client in CLIENTS:
        if client["email"].lower() == email.lower():
            return client["plan"].upper()
    return "FREE"

# ✅ Main user query handler
def handle_user_query(message, email="anonymous", lang="en"):
    plan = get_plan_for_email(email)
    
    # 🛰️ Fetch alerts (grouped + flat)
    threat_groups, flat_list = get_structured_alerts(plan=plan, query=message)

    # 🧠 Get GPT-based advisory message
    advisory = get_advisory(message, lang=lang)

    # 🌐 Translate if needed
    translated_reply = translate_text(advisory, lang)

    return {
        "reply": translated_reply,
        "plan": plan,
        "alerts": flat_list
    }
