from flask import Blueprint, request, jsonify
from socmint_service import SocmintService
import auth_utils
import logging
import urllib.parse
import os
from db_utils import fetch_one

socmint_bp = Blueprint('socmint', __name__)
apify_service = SocmintService()
logger = logging.getLogger(__name__)

# Rate limit configuration now decoupled from main to avoid circular import.
# Main application will inject the limiter via `set_socmint_limiter` after blueprint registration.
SOCMINT_INSTAGRAM_RATE = os.getenv("SOCMINT_INSTAGRAM_RATE", "30 per minute")
SOCMINT_FACEBOOK_RATE = os.getenv("SOCMINT_FACEBOOK_RATE", "10 per minute")
_INJECTED_LIMITER = None  # set by set_socmint_limiter()

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

# Rate limits applied later via set_socmint_limiter()

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

# Rate limits applied later via set_socmint_limiter()

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


def set_socmint_limiter(limiter_obj):
    """Inject flask-limiter instance after app & blueprint setup.

    This avoids circular imports with main.py. Can be called safely multiple times.
    """
    global _INJECTED_LIMITER, get_instagram_profile, get_facebook_posts, get_socmint_status
    if limiter_obj is None:
        return
    if _INJECTED_LIMITER is limiter_obj:
        return  # already applied
    _INJECTED_LIMITER = limiter_obj
    try:
        get_instagram_profile = limiter_obj.limit(SOCMINT_INSTAGRAM_RATE)(get_instagram_profile)
        get_facebook_posts = limiter_obj.limit(SOCMINT_FACEBOOK_RATE)(get_facebook_posts)
        # Generic status endpoint—slightly higher allowance
        get_socmint_status = limiter_obj.limit("60 per minute")(get_socmint_status)
        logger.info("[socmint_routes] Rate limits applied successfully")
    except Exception as e:  # pragma: no cover
        logger.warning(f"[socmint_routes] Failed to apply rate limits: {e}")
