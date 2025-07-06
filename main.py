import json
import os
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from chat_handler import handle_user_query
from email_dispatcher import generate_translated_pdf
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
        lang = data.get("lang", "en")
        region = data.get("region", "All")
        threat_type = data.get("type", "All")
        plan = data.get("plan", "Free")

        print(f"Processing chat: plan={plan}, region={region}, type={threat_type}")
        region = str(region) if not isinstance(region, str) else region
        threat_type = str(threat_type) if not isinstance(threat_type, str) else threat_type
        plan = str(plan).capitalize()
        lang = str(lang)

        result = handle_user_query(
            {"query": query},
            email=email,
            lang=lang,
            region=region,
            threat_type=threat_type,
            plan=plan
        )

        return _build_cors_response(jsonify(result))

    except Exception as e:
        print(f"Error in /chat handler: {e}")
        return _build_cors_response(jsonify({
            "reply": f"Advisory engine error: {str(e)}",
            "plan": "Unknown",
            "alerts": []
        })), 500

@app.route("/request_report", methods=["POST"])
def request_report():
    try:
        data = request.get_json(force=True)
        email = data.get("email", "anonymous")
        lang = data.get("lang", "en")
        region = data.get("region", "All")
        threat_type = data.get("type", "All")
        plan = data.get("plan", "Free").capitalize()

        print(f"📄 Generating report for {email} | Region={region}, Type={threat_type}, Lang={lang}, Plan={plan}")
        alerts = handle_user_query(
            {"query": "Generate my report"},
            email=email,
            lang=lang,
            region=region,
            threat_type=threat_type,
            plan=plan
        ).get("alerts", [])

        generate_translated_pdf(email, alerts, plan, lang)

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
    # Only run this for local dev testing
    # app.run(host="0.0.0.0", port=PORT)
