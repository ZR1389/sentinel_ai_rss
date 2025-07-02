import os
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# 🔒 Optional: High-impact keywords to auto-score "Critical" alerts instantly
CRITICAL_KEYWORDS = [
    "assassination", "suicide bombing", "mass shooting", "IED", "terrorist attack",
    "hijacking", "hostage situation", "military raid"
]

# ✅ Normalize GPT response
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

# 🧠 GPT-Based Threat Level Assessment
def assess_threat_level(alert_text):
    # ✅ Pre-check: Auto-score based on known critical terms
    for keyword in CRITICAL_KEYWORDS:
        if keyword.lower() in alert_text.lower():
            return "Critical"

    # 🧠 GPT logic
    system_prompt = """
You are a senior risk analyst for a global threat monitoring system.
Your job is to assign a risk score to security-related alerts or incidents.

You must classify the alert using ONLY one of the following:
Low, Moderate, High, or Critical.

Use these guidelines:
- Critical: catastrophic impact or immediate danger to life/safety/national security
- High: serious and urgent threat requiring immediate action or avoidance
- Moderate: concerning but not life-threatening
- Low: informational, minimal risk

Do not explain. Respond with only the label.
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": alert_text}
            ],
            temperature=0
        )
        label = response.choices[0].message.content
        return normalize_threat_label(label)
    except Exception as e:
        print(f"❌ Threat scoring error: {e}")
        return "Unrated"

# ✅ Test it
if __name__ == "__main__":
    sample = "Assassination attempt on diplomat in Baghdad"
    level = assess_threat_level(sample)
    print(f"Threat Level: {level}")
