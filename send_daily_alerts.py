from email_dispatcher import send_pdf_report
from dotenv import load_dotenv
from plan_rules import PLAN_RULES
import json

load_dotenv()

def send_daily_summaries():
    with open("clients.json", "r") as f:
        clients = json.load(f)

    for client in clients:
        email = client["email"]
        plan = client.get("plan", "FREE")
        if PLAN_RULES.get(plan, {}).get("pdf") in ["Monthly", "On-request"]:
            try:
                send_pdf_report(email=email, plan=plan)
                print(f"✅ Sent daily PDF to {email} ({plan})")
            except Exception as e:
                print(f"❌ Error for {email}: {str(e)}")
        else:
            print(f"⏭️ Skipping {email} — PDF not allowed for {plan}")

if __name__ == "__main__":
    print("📬 Sending scheduled daily PDF summaries...")
    send_daily_summaries()
