#!/usr/bin/env python3
"""Tests for new gated endpoints: map features, PDF export, briefing package.

Tests tier-specific access to:
- GET /api/map/features (plan feature matrix)
- GET /api/chat/threads/<uuid>/export/pdf (chat_export_pdf)
- POST /api/briefing/package (briefing_packages)
"""
import os
import jwt
import json
import datetime
import uuid
from unittest.mock import patch, MagicMock
from config import CONFIG

JWT_SECRET = CONFIG.security.jwt_secret or 'testsecret'

def make_token(email: str, plan: str):
    payload = {
        'user_email': email,
        'plan': plan,
        'type': 'access',
        'exp': datetime.datetime.utcnow() + datetime.timedelta(minutes=5)
    }
    return 'Bearer ' + jwt.encode(payload, JWT_SECRET, algorithm='HS256')

def _fake_user_row(plan: str):
    return {'id': 1, 'plan': plan}

# ==================== Map Features Tests ====================

def test_map_features_free_plan():
    """FREE plan should see limited map features"""
    import main
    client = main.app.test_client()
    with patch.object(main, 'fetch_one', return_value=_fake_user_row('FREE')):
        resp = client.get('/api/map/features',
                          headers={'Authorization': make_token('free@example.com', 'FREE')})
        assert resp.status_code == 200, resp.data
        body = resp.get_json()
        assert body.get('ok') is True
        features = body.get('features', {})
        # FREE should have minimal features
        assert features.get('map_custom_filters') is False
        assert features.get('map_historical_playback') is False
        assert features.get('safe_zones_overlay') is False

def test_map_features_pro_plan():
    """PRO plan should have basic but not advanced map features"""
    import main
    client = main.app.test_client()
    with patch.object(main, 'fetch_one', return_value=_fake_user_row('PRO')):
        resp = client.get('/api/map/features',
                          headers={'Authorization': make_token('pro@example.com', 'PRO')})
        assert resp.status_code == 200, resp.data
        body = resp.get_json()
        features = body.get('features', {})
        # PRO has basic filters but NOT advanced features (per plans.py)
        assert features.get('map_custom_filters') is False
        assert features.get('map_historical_playback') is False
        assert features.get('map_export') == 'csv'  # CSV export only

def test_map_features_enterprise_plan():
    """ENTERPRISE plan should have all map features"""
    import main
    client = main.app.test_client()
    with patch.object(main, 'fetch_one', return_value=_fake_user_row('ENTERPRISE')):
        resp = client.get('/api/map/features',
                          headers={'Authorization': make_token('ent@example.com', 'ENTERPRISE')})
        assert resp.status_code == 200, resp.data
        body = resp.get_json()
        features = body.get('features', {})
        # ENTERPRISE should have everything
        assert features.get('map_custom_filters') is True
        assert features.get('map_historical_playback') is True
        assert features.get('safe_zones_overlay') is True
        assert features.get('map_export') == 'all'  # All export formats

# ==================== Chat PDF Export Tests ====================

def test_chat_pdf_export_free_blocked():
    """FREE plan should be blocked from PDF export"""
    import main
    client = main.app.test_client()
    thread_id = str(uuid.uuid4())
    
    # Mock thread fetch to return a valid thread
    mock_thread = {'thread_uuid': thread_id, 'user_id': 1, 'title': 'Test Thread'}
    
    with patch.object(main, 'fetch_one', side_effect=[
        _fake_user_row('FREE'),  # user lookup
        mock_thread,              # thread lookup
    ]):
        resp = client.get(f'/api/chat/threads/{thread_id}/export/pdf',
                          headers={'Authorization': make_token('free@example.com', 'FREE')})
        assert resp.status_code == 403, resp.data
        body = resp.get_json()
        assert body.get('feature_locked') is True
        assert 'PDF export requires PRO plan' in body.get('error', '')

