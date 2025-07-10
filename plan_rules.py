PLAN_RULES = {
    "FREE": {
        "chat_limit": 3,
        "pdf": False,
        "priority": "Standard",
        "insights": False,
        "dark_web": False,
        "support": False
    },
    "BASIC": {
        "chat_limit": 100,
        "pdf": False,
        "priority": "Standard",
        "insights": "Monthly",
        "dark_web": False,
        "support": False
    },
    "PRO": {
        "chat_limit": 500,
        "pdf": "Monthly",
        "priority": "Fast",
        "insights": "Weekly",
        "dark_web": True,
        "support": False
    },
    "VIP": {
        "chat_limit": None,
        "pdf": "On-request",
        "priority": "Fastest",
        "insights": "On-demand",
        "dark_web": True,
        "support": True
    }
}