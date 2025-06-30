import os
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from dotenv import load_dotenv
from chat_handler import generate_threat_summary, get_plan_for_email

# ✅ Load .env variables
load_dotenv()

class ChatRequestHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/chat":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
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

def run():
    port = int(os.getenv("PORT", 8080))  # Railway auto-injects PORT
    server = HTTPServer(('', port), ChatRequestHandler)
    print(f"🚀 Sentinel AI /chat endpoint running on port {port}")
    server.serve_forever()

if __name__ == "__main__":
    run()
