import os
from openai import OpenAI
from dotenv import load_dotenv
from threat_scorer import assess_threat_level

load_dotenv()
client = OpenAI()

# Translate using OpenAI
def translate_text(text, target_lang="en"):
    if not text or target_lang.lower() == "en":
        return text
    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": f"Translate the following summary to {target_lang}."},
                {"role": "user", "content": text}
            ],
            temperature=0.3
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return text  # Fail-safe: return original if translation fails

# GPT summary for alert + optional translation
def summarize_alerts(alerts, lang="en"):
    summarized = []
    for alert in alerts:
        try:
            full_text = f"{alert['title']}\n{alert['summary']}"
            response = client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "Summarize this security alert in one concise sentence."},
                    {"role": "user", "content": full_text}
                ],
                temperature=0.5
            )
            summary = response.choices[0].message.content.strip()
            translated = translate_text(summary, target_lang=lang)
            alert["gpt_summary"] = translated
        except Exception:
            alert["gpt_summary"] = None
        summarized.append(alert)
    return summarized
