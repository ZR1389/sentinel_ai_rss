#!/usr/bin/env python3
"""
railway_health.py - Railway-optimized health server

This is a simplified, Railway-compatible health server that addresses common deployment issues:
- Proper Railway environment detection
- Robust port handling
- Graceful error handling for missing dependencies
- Faster startup time
"""

import os
import sys
import json
import logging
from datetime import datetime
from typing import Dict, Any

# Configure basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Railway environment detection
RAILWAY_ENVIRONMENT = os.getenv('RAILWAY_ENVIRONMENT', os.getenv('ENV', 'development'))
IS_RAILWAY = RAILWAY_ENVIRONMENT in ['production', 'staging'] or 'railway' in os.getenv('DATABASE_URL', '').lower()

def get_port() -> int:
    """Get the port from Railway environment or default."""
    port = os.getenv('PORT', '8080')
    try:
        return int(port)
    except (ValueError, TypeError):
        logger.warning(f"Invalid PORT value '{port}', using default 8080")
        return 8080

def check_basic_health() -> Dict[str, Any]:
    """Quick health check without heavy dependencies."""
    health_data = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "environment": RAILWAY_ENVIRONMENT,
        "is_railway": IS_RAILWAY,
        "port": get_port(),
        "python_version": sys.version,
        "checks": {},
        "issues": []
    }
    
    # Check environment variables
    required_vars = ["DATABASE_URL"]
    optional_vars = ["OPENAI_API_KEY", "XAI_API_KEY", "DEEPSEEK_API_KEY"]
    
    for var in required_vars:
        if not os.getenv(var):
            health_data["status"] = "unhealthy"
            health_data["issues"].append(f"Missing required environment variable: {var}")
            health_data["checks"][var] = False
        else:
            health_data["checks"][var] = True
    
    # Check at least one LLM provider
    llm_available = any(os.getenv(var) for var in optional_vars)
    health_data["checks"]["llm_provider"] = llm_available
    if not llm_available:
        health_data["status"] = "unhealthy"
        health_data["issues"].append("No LLM provider API key configured")
    
    # Quick database check
    try:
        import psycopg2
        db_url = os.getenv('DATABASE_URL')
        if db_url:
            conn = psycopg2.connect(db_url)
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            conn.close()
            health_data["checks"]["database"] = True
        else:
            health_data["checks"]["database"] = False
    except Exception as e:
        health_data["checks"]["database"] = False
        health_data["issues"].append(f"Database connection failed: {str(e)}")
        if health_data["status"] == "healthy":
            health_data["status"] = "degraded"
    
    return health_data

# Try FastAPI first, fallback to Flask
try:
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    
    app = FastAPI(
        title="Sentinel AI Railway Health",
        description="Railway-optimized health monitoring",
        version="1.0.0",
        docs_url="/docs" if not IS_RAILWAY else None,  # Disable docs in production
        redoc_url=None
    )
    
    @app.get("/")
    @app.get("/health")
    async def health_check():
        """Main health check endpoint."""
        try:
            health_data = check_basic_health()
            status_code = 200 if health_data["status"] == "healthy" else 503
            return JSONResponse(content=health_data, status_code=status_code)
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return JSONResponse(
                content={
                    "status": "error",
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "error": str(e)
                },
                status_code=500
            )
    
    @app.get("/health/quick")
    async def quick_health():
        """Quick health check - just basic status."""
        return JSONResponse(content={
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "port": get_port(),
            "environment": RAILWAY_ENVIRONMENT
        })
    
    logger.info("FastAPI health server initialized")
    
except ImportError:
    logger.warning("FastAPI not available, falling back to Flask")
    from flask import Flask, jsonify
    
    app = Flask(__name__)
    
    @app.route("/")
    @app.route("/health")
    def health_check():
        """Main health check endpoint."""
        try:
            health_data = check_basic_health()
            status_code = 200 if health_data["status"] == "healthy" else 503
            response = jsonify(health_data)
            response.status_code = status_code
            return response
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            response = jsonify({
                "status": "error",
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "error": str(e)
            })
            response.status_code = 500
            return response
    
    @app.route("/health/quick")
    def quick_health():
        """Quick health check."""
        return jsonify({
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "port": get_port(),
            "environment": RAILWAY_ENVIRONMENT
        })
    
    logger.info("Flask health server initialized")

if __name__ == "__main__":
    port = get_port()
    logger.info(f"Starting health server on port {port}")
    
    # Test health check before starting server
    try:
        health_result = check_basic_health()
        logger.info(f"Health check result: {health_result['status']}")
        if health_result["issues"]:
            for issue in health_result["issues"]:
                logger.warning(f"Health issue: {issue}")
    except Exception as e:
        logger.error(f"Health check test failed: {e}")
    
    # Start appropriate server
    try:
        import uvicorn
        logger.info("Starting with uvicorn...")
        uvicorn.run(app, host="0.0.0.0", port=port)
    except ImportError:
        logger.info("Starting with Flask development server...")
        app.run(host="0.0.0.0", port=port)