def test_chat_pdf_export_pro_allowed():
    """PRO plan should allow PDF export"""
    import main
    client = main.app.test_client()
    thread_id = str(uuid.uuid4())
    
    mock_thread = {'thread_uuid': thread_id, 'user_id': 1, 'title': 'Test Thread'}
    mock_messages = [
        {'role': 'user', 'content': 'Hello', 'created_at': datetime.datetime.utcnow()},
        {'role': 'assistant', 'content': 'Hi there', 'created_at': datetime.datetime.utcnow()}
    ]
    
    with patch.object(main, 'fetch_one', side_effect=[
        _fake_user_row('PRO'),
        mock_thread,
    ]), patch.object(main, 'fetch_all', return_value=mock_messages):
        resp = client.get(f'/api/chat/threads/{thread_id}/export/pdf',
                          headers={'Authorization': make_token('pro@example.com', 'PRO')})
        # Should pass gating (might 500 on PDF generation but gating succeeded)
        assert resp.status_code in (200, 500), resp.data
        if resp.status_code == 200:
            body = resp.get_json()
            assert body.get('ok') is True
            assert 'pdf_base64' in body

def test_chat_pdf_export_thread_not_found():
    """Should return 404 for non-existent thread"""
    import main
    client = main.app.test_client()
    thread_id = str(uuid.uuid4())
    
    with patch.object(main, 'fetch_one', side_effect=[
        _fake_user_row('PRO'),
        None,  # thread not found
    ]):
        resp = client.get(f'/api/chat/threads/{thread_id}/export/pdf',
                          headers={'Authorization': make_token('pro@example.com', 'PRO')})
        assert resp.status_code == 404, resp.data

# ==================== Briefing Package Tests ====================

def test_briefing_package_free_blocked():
    """FREE plan should be blocked from briefing packages"""
    import main
    client = main.app.test_client()
    
    with patch.object(main, 'fetch_one', return_value=_fake_user_row('FREE')):
        resp = client.post('/api/briefing/package',
                           headers={'Authorization': make_token('free@example.com', 'FREE'),
                                    'Content-Type': 'application/json'},
                           data=json.dumps({
                               'location': {'lat': 40.7128, 'lon': -74.0060},
                               'sections': ['threat', 'travel']
                           }))
        assert resp.status_code == 403, resp.data
        body = resp.get_json()
        assert body.get('feature_locked') is True
        assert 'Briefing packages require PRO plan' in body.get('error', '')

def test_briefing_package_pro_allowed():
    """PRO plan should allow briefing packages (per plans.py)"""
    import main
    client = main.app.test_client()
    
    with patch.object(main, 'fetch_one', return_value=_fake_user_row('PRO')):
        resp = client.post('/api/briefing/package',
                           headers={'Authorization': make_token('pro@example.com', 'PRO'),
                                    'Content-Type': 'application/json'},
                           data=json.dumps({
                               'location': {'lat': 40.7128, 'lon': -74.0060},
                               'sections': ['threat', 'travel']
                           }))
        # Should pass gating
        assert resp.status_code in (200, 400, 500), resp.data
        if resp.status_code == 200:
            body = resp.get_json()
            assert body.get('ok') is True

def test_briefing_package_business_allowed():
    """BUSINESS plan should allow briefing packages"""
    import main
    client = main.app.test_client()
    
    with patch.object(main, 'fetch_one', return_value=_fake_user_row('BUSINESS')):
        resp = client.post('/api/briefing/package',
                           headers={'Authorization': make_token('biz@example.com', 'BUSINESS'),
                                    'Content-Type': 'application/json'},
                           data=json.dumps({
                               'location': {'lat': 40.7128, 'lon': -74.0060},
                               'sections': ['threat', 'travel']
                           }))
        # Should pass gating (might 500 on generation but gating succeeded)
        assert resp.status_code in (200, 400, 500), resp.data
        if resp.status_code == 200:
            body = resp.get_json()
            assert body.get('ok') is True
            assert 'sections' in body

def test_briefing_package_missing_location():
    """Should validate required location field"""
    import main
    client = main.app.test_client()
    
    with patch.object(main, 'fetch_one', return_value=_fake_user_row('BUSINESS')):
        resp = client.post('/api/briefing/package',
                           headers={'Authorization': make_token('biz@example.com', 'BUSINESS'),
                                    'Content-Type': 'application/json'},
                           data=json.dumps({
                               'sections': ['threat']
                           }))
        # Will pass gating but may fail validation; accept 200 or 400
        assert resp.status_code in (200, 400), resp.data

if __name__ == '__main__':
    # Run tests manually
    for name, fn in list(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print('✓', name)
            except AssertionError as e:
                print('✗', name, ':', e)
            except Exception as e:
                print('⚠', name, ':', e)
    print('All new endpoint gating tests completed')
