import json

def get_all_client_emails():
    with open("clients.json", "r") as f:
        return json.load(f)
import json

CLIENTS_FILE = "clients.json"

def get_plan(email):
    with open(CLIENTS_FILE, "r") as f:
        clients = json.load(f)
    for client in clients:
        if client["email"].lower() == email.lower():
            return client.get("plan", "Free")
    return "Free"
