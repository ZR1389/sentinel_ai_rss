import os
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from dotenv import load_dotenv
from chat_handler import generate_threat_summary, get_plan_for_email
from email_dispatcher import send_pdf_report

# ✅ Load .env variables
load_dotenv()

# ✅ Track usage per email (simple in-memory store)
email_usage = {}

MAX_FREE_MESSAGES = 3  # Free users can send 3 messages total

class ChatRequestHandler(BaseHTTPRequestHandler):
    # ✅ Handle browser CORS preflight
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))

        # Common headers
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        if self.path == "/chat":
            message = body.get("message", "")
            lang = body.get("lang", "en")
            email = body.get("email", "")

            plan = get_plan_for_email(email)

            # Track usage if user is FREE
            if plan.upper() == "FREE":
                usage = email_usage.get(email, 0)
                if usage >= MAX_FREE_MESSAGES:
                    response = {
                        "reply": "🚫 You've reached the 3-message limit. Please upgrade.",
                        "plan": plan
                    }
                    self.wfile.write(json.dumps(response).encode("utf-8"))
                    return
                else:
                    email_usage[email] = usage + 1

            summary = generate_threat_summary(message, user_plan=plan)
            response = {
                "reply": summary,
                "plan": plan
            }
            self.wfile.write(json.dumps(response).encode("utf-8"))

        elif self.path == "/request_report":
            email = body.get("email", "")
            plan = get_plan_for_email(email)

            if plan not in ["PRO", "VIP"]:
                message = "🚫 PDF reports are available for PRO and VIP users only."
            else:
                try:
                    send_pdf_report(email=email, plan=plan)
                    message = f"📄 Your {plan} report was sent to {email}."
                except Exception as e:
                    message = f"❌ Failed to send report. Reason: {str(e)}"

            response = {
                "message": message
            }
            self.wfile.write(json.dumps(response).encode("utf-8"))

def run():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), ChatRequestHandler)
    print(f"🚀 Sentinel AI server running on port {port}")
    server.serve_forever()

if __name__ == "__main__":
    run()


