import os
import logging
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.exceptions import BadRequest, MethodNotAllowed, UnsupportedMediaType

from chat_handler import handle_user_query
from email_dispatcher import generate_pdf
from plan_utils import get_plan_limits, get_usage, ensure_user_exists
from newsletter import subscribe_to_newsletter
from verification_utils import (
    send_code_email, check_verification_code,
    get_client_ip, email_verification_ip_quota_exceeded,
    log_email_verification_ip
)
import psycopg2

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

# Environment
load_dotenv()
RAILWAY_ENV = os.getenv("RAILWAY_ENVIRONMENT")
if RAILWAY_ENV:
    log.info(f"Running in Railway environment: {RAILWAY_ENV}")
else:
    log.info("Running outside Railway or RAILWAY_ENVIRONMENT not set.")

if not os.getenv("DATABASE_URL"):
    log.warning("DATABASE_URL not set! Database operations may fail.")
if not os.getenv("PORT"):
    log.info("PORT not set, using default 8080.")

PORT = int(os.getenv("PORT", 8080))

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "https://zikarisk.com"}}, allow_headers=["Authorization", "Content-Type"])

@app.route("/chat", methods=["POST", "OPTIONS"])
def chat():
    print("CHAT ENDPOINT HIT")
    if request.method == "OPTIONS":
        print("OPTIONS request received")
        return _build_cors_response()
    try:
        print("Parsing JSON...")
        data = request.get_json(force=True)
        log.info("🔒 Incoming /chat request...")
        query = data.get("query", "")
        email = data.get("user_email", "anonymous")
        region = data.get("region")
        threat_type = data.get("type")
        print(f"query={query}, email={email}, region={region}, threat_type={threat_type}")
        region = None if not region or str(region).lower() == "all" else str(region)
        threat_type = None if not threat_type or str(threat_type).lower() == "all" else str(threat_type)
        if email and email != "anonymous":
            print("Ensuring user exists...")
            ensure_user_exists(email, plan="FREE")
        print("Calling handle_user_query...")
        result = handle_user_query(
            {"query": query},
            email=email,
            region=region,
            threat_type=threat_type,
        )
        print("handle_user_query returned, preparing response...")
        return _build_cors_response(jsonify(result))
    except BadRequest:
        print("BadRequest error")
        return _build_cors_response(jsonify({"error": "Malformed input"})), 400
    except MethodNotAllowed:
        print("MethodNotAllowed error")
        return _build_cors_response(jsonify({"error": "Method not allowed"})), 405
    except UnsupportedMediaType:
        print("UnsupportedMediaType error")
        return _build_cors_response(jsonify({"error": "Unsupported media type"})), 415
    except Exception as e:
        print(f"🔥 Unhandled error in /chat: {e}")
        log.error(f"🔥 Unhandled error in /chat: {e}")
        return _build_cors_response(jsonify({"error": "Internal server error"})), 500

@app.route("/request_report", methods=["POST"])
def request_report():
    print("REQUEST_REPORT ENDPOINT HIT")
    try:
        print("Parsing JSON for report...")
        data = request.get_json(force=True)
        email = data.get("user_email", "anonymous")
        region = data.get("region")
        threat_type = data.get("type")
        print(f"email={email}, region={region}, threat_type={threat_type}")
        region = None if not region or str(region).lower() == "all" else str(region)
        threat_type = None if not threat_type or str(threat_type).lower() == "all" else str(threat_type)
        log.info(f"📄 Generating report for {email} | Region={region}, Type={threat_type}")
        if email and email != "anonymous":
            print("Ensuring user exists for report...")
            ensure_user_exists(email, plan="FREE")
        print("Calling handle_user_query for report...")
        alerts = handle_user_query(
            {"query": "Generate my report"},
            email=email,
            region=region,
            threat_type=threat_type
        ).get("alerts", [])
        print(f"Alerts for report: {len(alerts)}")
        generate_pdf(email, alerts, get_plan_limits(email).get("name", "FREE"))
        print("Report generated and sent")
        return _build_cors_response(jsonify({
            "status": "Report generated and sent",
            "alerts_included": len(alerts)
        }))
    except Exception as e:
        print(f"🔥 Report generation failed: {e}")
        log.error(f"🔥 Report generation failed: {e}")
        return _build_cors_response(jsonify({"error": "Internal server error"})), 500

@app.route("/user_plan", methods=["GET"])
def user_plan():
    print("USER_PLAN ENDPOINT HIT")
    email = request.args.get("user_email", "anonymous")
    print(f"user_plan email={email}")
    if email and email != "anonymous":
        ensure_user_exists(email, plan="FREE")
    plan_limits = get_plan_limits(email)
    features = {
        "pdf": bool(plan_limits.get("custom_pdf_briefings_frequency")),
        "insights": bool(plan_limits.get("insights")),
        "telegram": bool(plan_limits.get("telegram")),
        "alerts": bool(plan_limits.get("rss_monthly", 0) > 0)
    }
    return jsonify({
        "email": email,
        "plan": plan_limits.get("name", "FREE"),
        "features": features,
        "limits": plan_limits
    })

@app.route("/plan_features", methods=["GET"])
def plan_features():
    print("PLAN_FEATURES ENDPOINT HIT")
    from plan_rules import PLAN_RULES
    return jsonify(PLAN_RULES)

