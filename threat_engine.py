from rss_processor import get_clean_alerts

# ✅ Allowed types per subscription tier
THREAT_FILTERS = {
    "VIP": None,  # Full access
    "PRO": {"Kidnapping", "Cyber", "Terrorism", "Protest", "Crime"},
    "FREE": {"Protest", "Crime"}
}

# ✅ Return alerts (grouped by type + flat list), filtered by plan and optional search query
def get_structured_alerts(plan="FREE", query=None):
    alerts = get_clean_alerts(limit=10)

    allowed_types = THREAT_FILTERS.get(plan.upper())
    filtered_alerts = []

    for alert in alerts:
        alert_type = alert.get("type", "Unclassified")
        alert["type"] = alert_type
        alert["level"] = "Moderate"  # 🛑 TEMP: Disable GPT scoring for speed

        # 🧠 Filter by access level and optional search query
        if allowed_types is None or alert_type in allowed_types:
            if query:
                if query.lower() in alert["title"].lower() or query.lower() in alert["summary"].lower():
                    filtered_alerts.append(alert)
            else:
                filtered_alerts.append(alert)

    # 📦 Group alerts by type
    grouped = {}
    for alert in filtered_alerts:
        grouped.setdefault(alert["type"], []).append(alert)

    return grouped, filtered_alerts
