# ✅ threat_engine.py — handles raw alerts, scoring, grouping (no GPT)

import json
from rss_processor import get_clean_alerts
from threat_scorer import assess_threat_level

# ✅ Load client plans
def load_clients():
    with open("clients.json") as f:
        return json.load(f)

CLIENTS = load_clients()

# ✅ Plan lookup
def get_plan(email):
    for c in CLIENTS:
        if c["email"].lower() == email.lower():
            return c["plan"].upper()
    return "FREE"

# ✅ Filters
THREAT_FILTERS = {
    "VIP": None,
    "PRO": {"Kidnapping", "Cyber", "Terrorism", "Protest", "Crime"},
    "FREE": {"Protest", "Crime"}
}

# ✅ Alert filter/score/group

def get_structured_alerts(plan, keyword=None):
    raw_alerts = get_clean_alerts(limit=10)
    allowed_types = THREAT_FILTERS.get(plan)
    grouped = {}
    flat_list = []

    for alert in raw_alerts:
        alert["level"] = assess_threat_level(alert)
        alert_type = alert.get("type", "Unclassified")
        alert["type"] = alert_type

        if allowed_types is None or alert_type in allowed_types:
            if keyword:
                if keyword.lower() not in alert["title"].lower() and keyword.lower() not in alert["summary"].lower():
                    continue

            grouped.setdefault(alert_type, []).append(alert)
            flat_list.append(alert)

    return grouped, flat_list
