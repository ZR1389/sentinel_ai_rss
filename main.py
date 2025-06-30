import os
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from dotenv import load_dotenv
from chat_handler import generate_threat_summary, get_plan_for_email
from email_dispatcher import send_daily_summaries  # ✅ current function

# ✅ Load .env variables
load_dotenv()

class ChatRequestHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))

        if self.path == "/chat":
            message = body.get("message", "")
            lang = body.get("lang", "en")
            email = body.get("email", "")

            plan = get_plan_for_email(email)
            summary = generate_threat_summary(message, user_plan=plan)

            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "reply": summary,
                "plan": plan
            }).encode("utf-8"))

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

            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "message": message
            }).encode("utf-8"))

def run():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), ChatRequestHandler)
    print(f"🚀 Sentinel AI server running on port {port}")
    server.serve_forever()

if __name__ == "__main__":
    run()

