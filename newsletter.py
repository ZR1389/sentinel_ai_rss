import requests
import os
from dotenv import load_dotenv
from plan_utils import require_plan_feature
from security_log_utils import log_security_event

load_dotenv()

BREVO_API_KEY = os.getenv("BREVO_API_KEY")
NEWSLETTER_LIST_ID = int(os.getenv("NEWSLETTER_LIST_ID", 3))

def subscribe_to_newsletter(email):
    """
    Subscribes the given email to your Brevo newsletter list.
    Returns True if successful, False otherwise.
    Backend plan gating: only users with newsletter feature can subscribe.
    Security logging added for all relevant events.
    """
    # --- ENFORCE PLAN GATING FOR NEWSLETTER FEATURE ---
    if not require_plan_feature(email, "newsletter"):
        log_security_event(
            event_type="newsletter_plan_denied",
            email=email,
            details="Feature gated: newsletter not enabled for plan"
        )
        print(f"❌ User {email} not allowed to subscribe to newsletter (feature gated).")
        return False

    if not BREVO_API_KEY:
        log_security_event(
            event_type="newsletter_api_key_missing",
            email=email,
            details="BREVO_API_KEY environment variable not set"
        )
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
        log_security_event(
            event_type="newsletter_subscribed",
            email=email,
            details=f"Subscribed successfully (status {r.status_code})"
        )
        print(f"✅ {email} subscribed to newsletter.")
        return True
    else:
        log_security_event(
            event_type="newsletter_subscribe_failed",
            email=email,
            details=f"Failed ({r.status_code}): {r.text}"
        )
        print(f"❌ Newsletter subscription failed ({r.status_code}): {r.text}")
        return False