from email_dispatcher import send_pdf_report
from dotenv import load_dotenv
import json

load_dotenv()

def send_daily_summaries():
    try:
        with open("clients.json", "r") as f:
            clients = json.load(f)
    except Exception as e:
        print(f"❌ Failed to load clients.json: {e}")
        return

    for client in clients:
        email = client.get("email", "unknown")
        plan = client.get("plan", "FREE")
        region = client.get("region", None)
        result = send_pdf_report(email=email, plan=plan, region=region)
        status = result.get("status", "unknown")
        reason = result.get("reason", "")
        if status == "sent":
            print(f"✅ Sent daily PDF to {email} ({plan})")
        elif status == "skipped":
            print(f"⏩ Skipped {email} ({plan}) — {reason}")
        elif status == "error":
            print(f"❌ Error for {email} ({plan}): {reason}")
        else:
            print(f"❓ Unknown status for {email} ({plan}): {result}")

if __name__ == "__main__":
    print("📤 Sending scheduled daily PDF summaries...")
    send_daily_summaries()