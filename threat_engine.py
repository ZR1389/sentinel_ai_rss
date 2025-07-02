from rss_processor import get_clean_alerts

# Allowed types per plan
THREAT_FILTERS = {
    "VIP": None,
    "PRO": {"Kidnapping", "Cyber", "Terrorism", "Protest", "Crime"},
    "FREE": {"Protest", "Crime"}
}

# Returns grouped and flat alerts based on plan and optional query
def get_structured_alerts(plan="FREE", query=None):
    alerts = get_clean_alerts(limit=10)

    allowed_types = THREAT_FILTERS.get(plan)
    filtered_alerts = []

    for alert in alerts:
        alert_type = alert.get("type", "Unclassified")
        alert["type"] = alert_type
        alert["level"] = "Moderate"  # 🛑 TEMP: Disable GPT scoring for speed

        if allowed_types is None or alert_type in allowed_types:
            if query:
                if query.lower() in alert["title"].lower() or query.lower() in alert["summary"].lower():
                    filtered_alerts.append(alert)
            else:
                filtered_alerts.append(alert)

    # Group by type
    grouped = {}
    for alert in filtered_alerts:
        grouped.setdefault(alert["type"], []).append(alert)

    return grouped, filtered_alerts
