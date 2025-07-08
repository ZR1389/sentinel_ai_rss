import os
from dotenv import load_dotenv
from mistralai.client import Client
from mistralai.models.chat_completion import ChatMessage

load_dotenv()
client = Client(api_key=os.getenv("MISTRAL_API_KEY"))

# High-priority keywords to instantly flag Critical threats
CRITICAL_KEYWORDS = [
    "assassination", "suicide bombing", "mass shooting", "IED",
    "terrorist attack", "hijacking", "hostage situation", "military raid"
]

MISTRAL_THREAT_MODEL = os.getenv("MISTRAL_THREAT_MODEL", "mistral-small-3.2")

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

    try:
        response = client.chat(
            model=MISTRAL_THREAT_MODEL,
            messages=[
                ChatMessage(role="system", content=system_prompt),
                ChatMessage(role="user", content=alert_text)
            ],
            temperature=0,
            max_tokens=8
        )
        label = response.choices[0].message.content
        return normalize_threat_label(label)
    except Exception as e:
        print(f"❌ Threat scoring error: {e}")
        return "Unrated"

# Test run
if __name__ == "__main__":
    test = "Gunfire reported near embassy with possible hostage situation."
    print("Threat Level:", assess_threat_level(test))