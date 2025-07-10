import json

CLIENTS_FILE = "clients.json"

def get_all_client_emails():
    """Return a list of all client emails (lowercase) from the clients JSON file."""
    with open(CLIENTS_FILE, "r") as f:
        clients = json.load(f)
    return [client["email"].lower() for client in clients if "email" in client and isinstance(client["email"], str)]

def get_plan(email):
    """Return the plan (as uppercase string) for the given email, or 'FREE' if not found."""
    with open(CLIENTS_FILE, "r") as f:
        clients = json.load(f)
    for client in clients:
        if isinstance(client.get("email"), str) and client["email"].lower() == email.lower():
            return client.get("plan", "FREE").upper()
    return "FREE"