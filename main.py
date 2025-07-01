import os
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from dotenv import load_dotenv
from chat_handler import handle_user_query
from email_dispatcher import send_pdf_report
from telegram_dispatcher import send_alerts_to_telegram  # ✅ New import

# ✅ Load .env variables
load_dotenv()

class ChatRequestHandler(BaseHTTPRequestHandler):
    def _set_headers(self):
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        data = json.loads(body)

        if self.path == "/chat":
            message = data.get("message", "")
            email = data.get("email", "anonymous")
            lang = data.get("lang", "en")

            result = handle_user_query(message, email=email, lang=lang)
            self._set_headers()
            self.wfile.write(json.dumps(result).encode("utf-8"))

        elif self.path == "/request_report":
            email = data.get("email", "")
            plan = result = None
            try:
                result = handle_user_query("status", email=email)
                plan = result.get("plan", "FREE")
            except:
                plan = "FREE"

            if plan not in ["PRO", "VIP"]:
                msg = "🚫 PDF reports are available for PRO and VIP users only."
            else:
                try:
                    send_pdf_report(email=email, plan=plan)
                    msg = f"📄 Your {plan} report was sent to {email}."
                except Exception as e:
                    msg = f"❌ Failed to send report. Reason: {str(e)}"

            self._set_headers()
            self.wfile.write(json.dumps({"message": msg}).encode("utf-8"))

        elif self.path == "/send_telegram_alerts":
            email = data.get("email", "anonymous")
            count = send_alerts_to_telegram(email=email)
            if count > 0:
                msg = f"✅ {count} alerts sent to Telegram."
            else:
                msg = "⚠️ No high-risk alerts to send right now."
            self._set_headers()
            self.wfile.write(json.dumps({"message": msg}).encode("utf-8"))

def run():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), ChatRequestHandler)
    print(f"🚀 Sentinel AI server running on port {port}")
    server.serve_forever()

if __name__ == "__main__":
    run()
