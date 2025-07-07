import os
from openai import OpenAI
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor
from threat_scorer import assess_threat_level

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=15)  # Set timeout here

SUMMARY_LIMIT = 5  # Limit number of alerts to summarize per request

# Translate using OpenAI
def translate_text(text, target_lang="en"):
    if not text or not (isinstance(target_lang, str) and target_lang.lower() != "en"):
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
        print(f"Translation error: {e}")
        return text  # Fail-safe: return original if translation fails

def summarize_single_alert(alert, lang="en"):
    # Helper for parallelization
    try:
        title = alert.get('title', '')
        summary = alert.get('summary', '')
        if not isinstance(title, str):
            title = str(title)
        if not isinstance(summary, str):
            summary = str(summary)
        full_text = f"{title}\n{summary}"
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
        return translated
    except Exception as e:
        print(f"Summary error: {e}")
        return None

def summarize_alerts(alerts, lang="en"):
    summarized = []
    # Only summarize up to SUMMARY_LIMIT alerts in parallel
    alerts_to_summarize = alerts[:SUMMARY_LIMIT]

    with ThreadPoolExecutor(max_workers=5) as executor:
        summaries = list(executor.map(lambda alert: summarize_single_alert(alert, lang), alerts_to_summarize))

    for i, alert in enumerate(alerts_to_summarize):
        alert_copy = alert.copy()
        alert_copy["gpt_summary"] = summaries[i]
        summarized.append(alert_copy)

    # For the rest, just copy with a placeholder summary
    for alert in alerts[SUMMARY_LIMIT:]:
        alert_copy = alert.copy()
        alert_copy["gpt_summary"] = f"Summary not generated (limit {SUMMARY_LIMIT} reached)"
        summarized.append(alert_copy)

    return summarized