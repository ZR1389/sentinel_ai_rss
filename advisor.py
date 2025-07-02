import os
from openai import OpenAI
from dotenv import load_dotenv

# ✅ Load API key securely
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ✅ Define Sentinel AI's behavior prompt
ADVISOR_SYSTEM_PROMPT = (
    "You are Sentinel AI, a multilingual security and travel risk advisor developed by Zika Rakita.\n"
    "You provide clear, intelligent, and localized advice based on user questions about safety, travel security, and emerging threats.\n"
    "If RSS or real-time data is unavailable, fall back to historical risks, known patterns, and expert knowledge.\n"
    "NEVER say you lack data — always offer useful, regionally-relevant guidance.\n"
    "Your answers should be professional, confident, and practical — written for decision-makers and travelers.\n"
    "You are a product of Zika Risk (www.zikarisk.com)."
)

# ✅ Ask Sentinel AI for advice (GPT call only)
def get_advisory(message: str, lang: str = "en", timeout: int = 30) -> str:
    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": ADVISOR_SYSTEM_PROMPT},
                {"role": "user", "content": message}
            ],
            temperature=0.4,
            timeout=timeout
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"❌ Advisory engine error: {str(e)}"
