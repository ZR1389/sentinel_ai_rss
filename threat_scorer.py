import os
from dotenv import load_dotenv
from xai_client import grok_chat
from openai import OpenAI

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

CRITICAL_KEYWORDS = [
    "assassination", "suicide bombing", "mass shooting", "IED",
    "terrorist attack", "hijacking", "hostage situation", "military raid"
]

def normalize_threat_label(label):
    label = label.strip().lower()
    if "low" in label:
        return "Low"
    elif "moderate" in label:
        return "Moderate"
    elif "high" in label:
        return "High"
    elif "critical" in label:
        return "Critical"
    else:
        return "Unrated"

def assess_threat_level(alert_text):
    if not isinstance(alert_text, str):
        alert_text = str(alert_text)

    lowered = alert_text.lower()
    for keyword in CRITICAL_KEYWORDS:
        if keyword.lower() in lowered:
            return "Critical"

    system_prompt = (
        "You are a senior risk analyst for a global threat monitoring system. "
        "Classify this alert using ONLY one of the following labels: Low, Moderate, High, or Critical.\n\n"
        "Guidelines:\n"
        "- Critical: catastrophic impact or immediate danger to life/safety/national security\n"
        "- High: serious and urgent threat requiring immediate action or avoidance\n"
        "- Moderate: concerning but not life-threatening\n"
        "- Low: informational, minimal risk\n\n"
        "Only return the label, no explanation."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": alert_text},
    ]
    # 1. Grok-3-mini
    grok_label = grok_chat(messages, max_tokens=8, temperature=0)
    if grok_label:
        return normalize_threat_label(grok_label)
    # 2. OpenAI fallback
    if openai_client:
        try:
            response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages,
                temperature=0,
                max_tokens=8
            )
            label = response.choices[0].message.content
            return normalize_threat_label(label)
        except Exception as e:
            print(f"[OpenAI fallback error] {e}")
    return "Unrated"

if __name__ == "__main__":
    test = "Gunfire reported near embassy with possible hostage situation."
    print("Threat Level:", assess_threat_level(test))