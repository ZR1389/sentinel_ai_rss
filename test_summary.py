from rss_processor import get_clean_alerts

# ✅ Live test with GPT summaries ON
alerts = get_clean_alerts(limit=5, summarize=True)

for i, alert in enumerate(alerts, 1):
    print(f"\n[{i}] {alert['title']}")
    print(f"📍 Source: {alert['source']}")
    print(f"🧾 Summary: {alert['summary']}")
    if alert['gpt_summary']:
        print(f"🤖 GPT Summary: {alert['gpt_summary']}")
    print(f"🔗 Link: {alert['link']}")

