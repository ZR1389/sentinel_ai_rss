import json
import os
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from chat_handler import handle_user_query
from email_dispatcher import generate_pdf  # ✅ Renamed version without translation
from flask_cors import CORS

# Flask app
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "https://zikarisk.com"}}, allow_headers=["Authorization", "Content-Type"])

load_dotenv()
PORT = int(os.getenv("PORT", 8080))

@app.route("/chat", methods=["POST", "OPTIONS"])
def chat():
    if request.method == "OPTIONS":
        return _build_cors_response()

    try:
        data = request.get_json(force=True)
        print("Incoming /chat request...")

        query = data.get("query", "")
        email = data.get("email", "anonymous")
        region = str(data.get("region", "All"))
        threat_type = str(data.get("type", "All"))
        plan = str(data.get("plan", "Free")).capitalize()

        print(f"Processing chat: plan={plan}, region={region}, type={threat_type}")

        result = handle_user_query(
            {"query": query},
            email=email,
            region=region,
            threat_type=threat_type,
            plan=plan
        )

        return _build_cors_response(jsonify(result))

    except Exception as e:
        print(f"Error in /chat handler: {e}")
        return _build_cors_response(jsonify({
            "reply": f"❌ Advisory engine error: {str(e)}",
            "plan": "Unknown",
            "alerts": []
        })), 500

@app.route("/request_report", methods=["POST"])
def request_report():
    try:
        data = request.get_json(force=True)
        email = data.get("email", "anonymous")
        region = str(data.get("region", "All"))
        threat_type = str(data.get("type", "All"))
        plan = str(data.get("plan", "Free")).capitalize()

        print(f"📄 Generating report for {email} | Region={region}, Type={threat_type}, Plan={plan}")
        alerts = handle_user_query(
            {"query": "Generate my report"},
            email=email,
            region=region,
            threat_type=threat_type,
            plan=plan
        ).get("alerts", [])

        generate_pdf(email, alerts, plan)  # ✅ Simplified

        return _build_cors_response(jsonify({
            "status": "Report generated and sent",
            "alerts_included": len(alerts)
        }))

    except Exception as e:
        print(f"💥 Report generation error: {e}")
        return _build_cors_response(jsonify({
            "status": f"Failed to generate report: {str(e)}"
        })), 500

def _build_cors_response(response=None):
    headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type"
    }
    if response is None:
        response = jsonify({})
    response.headers.update(headers)
    return response

if __name__ == "__main__":
    print(f"Loaded TOKEN_TO_PLAN map: {{'sentinel_free_2025': 'FREE', 'sentinel_basic_2025': 'BASIC', 'sentinel_pro_2025': 'PRO', 'sentinel_vip_2025': 'VIP'}}")
    print(f"Sentinel AI server running on port {PORT}")
    # app.run(host="0.0.0.0", port=PORT)
