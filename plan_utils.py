import json

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


def get_plan(email):
    try:
        with open("clients.json") as f:
            clients = json.load(f)
            for client in clients:
                if isinstance(client.get("email"), str) and client["email"].lower() == email.lower():
                    return client.get("plan", "FREE").upper()
    except Exception as e:
        print(f"[ERROR] Failed to load client plan: {e}")
    return "FREE"
