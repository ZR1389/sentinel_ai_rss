import os
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor
from threat_scorer import assess_threat_level
from xai_client import grok_chat
from openai import OpenAI

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

SUMMARY_LIMIT = 5  # Max number of alerts to summarize
GROK_MODEL = os.getenv("GROK_MODEL", "grok-3-mini")
TEMPERATURE = 0.4

def summarize_single_alert(alert):
    """
    Summarize a single threat alert using Grok-3-mini, fallback to OpenAI.
    """
    title = alert.get("title", "")
    summary = alert.get("summary", "")
    title = str(title) if not isinstance(title, str) else title
    summary = str(summary) if not isinstance(summary, str) else summary
    full_text = f"{title}\n{summary}".strip()

    messages = [
        {"role": "system", "content": "Summarize this security threat alert in one concise sentence."},
        {"role": "user", "content": full_text}
    ]
    # 1. Grok-3-mini
    grok_summary = grok_chat(messages, max_tokens=80, temperature=TEMPERATURE)
    if grok_summary:
        return grok_summary
    # 2. OpenAI fallback
    if openai_client:
        try:
            response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages,
                temperature=TEMPERATURE,
                max_tokens=80
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"[OpenAI fallback error] {e}")
    return "⚠️ Failed to generate summary"

def summarize_alerts(alerts):
    """
    Summarize a list of threat alerts with the Grok LLM (up to SUMMARY_LIMIT).
    Adds 'gpt_summary' to each alert.
    """
    summarized = []
    to_summarize = alerts[:SUMMARY_LIMIT]

    if not to_summarize:
        return []

    with ThreadPoolExecutor(max_workers=min(5, len(to_summarize))) as executor:
        summaries = list(executor.map(summarize_single_alert, to_summarize))

    for i, alert in enumerate(to_summarize):
        alert_copy = alert.copy()
        alert_copy["gpt_summary"] = summaries[i]
        summarized.append(alert_copy)

    for alert in alerts[SUMMARY_LIMIT:]:
        alert_copy = alert.copy()
        alert_copy["gpt_summary"] = f"Summary not generated (limit {SUMMARY_LIMIT} reached)"
        summarized.append(alert_copy)

    return summarized