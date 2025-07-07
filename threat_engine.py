import os
from openai import OpenAI
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor
from threat_scorer import assess_threat_level

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=15)

SUMMARY_LIMIT = 5  # Max number of alerts to summarize with GPT

# Summarize one alert using GPT
def summarize_single_alert(alert):
    try:
        title = alert.get("title", "")
        summary = alert.get("summary", "")
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
        return response.choices[0].message.content.strip()

    except Exception as e:
        print(f"❌ Summary error: {e}")
        return "⚠️ Failed to generate summary"

# Summarize list of alerts
def summarize_alerts(alerts):
    summarized = []
    to_summarize = alerts[:SUMMARY_LIMIT]

    with ThreadPoolExecutor(max_workers=5) as executor:
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
