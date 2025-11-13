from flask import Blueprint, request, jsonify
from app.services.socmint_service import SocmintService
from app.middleware.auth import token_required

socmint_bp = Blueprint('socmint', __name__)
socmint_service = SocmintService()

@socmint_bp.route('/socmint/instagram/<username>', methods=['GET'])
@token_required
def get_instagram_profile(current_user, username):
    """Scrape Instagram profile"""
    result = socmint_service.scrape_instagram_profile(username)
    
    if result['success']:
        return jsonify(result), 200
    else:
        return jsonify(result), 400

@socmint_bp.route('/socmint/linkedin', methods=['POST'])
@token_required
def get_linkedin_profile(current_user):
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
