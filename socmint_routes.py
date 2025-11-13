from flask import Blueprint, request, jsonify
from socmint_service import SocmintService
try:
    from auth_utils import login_required
except ImportError:
    def login_required(f):
        return f

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

@socmint_bp.route('/socmint/linkedin', methods=['POST'])
@login_required
def get_linkedin_profile():
    """Scrape LinkedIn profile - requires full URL in body"""
    data = request.get_json()
    profile_url = data.get('profile_url')
    
    if not profile_url:
        return jsonify({"error": "profile_url required"}), 400
    
    result = socmint_service.scrape_linkedin_profile(profile_url)
    
    if result['success']:
        return jsonify(result), 200
    else:
        return jsonify(result), 400
