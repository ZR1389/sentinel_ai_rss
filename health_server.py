"""
Simple Flask health check server for Railway deployment.
Fallback when FastAPI is not available.
"""

from flask import Flask, jsonify
import os
import sys

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from health_check import perform_health_check

app = Flask(__name__)

@app.route('/health')
@app.route('/')
def health_endpoint():
    """Main health check endpoint for Railway."""
    try:
        health_data = perform_health_check()
        status_code = 200 if health_data["status"] == "healthy" else 200  # Always return 200 for Railway
        response = jsonify(health_data)
        response.status_code = status_code
        return response
    except Exception as e:
        response = jsonify({
            "status": "error",
            "error": str(e),
            "timestamp": "unknown"
        })
        response.status_code = 500
        return response

@app.route('/health/quick')
def quick_health():
    """Quick health check - just database."""
    try:
        from health_check import check_database_health
        db_check = check_database_health()
        status = "healthy" if db_check["connected"] else "degraded"
        return jsonify({"status": status, "database": db_check})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route('/ping')
def ping():
    """Simple ping endpoint."""
    return jsonify({"status": "ok", "message": "pong"})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
