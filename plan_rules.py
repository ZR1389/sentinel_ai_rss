"""
Centralized plan rules for all product features.
Update here to change plan quotas or feature flags site-wide.
"""

PLAN_RULES = {
    "FREE": {
        # Chat/Advisor/Handler limits
        "chat_monthly": 3,
        "chat_per_session": 2,

        # RSS processor (travel alerts)
        "rss_monthly": 5,
        "rss_per_session": 2,

        # Threat engine
        "threat_monthly": 5,
        "threat_per_session": 2,

        # Feature flags
        "pdf": False,
        "priority": "Standard",
        "insights": False,
        "dark_web": False,
        "support": False
    },
    "BASIC": {
        "chat_monthly": 100,
        "chat_per_session": 5,
        "rss_monthly": 20,
        "rss_per_session": 5,
        "threat_monthly": 20,
        "threat_per_session": 5,
        "pdf": False,
        "priority": "Standard",
        "insights": "Monthly",
        "dark_web": False,
        "support": False
    },
    "PRO": {
        "chat_monthly": 500,
        "chat_per_session": 10,
        "rss_monthly": 50,
        "rss_per_session": 10,
        "threat_monthly": 50,
        "threat_per_session": 10,
        "pdf": "Monthly",
        "priority": "Fast",
        "insights": "Weekly",
        "dark_web": True,
        "support": False
    },
    "VIP": {
        "chat_monthly": float("inf"),
        "chat_per_session": float("inf"),
        "rss_monthly": float("inf"),
        "rss_per_session": float("inf"),
        "threat_monthly": float("inf"),
        "threat_per_session": float("inf"),
        "pdf": "On-request",
        "priority": "Fastest",
        "insights": "On-demand",
        "dark_web": True,
        "support": True
    }
}