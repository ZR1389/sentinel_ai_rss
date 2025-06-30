import os
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Load API key from .env
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def assess_threat_level(alert_text):
    prompt = f"""
You are a professional security analyst. Assess the threat level of this alert:

"{alert_text}"

Respond with one of the following ONLY:
Low, Moderate, High, or Critical.
"""
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )
    return response.choices[0].message.content.strip()

# Test the function
if __name__ == "__main__":
    sample_alert = "Curfew declared in Burkina Faso after insurgent attack"
    level = assess_threat_level(sample_alert)
    print(f"Threat Level: {level}")
