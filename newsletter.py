import requests
import os
from dotenv import load_dotenv

load_dotenv()

BREVO_API_KEY = os.getenv("BREVO_API_KEY")
NEWSLETTER_LIST_ID = int(os.getenv("NEWSLETTER_LIST_ID", 3))

def subscribe_to_newsletter(email):
    """
    Subscribes the given email to your Brevo newsletter list.
    Returns True if successful, False otherwise.
    """
    if not BREVO_API_KEY:
        print("❌ BREVO_API_KEY environment variable not set")
        return False

    url = "https://api.brevo.com/v3/contacts"
    headers = {
        "accept": "application/json",
        "api-key": BREVO_API_KEY,
        "content-type": "application/json"
    }
    payload = {
        "email": email,
        "listIds": [NEWSLETTER_LIST_ID],
        "updateEnabled": True
    }
    r = requests.post(url, headers=headers, json=payload)
    if r.status_code in [201, 204]:
        print(f"✅ {email} subscribed to newsletter.")
        return True
    else:
        print(f"❌ Newsletter subscription failed ({r.status_code}): {r.text}")
        return False