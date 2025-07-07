import os
from mistralai.client import MistralClient
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor
from threat_scorer import assess_threat_level

load_dotenv()
client = MistralClient(api_key=os.getenv("MISTRAL_API_KEY"))

# Configurable parameters
SUMMARY_LIMIT = 5  # Max number of alerts to summarize
MISTRAL_MODEL = "mistral-small-3.2"  # Use the appropriate Mistral model name
TEMPERATURE = 0.4

def summarize_single_alert(alert):
    """
    Summarize a single alert using Mistral LLM.
    """
    try:
        title = alert.get("title", "")
        summary = alert.get("summary", "")
        title = str(title) if not isinstance(title, str) else title
        summary = str(summary) if not isinstance(summary, str) else summary
        full_text = f"{title}\n{summary}".strip()

        response = client.chat(
            model=MISTRAL_MODEL,
            messages=[
                {"role": "system", "content": "Summarize this security alert in one concise sentence."},
                {"role": "user", "content": full_text}
            ],
            temperature=TEMPERATURE,
            max_tokens=80
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"❌ Summary error: {e}")
        return "⚠️ Failed to generate summary"

def summarize_alerts(alerts):
    """
    Summarize a list of alerts with the Mistral LLM (up to SUMMARY_LIMIT).
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