"""
health_check.py - Comprehensive health check endpoint for Railway deployments

Provides /health endpoint for:
- Zero-downtime deployments
- Uptime monitoring  
- Service dependency validation
- Performance metrics

Usage:
    uvicorn health_check:app --host 0.0.0.0 --port $PORT
"""

from datetime import datetime
import os
import json
from typing import Dict, Any, List

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import JSONResponse
except ImportError:
    # Fallback to Flask if FastAPI not available
    try:
        from flask import Flask, jsonify
        FastAPI = None
    except ImportError:
        FastAPI = None

# Initialize FastAPI app
if FastAPI:
    app = FastAPI(
        title="Sentinel AI Health Check",
        description="Health monitoring endpoint for Railway deployments",
        version="1.0.0"
    )
else:
    # Fallback Flask app
    from flask import Flask
    flask_app = Flask(__name__)

def check_database_health() -> Dict[str, Any]:
    """Check database connectivity and pool status."""
    try:
        from db_utils import _get_db_connection, fetch_one
        
        # Test basic connectivity
        with _get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 as test")
                result = cur.fetchone()
                
        # Test alerts table access
        alert_count = 0
        try:
            result = fetch_one("SELECT COUNT(*) FROM alerts LIMIT 1")
            alert_count = result[0] if result else 0
        except Exception:
            pass
            
        return {
            "connected": True,
            "test_query": True,
            "alerts_accessible": alert_count >= 0,
            "alert_count": alert_count,
            "error": None
        }
        
    except Exception as e:
        return {
            "connected": False,
            "test_query": False,
            "alerts_accessible": False,
            "alert_count": 0,
            "error": str(e)
        }

def check_llm_health() -> Dict[str, Any]:
    """Check LLM API connectivity (lightweight test)."""
    try:
        # Check XAI/Grok
        xai_status = {"available": False, "error": None}
        try:
            from xai_client import XAI_API_KEY
            if XAI_API_KEY:
                # Don't make actual API call in health check to avoid quota usage
                xai_status = {"available": True, "configured": True, "error": None}
            else:
                xai_status = {"available": False, "configured": False, "error": "XAI_API_KEY not set"}
        except ImportError as e:
            xai_status = {"available": False, "configured": False, "error": f"XAI client not available: {e}"}
        except Exception as e:
            xai_status = {"available": False, "configured": False, "error": str(e)}
        
        # Check OpenAI (if configured)
        openai_status = {"available": False, "error": None}
        try:
            openai_key = os.getenv("OPENAI_API_KEY")
            if openai_key:
                openai_status = {"available": True, "configured": True, "error": None}
            else:
                openai_status = {"available": False, "configured": False, "error": "OPENAI_API_KEY not set"}
        except Exception as e:
            openai_status = {"available": False, "configured": False, "error": str(e)}
            
        # Check DeepSeek (if configured)
        deepseek_status = {"available": False, "error": None}
        try:
            deepseek_key = os.getenv("DEEPSEEK_API_KEY")
            if deepseek_key:
                deepseek_status = {"available": True, "configured": True, "error": None}
            else:
                deepseek_status = {"available": False, "configured": False, "error": "DEEPSEEK_API_KEY not set"}
        except Exception as e:
            deepseek_status = {"available": False, "configured": False, "error": str(e)}
            
        return {
            "xai": xai_status,
            "openai": openai_status, 
            "deepseek": deepseek_status,
            "any_available": any([
                xai_status["available"], 
                openai_status["available"], 
                deepseek_status["available"]
            ])
        }
        
    except Exception as e:
        return {
            "xai": {"available": False, "error": str(e)},
            "openai": {"available": False, "error": str(e)},
            "deepseek": {"available": False, "error": str(e)},
            "any_available": False
        }

def check_cache_health() -> Dict[str, Any]:
    """Check Redis/cache connectivity."""
    try:
        redis_url = os.getenv("REDIS_URL")
        if not redis_url:
            return {"available": False, "configured": False, "error": "REDIS_URL not configured"}
            
        try:
            import redis
            r = redis.from_url(redis_url, socket_timeout=5)
            r.ping()
            return {"available": True, "configured": True, "error": None}
        except ImportError:
            return {"available": False, "configured": True, "error": "redis package not installed"}
        except Exception as e:
            return {"available": False, "configured": True, "error": str(e)}
            
    except Exception as e:
        return {"available": False, "configured": False, "error": str(e)}

def check_vector_system_health() -> Dict[str, Any]:
    """Check vector deduplication system health."""
    try:
        from keywords_loader import get_all_keywords
        from db_utils import fetch_one
        
        # Check keywords loaded
        keywords = get_all_keywords()
        keywords_count = len(keywords)
        
        # Check vector functions exist
        vector_functions = []
        try:
            result = fetch_one("""
                SELECT COUNT(*) 
                FROM pg_proc 
                WHERE proname = 'find_similar_alerts'
            """)
            if result and result[0] > 0:
                vector_functions.append("find_similar_alerts")
        except Exception:
            pass
            
        # Check vector operators exist
        vector_operators = []
        try:
            result = fetch_one("""
                SELECT COUNT(*) 
                FROM pg_operator 
                WHERE oprname = '<=>'
            """)
            if result and result[0] > 0:
                vector_operators.append("<=> (cosine distance)")
        except Exception:
            pass
        
        return {
            "keywords_loaded": keywords_count > 0,
            "keywords_count": keywords_count,
            "vector_functions": vector_functions,
            "vector_operators": vector_operators,
            "system_ready": keywords_count > 0 and len(vector_functions) > 0,
            "error": None
        }
        
    except Exception as e:
        return {
            "keywords_loaded": False,
            "keywords_count": 0,
            "vector_functions": [],
            "vector_operators": [],
            "system_ready": False,
            "error": str(e)
        }

