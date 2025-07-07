import json
import os
import time
from dotenv import load_dotenv
from openai import OpenAI
from datetime import datetime

from rss_processor import get_clean_alerts
from threat_scorer import assess_threat_level
from threat_engine import summarize_alerts
from advisor import generate_advice
from clients import get_plan

USAGE_FILE = "usage_log.json"
RESPONSE_CACHE = {}

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=15)  # Set timeout here


with open("risk_profiles.json", "r") as f:
    risk_profiles = json.load(f)

def load_usage_data():
    if not os.path.exists(USAGE_FILE):
        return {}
    with open(USAGE_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def save_usage_data(data):
    with open(USAGE_FILE, "w") as f:
        json.dump(data, f, indent=2)

PLAN_LIMITS = {
    "Free": {"chat_limit": 3},
    "Basic": {"chat_limit": 100},
    "Pro": {"chat_limit": 500},
    "VIP": {"chat_limit": None},
}

def check_usage_allowed(email, plan):
    usage_data = load_usage_data()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    usage_today = usage_data.get(email, {}).get(today, 0)
    limit = PLAN_LIMITS.get(plan, {}).get("chat_limit")
    return usage_today < limit if limit is not None else True

def increment_usage(email):
    usage_data = load_usage_data()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if email not in usage_data:
        usage_data[email] = {}
    if today not in usage_data[email]:
        usage_data[email][today] = 0
    usage_data[email][today] += 1
    save_usage_data(usage_data)

def translate_text(text, target_lang="en"):
    max_retries = 3
    retry_delay = 4
    for attempt in range(max_retries):
        try:
            if not isinstance(text, str):
                text = str(text)
            text = text.strip()
            if target_lang == "en" or not text:
                return text
            response = client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": f"Translate the following text into {target_lang} with cultural accuracy."},
                    {"role": "user", "content": text}
                ],
                temperature=0.3,
                max_tokens=200
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"Translation error (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                retry_delay *= 2
            else:
                return f"[Translation error: {str(e)}]"

def handle_user_query(message, email, lang="en", region=None, threat_type=None, plan=None):
    print(f"Received query: {message} | Email: {email} | Lang: {lang}")
    plan_raw = get_plan(email) or plan or "Free"
    plan = plan_raw.upper() if isinstance(plan_raw, str) else "FREE"
    print(f"Plan: {plan}")

    query = message.get("query", "") if isinstance(message, dict) else str(message)
    print(f"Query content: {query}")

    if isinstance(query, str) and query.lower().strip() in ["status", "plan"]:
        return {"plan": plan}

    if not check_usage_allowed(email, plan):
        print("Usage limit reached")
        translated_error = translate_text(
            "You reached your monthly message quota. Please upgrade to get more access.", lang
        )
        return {
            "reply": translated_error,
            "plan": plan,
            "alerts": []
        }

    increment_usage(email)
    print("Usage incremented")

    cache_key = f"{query}_{lang}_{region}_{threat_type}_{plan}"
    if cache_key in RESPONSE_CACHE:
        print("Returning cached response")
        return RESPONSE_CACHE[cache_key]
    
    if not isinstance(region, str):
       print(f"[!] Warning: region was not a string: {region}")
       region = "All Regions"

    if not isinstance(threat_type, str):
       print(f"[!] Warning: threat_type was not a string: {threat_type}")
       threat_type = "All Threats"

    print(f"[TRACE] region={region} ({type(region)}), threat_type={threat_type} ({type(threat_type)})")

    raw_alerts = get_clean_alerts(region=region, topic=threat_type, summarize=True)
    print(f"Alerts fetched: {len(raw_alerts)}")

    if not raw_alerts:
        if plan in ["PRO", "VIP"]:
            context = (
                f"No live alerts available, but the user asked: '{query}'\n"
                f"Region: {region or 'Unspecified'}\n"
                f"Threat Type: {threat_type or 'Unspecified'}\n"
                f"Based on professional security logic, provide clear, field-tested travel advisory."
            )
            max_retries = 3
            retry_delay = 4
            for attempt in range(max_retries):
                try:
                    response = client.chat.completions.create(
                        model="gpt-4",
                        messages=[
                            {
                                "role": "system",
                                "content": (
                                    "You're Zika Rakita, a global security advisor with 20+ years of experience. "
                                    "Deliver professional travel security advice using a direct, realistic tone. "
                                    "Incorporate general security knowledge and static risk profiles if needed."
                                )
                            },
                            {"role": "user", "content": context}
                        ],
                        temperature=0.4,
                        max_tokens=400
                    )
                    fallback = response.choices[0].message.content.strip()
                    break
                except Exception as e:
                    print(f"Fallback error (attempt {attempt + 1}/{max_retries}): {e}")
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        retry_delay *= 2
                    else:
                        fallback = "Advisory temporarily unavailable. Please check back soon or consult official channels."

            translated_fallback = translate_text(fallback, lang)
            result = {
                "reply": translated_fallback,
                "plan": plan,
                "alerts": []
            }
            RESPONSE_CACHE[cache_key] = result
            return result
        else:
            region_data = risk_profiles.get(region, {})
            fallback = region_data.get(lang) or region_data.get("en", "No alerts right now. Stay aware and consult regional sources.")
            translated = translate_text(fallback, lang)
            result = {
                "reply": translated,
                "plan": plan,
                "alerts": []
            }
            RESPONSE_CACHE[cache_key] = result
            return result

    threat_scores = [assess_threat_level(alert) for alert in raw_alerts]
    summaries = summarize_alerts(raw_alerts)
    print("Summaries generated")

    translated_summaries = [translate_text(summary, lang) for summary in summaries]
    print(f"Summaries translated to {lang}")

    results = []
    for i, alert in enumerate(raw_alerts):
        results.append({
            "title": alert.get("title", ""),
            "summary": alert.get("summary", ""),
            "link": alert.get("link", ""),
            "source": alert.get("source", ""),
            "type": translate_text(alert.get("type", ""), lang),
            "level": threat_scores[i],
            "gpt_summary": translated_summaries[i]
        })

    fallback = generate_advice(query, raw_alerts)
    translated_fallback = translate_text(fallback, lang)
    print("Fallback advice generated and translated")

    result = {
        "reply": translated_fallback,
        "plan": plan,
        "alerts": results
    }
    RESPONSE_CACHE[cache_key] = result
    return result