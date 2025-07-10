import json
from plan_rules import PLAN_RULES

def get_plan(email):
    """
    Returns the user's plan as an uppercase string.
    Defaults to "FREE" if not found or error.
    """
    try:
        with open("clients.json") as f:
            clients = json.load(f)
            for client in clients:
                if isinstance(client.get("email"), str) and client["email"].lower() == email.lower():
                    return client.get("plan", "FREE").upper()
    except Exception as e:
        print(f"[ERROR] Failed to load client plan: {e}")
    return "FREE"