@app.route("/usage", methods=["GET"])
def usage():
    print("USAGE ENDPOINT HIT")
    email = request.args.get("user_email")
    print(f"usage email={email}")
    if not email:
        return jsonify({"error": "Missing user_email"}), 400
    if email and email != "anonymous":
        ensure_user_exists(email, plan="FREE")
    usage_data = get_usage(email)
    return jsonify(usage_data)

@app.route("/health", methods=["GET"])
def health_check():
    print("HEALTH_CHECK ENDPOINT HIT")
    return jsonify({"status": "ok", "version": "1.0"}), 200

@app.route("/send_verification_code", methods=["POST"])
def send_code_route():
    print("SEND_VERIFICATION_CODE ENDPOINT HIT")
    try:
        print("Parsing JSON for verification code...")
        data = request.get_json(force=True)
        email = data.get("user_email", "").strip().lower()
        print(f"send_verification_code email={email}")
        if not email:
            return jsonify({"success": False, "error": "Missing user_email"}), 400
        ensure_user_exists(email, plan="FREE")
        ip = get_client_ip(request)
        if email_verification_ip_quota_exceeded(ip):
            return jsonify({"success": False, "error": "Too many verification attempts from your IP. Please try again later."}), 429
        log_email_verification_ip(ip)
        ok, error = send_code_email(email)
        if ok:
            return jsonify({"success": True})
        else:
            return jsonify({"success": False, "error": error}), 403
    except Exception as e:
        print(f"Verification send failed: {e}")
        log.error(f"Verification send failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/verify_code", methods=["POST"])
def verify_code_route():
    print("VERIFY_CODE ENDPOINT HIT")
    try:
        print("Parsing JSON for verify code...")
        data = request.get_json(force=True)
        email = data.get("user_email", "").strip().lower()
        code = data.get("code", "").strip()
        print(f"verify_code email={email}, code={code}")
        if not email or not code:
            return jsonify({"success": False, "error": "Missing user_email or code"}), 400
        ensure_user_exists(email, plan="FREE")
        ok, err = check_verification_code(email, code)
        return jsonify({"success": ok, "error": err if not ok else None})
    except Exception as e:
        print(f"Verification failed: {e}")
        log.error(f"Verification failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/newsletter_subscribe", methods=["POST"])
def newsletter_subscribe_route():
    print("NEWSLETTER_SUBSCRIBE ENDPOINT HIT")
    try:
        print("Parsing JSON for newsletter subscribe...")
        data = request.get_json(force=True)
        email = data.get("user_email", "").strip().lower()
        print(f"newsletter_subscribe email={email}")
        if not email:
            return jsonify({"success": False, "error": "Missing user_email"}), 400
        ensure_user_exists(email, plan="FREE")
        result = subscribe_to_newsletter(email)
        return jsonify({"success": result})
    except Exception as e:
        print(f"Newsletter error: {e}")
        log.error(f"Newsletter error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/presets", methods=["GET"])
def get_presets():
    try:
        category = request.args.get("category")
        limit = int(request.args.get("limit", 50))

        conn = psycopg2.connect(os.getenv("DATABASE_URL"))
        cur = conn.cursor()

        if category:
            cur.execute(
                "SELECT id, question, category FROM presets WHERE category = %s ORDER BY id LIMIT %s",
                (category, limit)
            )
        else:
            cur.execute(
                "SELECT id, question, category FROM presets ORDER BY id LIMIT %s",
                (limit,)
            )

        rows = cur.fetchall()
        cur.close()
        conn.close()

        return jsonify([
            {"id": row[0], "question": row[1], "category": row[2]}
            for row in rows
        ])
    except Exception as e:
        log.error(f"🔥 Error fetching presets: {e}")
        return jsonify({"error": "Internal server error"}), 500

@app.errorhandler(404)
def not_found_error(error):
    print("404 Not Found Error")
    log.warning(f"404 Not Found: {error}")
    return _build_cors_response(jsonify({"error": "Not found"})), 404

@app.errorhandler(405)
def method_not_allowed_error(error):
    print("405 Method Not Allowed Error")
    log.warning(f"405 Method Not Allowed: {error}")
    return _build_cors_response(jsonify({"error": "Method not allowed"})), 405

@app.errorhandler(500)
def internal_error(error):
    print("500 Internal Server Error")
    log.error(f"500 Internal Server Error: {error}")
    return _build_cors_response(jsonify({"error": "Internal server error"})), 500

def _build_cors_response(response=None):
    print("_build_cors_response called")
    headers = {
        "Access-Control-Allow-Origin": "https://zikarisk.com",
        "Access-Control-Allow-Methods": "POST, OPTIONS, GET",
        "Access-Control-Allow-Headers": "Content-Type"
    }
    if response is None:
        response = jsonify({})
    response.headers.update(headers)
    return response

if __name__ == "__main__":
    log.info("🚀 Sentinel AI backend starting...")
    print("ENV is:", os.getenv("ENV"))
    print("PORT is:", PORT)
    if os.getenv("ENV") != "production":
        print("Starting Flask app on port", PORT)
        app.run(host="0.0.0.0", port=PORT)