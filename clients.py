import json

def get_all_client_emails():
    with open("clients.json", "r") as f:
        return json.load(f)
