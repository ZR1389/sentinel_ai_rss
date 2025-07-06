import os
from openai import OpenAI
from dotenv import load_dotenv
from threat_scorer import assess_threat_level
import signal

load_dotenv()
client = OpenAI()

def timeout_handler(signum, frame):
    raise TimeoutError("OpenAI timed out")

# Translate using OpenAI
def translate_text(text, target_lang="en"):
    if not text or target_lang.lower() == "en":
        return text
    try:
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(15)
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": f"Translate the following summary to {target_lang}."},
                {"role": "user", "content": text}
            ],
            temperature=0.3
        )
        signal.alarm(0)
        return response.choices[0].message.content.strip()
    except Exception as e:
        signal.alarm(0)
        print(f"Translation error: {e}")
        return text  # Fail-safe: return original if translation fails

# GPT summary for alert + optional translation
def summarize_alerts(alerts, lang="en"):
    summarized = []
    for alert in alerts:
        try:
            full_text = f"{alert['title']}\n{alert['summary']}"
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(15)
            response = client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "Summarize this security alert in one concise sentence."},
                    {"role": "user", "content": full_text}
                ],
                temperature=0.5
            )
            signal.alarm(0)
            summary = response.choices[0].message.content.strip()
            translated = translate_text(summary, target_lang=lang)
            alert["gpt_summary"] = translated
        except Exception as e:
            signal.alarm(0)
            print(f"Summary error: {e}")
            alert["gpt_summary"] = None
        summarized.append(alert)
    return summarized