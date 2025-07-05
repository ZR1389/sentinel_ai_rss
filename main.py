# main.py ✅ WORKING TELEGRAM PLAN CHECK VIA GPT

import os
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from dotenv import load_dotenv
from chat_handler import handle_user_query
from email_dispatcher import send_pdf_report, send_daily_summaries
from telegram_dispatcher import send_alerts_to_telegram
from plan_rules import PLAN_RULES

load_dotenv()

TOKEN_TO_PLAN = {
    os.getenv("FREE_TOKEN"): "FREE",
    os.getenv("BASIC_TOKEN"): "BASIC",
    os.getenv("PRO_TOKEN"): "PRO",
    os.getenv("VIP_TOKEN"): "VIP"
}

print("🛡️ Loaded TOKEN_TO_PLAN map:", TOKEN_TO_PLAN)

class ChatRequestHandler(BaseHTTPRequestHandler):
    def _set_headers(self, code=200):
        self.send_response(code)
        self.send_header("Content-type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        data = json.loads(body)

        if self.path == "/chat":
            print("📩 Incoming /chat request...")
            auth_token = self.headers.get("Authorization")
            if not auth_token:
                print("❌ Missing token")
                self.send_response(401)
                self.end_headers()
                self.wfile.write(b'{"error": "Missing Authorization token"}')
                return

            user_plan = TOKEN_TO_PLAN.get(auth_token)
            if not user_plan:
                print("❌ Invalid token")
                self.send_response(403)
                self.end_headers()
                self.wfile.write(b'{"error": "Invalid or unauthorized token"}')
                return

            try:
                message = data.get("message", "")
                email = data.get("email", "anonymous")
                lang = data.get("lang", "en")
                region = data.get("region", None)
                threat_type = data.get("threat_type", None)

                print(f"🧠 Processing chat: plan={user_plan}, region={region}, type={threat_type}")

                result = handle_user_query(
                    message,
                    email=email,
                    lang=lang,
                    region=region,
                    threat_type=threat_type,
                    plan=user_plan
                )

                self._set_headers()
                self.wfile.write(json.dumps(result).encode("utf-8"))

            except Exception as e:
                print("💥 Error in /chat handler:", str(e))
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))

        elif self.path == "/request_report":
            email = data.get("email", "")
            lang = data.get("lang", "en")
            plan = result = None
            try:
                result = handle_user_query("status", email=email)
                plan = result.get("plan", "FREE")
            except:
                plan = "FREE"

            allowed_pdf = PLAN_RULES.get(plan, {}).get("pdf", False)

            if allowed_pdf in ["Monthly", "On-request", True]:
                try:
                    send_pdf_report(email=email, plan=plan, language=lang)
                    msg = f"Your {plan} report was sent to {email}."
                except Exception as e:
                    msg = f"Failed to send report. Reason: {str(e)}"
            elif plan == "BASIC":
                msg = "BASIC users can view alerts and summaries, but PDF reports are only available in PRO and VIP plans."
            else:
                msg = "PDF reports are available for PRO and VIP users only. Upgrade to access full features."

            self._set_headers()
            self.wfile.write(json.dumps({"message": msg}).encode("utf-8"))

        elif self.path == "/send_telegram_alerts":
            email = data.get("email", "anonymous")
            plan = "FREE"
            try:
                result = handle_user_query("status", email=email)
                plan = result.get("plan", "FREE").upper()
            except:
                plan = "FREE"

            if plan not in ["BASIC", "PRO", "VIP"]:
                self._set_headers(403)
                self.wfile.write(json.dumps({
                    "message": "Telegram alerts are only available for Basic, Pro, and VIP users."
                }).encode("utf-8"))
                return

            count = send_alerts_to_telegram(email=email)
            msg = f"{count} alerts sent to Telegram." if count > 0 else "No high-risk alerts to send right now."
            self._set_headers()
            self.wfile.write(json.dumps({"message": msg}).encode("utf-8"))

        elif self.path == "/subscribe_push":
            subscription = data.get("subscription")
            if subscription:
                try:
                    with open("subscribers.json", "r+") as f:
                        try:
                            subscribers = json.load(f)
                        except json.JSONDecodeError:
                            subscribers = []
                        if subscription not in subscribers:
                            subscribers.append(subscription)
                            f.seek(0)
                            json.dump(subscribers, f, indent=2)
                            f.truncate()
                    msg = "Push subscription saved."
                except Exception as e:
                    msg = f"Failed to save subscription: {str(e)}"
            else:
                msg = "No subscription received."

            self._set_headers()
            self.wfile.write(json.dumps({"message": msg}).encode("utf-8"))

def run_server():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), ChatRequestHandler)
    print(f"Sentinel AI server running on port {port}")
    server.serve_forever()

if __name__ == "__main__":
    if os.getenv("RUN_MODE") == "daily":
        print("Sending daily reports...")
        send_daily_summaries()
    else:
        run_server()
