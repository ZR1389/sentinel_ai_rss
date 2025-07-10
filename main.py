import json
import os
import logging
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from werkzeug.exceptions import BadRequest, MethodNotAllowed, UnsupportedMediaType
from chat_handler import handle_user_query
from email_dispatcher import generate_pdf  # ✅ Renamed version without translation
from flask_cors import CORS

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

TOKEN_TO_PLAN = {
    "sentinel_free_2025": "FREE",
    "sentinel_basic_2025": "BASIC",
    "sentinel_pro_2025": "PRO",
    "sentinel_vip_2025": "VIP"
}

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
        log.info("Incoming /chat request...")

        query = data.get("query", "")
        email = data.get("email", "anonymous")
        region = data.get("region")
        threat_type = data.get("type")
        plan = str(data.get("plan", "Free")).upper()

        region = None if not region or str(region).lower() == "all" else str(region)
        threat_type = None if not threat_type or str(threat_type).lower() == "all" else str(threat_type)

        log.info(f"Processing chat: plan={plan}, region={region}, type={threat_type}")

        result = handle_user_query(
            {"query": query},
            email=email,
            region=region,
            threat_type=threat_type,
            plan=plan
        )

        return _build_cors_response(jsonify(result))

    except BadRequest as e:
        log.error(f"Bad request: {e}")
        return _build_cors_response(jsonify({"error": "Malformed input"})), 400
    except MethodNotAllowed as e:
        log.error(f"Method not allowed: {e}")
        return _build_cors_response(jsonify({"error": "Method not allowed"})), 405
    except UnsupportedMediaType as e:
        log.error(f"Unsupported media type: {e}")
        return _build_cors_response(jsonify({"error": "Unsupported media type"})), 415
    except Exception as e:
        log.error(f"Unhandled error in /chat handler: {e}")
        return _build_cors_response(jsonify({
            "error": "Internal server error"
        })), 500

@app.route("/request_report", methods=["POST"])
def request_report():
    try:
        data = request.get_json(force=True)
        email = data.get("email", "anonymous")
        region = data.get("region")
        threat_type = data.get("type")
        plan = str(data.get("plan", "Free")).upper()

        region = None if not region or str(region).lower() == "all" else str(region)
        threat_type = None if not threat_type or str(threat_type).lower() == "all" else str(threat_type)

        log.info(f"📄 Generating report for {email} | Region={region}, Type={threat_type}, Plan={plan}")
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

    except BadRequest as e:
        log.error(f"Bad request: {e}")
        return _build_cors_response(jsonify({"error": "Malformed input"})), 400
    except MethodNotAllowed as e:
        log.error(f"Method not allowed: {e}")
        return _build_cors_response(jsonify({"error": "Method not allowed"})), 405
    except UnsupportedMediaType as e:
        log.error(f"Unsupported media type: {e}")
        return _build_cors_response(jsonify({"error": "Unsupported media type"})), 415
    except Exception as e:
        log.error(f"💥 Unhandled error in report generation: {e}")
        return _build_cors_response(jsonify({"error": "Internal server error"})), 500

@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "ok", "version": "1.0", "plan_map": TOKEN_TO_PLAN}), 200

@app.errorhandler(404)
def not_found_error(error):
    log.warning(f"404 Not Found: {error}")
    return _build_cors_response(jsonify({"error": "Not found"})), 404

@app.errorhandler(405)
def method_not_allowed_error(error):
    log.warning(f"405 Method Not Allowed: {error}")
    return _build_cors_response(jsonify({"error": "Method not allowed"})), 405

@app.errorhandler(500)
def internal_error(error):
    log.error(f"500 Internal Server Error: {error}")
    return _build_cors_response(jsonify({"error": "Internal server error"})), 500

def _build_cors_response(response=None):
    headers = {
        "Access-Control-Allow-Origin": "https://zikarisk.com",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type"
    }
    if response is None:
        response = jsonify({})
    response.headers.update(headers)
    return response

if __name__ == "__main__":
    log.info(f"Loaded TOKEN_TO_PLAN map: {TOKEN_TO_PLAN}")
    log.info(f"Sentinel AI server running on port {PORT}")
    if os.getenv("ENV") != "production":
        app.run(host="0.0.0.0", port=PORT)