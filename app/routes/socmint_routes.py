from flask import Blueprint, request, jsonify
from socmint_service import SocmintService
try:
    from auth_utils import login_required
except ImportError:
    pass

socmint_bp = Blueprint('socmint', __name__)
socmint_service = SocmintService()

@socmint_bp.route('/socmint/instagram/<username>', methods=['GET'])
@login_required
def get_instagram_profile(username):
    """Scrape Instagram profile"""
    result = socmint_service.scrape_instagram_profile(username)
    
    if result['success']:
        return jsonify(result), 200
    else:
        return jsonify(result), 400

@socmint_bp.route('/socmint/twitter/<username>', methods=['GET'])
@login_required
def get_twitter_profile(username):
    """Scrape Twitter (X) profile and recent tweets. Optional query param tweets_desired."""
    try:
        tweets_desired = int(request.args.get('tweets_desired', '20'))
    except ValueError:
        return jsonify({"error": "tweets_desired must be an integer"}), 400
    result = socmint_service.run_twitter_scraper(username, tweets_desired=tweets_desired)
    return jsonify(result), (200 if result.get('success') else 400)
