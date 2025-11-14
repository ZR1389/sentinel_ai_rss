from flask import Blueprint, request, jsonify
from socmint_service import SocmintService, get_cache_metrics, reset_cache_metrics
import auth_utils
from functools import wraps
import logging
import urllib.parse
from db_utils import fetch_one

socmint_bp = Blueprint('socmint', __name__)
apify_service = SocmintService()
logger = logging.getLogger(__name__)

# Try to import limiter for rate limiting
try:
    from main import limiter, SOCMINT_INSTAGRAM_RATE, SOCMINT_FACEBOOK_RATE
except ImportError:
    limiter = None
    SOCMINT_INSTAGRAM_RATE = "30 per minute"
    SOCMINT_FACEBOOK_RATE = "10 per minute"

# Instagram endpoint
@socmint_bp.route('/instagram/<username>', methods=['GET'])
@auth_utils.login_required
def get_instagram_profile(username):
    """GET /api/socmint/instagram/hacker_group?limit=10"""
    try:
        limit = min(int(request.args.get('limit', 20)), 100)
        result = apify_service.run_instagram_scraper(username, limit)
        
        if result["success"]:
            apify_service.save_socmint_data('instagram', username, result["data"])
            return jsonify(result), 200
        else:
            logger.warning(f"SOCMINT: Instagram scrape failed for {username}: {result['error']}")
            return jsonify(result), 400
            
    except ValueError:
        return jsonify(success=False, error="Invalid limit parameter"), 400
    except Exception as e:
        logger.error(f"SOCMINT: Instagram endpoint error: {str(e)}", exc_info=True)
        return jsonify(success=False, error="Server error"), 500

# Apply rate limit to Instagram endpoint
if limiter:
    get_instagram_profile = limiter.limit(SOCMINT_INSTAGRAM_RATE)(get_instagram_profile)

# Metrics endpoints
@socmint_bp.route('/metrics', methods=['GET'])
@auth_utils.login_required
def get_metrics():
    """Get SOCMINT cache performance metrics.
    
    Returns:
        JSON with cache hits, misses, hit rate, Apify calls, etc.
    """
    try:
        metrics = get_cache_metrics()
        return jsonify({
            "status": "success",
            "metrics": metrics
        }), 200
    except Exception as e:
        logger.error(f"Metrics retrieval failed: {e}")
        return jsonify({"error": "Internal server error"}), 500

@socmint_bp.route('/metrics/reset', methods=['POST'])
@auth_utils.login_required
def reset_metrics():
    """Reset SOCMINT cache metrics counters."""
    try:
        reset_cache_metrics()
        return jsonify({
            "status": "success",
            "message": "Cache metrics reset successfully"
        }), 200
    except Exception as e:
        logger.error(f"Metrics reset failed: {e}")
        return jsonify({"error": "Internal server error"}), 500

# Facebook endpoint
@socmint_bp.route('/facebook', methods=['POST'])
@auth_utils.login_required
def get_facebook_posts():
    """POST /api/socmint/facebook 
    Body: {"page_url": "https://www.facebook.com/ransomware.group", "limit": 20}
    """
    try:
        data = request.get_json()
        if not data or 'page_url' not in data:
            return jsonify(success=False, error="Missing required field: page_url"), 400
            
        page_url = data['page_url']
        limit = min(int(data.get('limit', 20)), 100)
        
        result = apify_service.run_facebook_scraper(page_url, limit)
        
        if result["success"]:
            apify_service.save_socmint_data('facebook', page_url, result["data"])
            return jsonify(result), 200
        else:
            logger.warning(f"SOCMINT: Facebook scrape failed for {page_url}: {result['error']}")
            return jsonify(result), 400
            
    except Exception as e:
        logger.error(f"SOCMINT: Facebook endpoint error: {str(e)}", exc_info=True)
        return jsonify(success=False, error="Server error"), 500

# Apply rate limit to Facebook endpoint (stricter due to block risk)
if limiter:
    get_facebook_posts = limiter.limit(SOCMINT_FACEBOOK_RATE)(get_facebook_posts)

# Status check endpoint
@socmint_bp.route('/status/<platform>/<path:identifier>', methods=['GET'])
@auth_utils.login_required
def get_socmint_status(platform, identifier):
    """Check scrape status and last data for a profile
    GET /api/socmint/status/instagram/hacker_group
    GET /api/socmint/status/facebook/https%3A%2F%2Ffacebook.com%2Fransomware.group
    """
    try:
        # Decode URL-encoded identifier
        identifier = urllib.parse.unquote(identifier)
        
        query = """
            SELECT platform, identifier, scraped_timestamp, analysis_status,
                   profile_data->>'full_name' as profile_name,
                   jsonb_array_length(COALESCE(posts_data, '[]'::jsonb)) as post_count
            FROM socmint_profiles 
            WHERE platform = %s AND identifier = %s
            ORDER BY scraped_timestamp DESC
            LIMIT 1
        """
        
        result = fetch_one(query, (platform, identifier))
        
        if not result:
            return jsonify({
                "found": False,
                "message": "No scrape record found"
            }), 404
            
        return jsonify({
            "found": True,
            "platform": result[0],
            "identifier": result[1],
            "last_scraped": result[2].isoformat() if result[2] else None,
            "analysis_status": result[3],
            "profile_name": result[4] if len(result) > 4 else None,
            "post_count": result[5] if len(result) > 5 else 0
        }), 200
        
    except Exception as e:
        logger.error(f"Status check failed: {str(e)}", exc_info=True)
        return jsonify(success=False, error="Server error"), 500

# Metrics endpoints
@socmint_bp.route('/metrics', methods=['GET'])
@auth_utils.login_required
def get_metrics():
    """Get SOCMINT cache performance metrics.
    
    Returns:
        JSON with cache hits, misses, hit rate, Apify calls, etc.
    
    Example:
        GET /api/socmint/metrics
    """
    try:
        metrics = get_cache_metrics()
        return jsonify({
            "status": "success",
            "metrics": metrics
        }), 200
    except Exception as e:
        logger.error(f"Metrics retrieval failed: {e}")
        return jsonify({"error": "Internal server error"}), 500

@socmint_bp.route('/metrics/reset', methods=['POST'])
@auth_utils.login_required
def reset_metrics():
    """Reset SOCMINT cache metrics counters.
    
    Example:
        POST /api/socmint/metrics/reset
    """
    try:
        reset_cache_metrics()
        return jsonify({
            "status": "success",
            "message": "Cache metrics reset successfully"
        }), 200
    except Exception as e:
        logger.error(f"Metrics reset failed: {e}")
        return jsonify({"error": "Internal server error"}), 500

# Dashboard endpoint
@socmint_bp.route('/dashboard', methods=['GET'])
@auth_utils.login_required
def get_dashboard():
    """Aggregated SOCMINT operational dashboard metrics.

    Example:
        GET /api/socmint/dashboard
    Returns platform stats, totals, recent errors, insights.
    """
    try:
        data = apify_service.get_dashboard_metrics()
        return jsonify({"status": "success", "dashboard": data}), 200
    except Exception as e:
        logger.error(f"Dashboard retrieval failed: {e}")
        return jsonify({"status": "error", "error": "Internal server error"}), 500