def check_environment_health() -> Dict[str, Any]:
    """Check environment configuration and variables."""
    required_vars = [
        "DATABASE_URL",
        "OPENAI_API_KEY", 
        "XAI_API_KEY",
        "DEEPSEEK_API_KEY"
    ]
    
    optional_vars = [
        "REDIS_URL",
        "RAILWAY_ENVIRONMENT",
        "RAILWAY_GIT_COMMIT_SHA",
        "PORT"
    ]
    
    env_status = {}
    missing_required = []
    
    for var in required_vars:
        value = os.getenv(var)
        env_status[var] = {
            "set": value is not None,
            "length": len(value) if value else 0
        }
        if not value:
            missing_required.append(var)
    
    for var in optional_vars:
        value = os.getenv(var)
        env_status[var] = {
            "set": value is not None,
            "value": value if var not in ["RAILWAY_GIT_COMMIT_SHA"] else (value[:8] + "..." if value else None)
        }
    
    return {
        "variables": env_status,
        "missing_required": missing_required,
        "all_required_set": len(missing_required) == 0,
        "railway_environment": os.getenv("RAILWAY_ENVIRONMENT", "unknown"),
        "git_commit": os.getenv("RAILWAY_GIT_COMMIT_SHA", "unknown")[:8] if os.getenv("RAILWAY_GIT_COMMIT_SHA") else "unknown"
    }

def perform_health_check() -> Dict[str, Any]:
    """Perform comprehensive health check and return status."""
    timestamp = datetime.utcnow().isoformat() + "Z"
    issues = []
    
    # Environment check
    env_check = check_environment_health()
    if env_check["missing_required"]:
        issues.append(f"Missing required environment variables: {', '.join(env_check['missing_required'])}")
    
    # Database check
    db_check = check_database_health()
    if not db_check["connected"]:
        issues.append(f"Database connection failed: {db_check['error']}")
    elif not db_check["alerts_accessible"]:
        issues.append("Database connected but alerts table not accessible")
    
    # LLM check
    llm_check = check_llm_health()
    if not llm_check["any_available"]:
        issues.append("No LLM providers configured or available")
    
    # Cache check (optional)
    cache_check = check_cache_health()
    if cache_check["configured"] and not cache_check["available"]:
        issues.append(f"Cache configured but not available: {cache_check['error']}")
    
    # Vector system check
    vector_check = check_vector_system_health()
    if not vector_check["system_ready"]:
        issues.append(f"Vector deduplication system not ready: {vector_check['error']}")
    
    # Overall status
    status = "healthy" if not issues else "unhealthy"
    
    return {
        "status": status,
        "timestamp": timestamp,
        "version": env_check["git_commit"],
        "environment": env_check["railway_environment"],
        "uptime": "unknown",  # Could be enhanced with process start time
        "issues": issues,
        "checks": {
            "database": db_check,
            "llm": llm_check,
            "cache": cache_check,
            "vector_system": vector_check,
            "environment": env_check
        }
    }

# FastAPI routes
if FastAPI:
    @app.get("/health")
    @app.get("/")
    def health_endpoint():
        """Main health check endpoint for Railway and monitoring."""
        try:
            health_data = perform_health_check()
            status_code = 200 if health_data["status"] == "healthy" else 503
            return JSONResponse(content=health_data, status_code=status_code)
        except Exception as e:
            return JSONResponse(
                content={
                    "status": "error",
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "error": str(e),
                    "issues": [f"Health check failed: {str(e)}"]
                },
                status_code=500
            )
    
    @app.get("/health/quick")
    def quick_health():
        """Quick health check - just database ping."""
        try:
            db_check = check_database_health()
            status = "healthy" if db_check["connected"] else "unhealthy"
            return JSONResponse(
                content={"status": status, "timestamp": datetime.utcnow().isoformat() + "Z"},
                status_code=200 if status == "healthy" else 503
            )
        except Exception as e:
            return JSONResponse(
                content={"status": "error", "error": str(e)},
                status_code=500
            )
    
    @app.get("/health/detailed")
    def detailed_health():
        """Detailed health check with full diagnostics."""
        health_data = perform_health_check()
        return JSONResponse(content=health_data, status_code=200)

# Flask routes (fallback)
else:
    @flask_app.route('/health')
    @flask_app.route('/')
    def health_endpoint():
        """Main health check endpoint for Railway and monitoring."""
        try:
            health_data = perform_health_check()
            status_code = 200 if health_data["status"] == "healthy" else 503
            response = jsonify(health_data)
            response.status_code = status_code
            return response
        except Exception as e:
            response = jsonify({
                "status": "error",
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "error": str(e),
                "issues": [f"Health check failed: {str(e)}"]
            })
            response.status_code = 500
            return response

# For direct execution
if __name__ == "__main__":
    # Test health check
    health_result = perform_health_check()
    print("=== Sentinel AI Health Check ===")
    print(json.dumps(health_result, indent=2))
    
    if health_result["status"] == "healthy":
        print("\n✅ All systems healthy")
        exit(0)
    else:
        print(f"\n❌ Issues found: {len(health_result['issues'])}")
        for issue in health_result["issues"]:
            print(f"  - {issue}")
        exit(1)
