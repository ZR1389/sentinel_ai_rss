from email_dispatcher import send_pdf_report
from dotenv import load_dotenv
from plan_rules import PLAN_RULES
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
        plan = client.get("plan", "FREE").upper()

        if PLAN_RULES.get(plan, {}).get("pdf", False):
            try:
                send_pdf_report(email=email, plan=plan)
                print(f"✅ Sent daily PDF to {email} ({plan})")
            except Exception as e:
                print(f"❌ Error for {email}: {e}")
        else:
            print(f"⏩ Skipped {email} — No PDF access for {plan}")

if __name__ == "__main__":
    print("📤 Sending scheduled daily PDF summaries...")
    send_daily_summaries()
