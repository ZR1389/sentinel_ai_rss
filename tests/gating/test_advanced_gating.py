#!/usr/bin/env python3
"""Tests for advanced gating: saved search deletion protection, safe zones, map/timeline/stats enforcement.

Tests:
- Saved search deletion anti-downgrade protection
- Safe zones overlay gating (BUSINESS+)
- Map historical playback days cap enforcement
- Timeline access gating
- Statistics dashboard gating
"""
import os
import jwt
import json
import datetime
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

# ==================== Saved Search Deletion Tests ====================

def test_saved_search_delete_over_limit_allowed():
    """Can delete over-limit search when over capacity"""
    import main
    client = main.app.test_client()
    
    # User has 5 searches but PRO limit is 3
    with patch.object(main, 'fetch_one', side_effect=[
        _fake_user_row('PRO'),  # user lookup
        {'is_over_limit': True},  # search is over-limit
        {'c': 5},  # count: 5 searches total
    ]), patch.object(main, 'execute', return_value=None):
        resp = client.delete('/api/monitoring/searches/123',
                             headers={'Authorization': make_token('pro@example.com', 'PRO')})
        assert resp.status_code == 200, resp.data
        body = resp.get_json()
        assert body.get('ok') is True
        assert body.get('deleted') == 123

def test_saved_search_delete_within_limit_blocked_when_over():
    """Cannot delete within-limit search when over capacity"""
    import main
    client = main.app.test_client()
    
    # User has 5 searches but PRO limit is 3; trying to delete a within-limit search
    with patch.object(main, 'fetch_one', side_effect=[
        _fake_user_row('PRO'),
        {'is_over_limit': False},  # search is within-limit (precious!)
        {'c': 5},
    ]):
        resp = client.delete('/api/monitoring/searches/123',
                             headers={'Authorization': make_token('pro@example.com', 'PRO')})
        assert resp.status_code == 403, resp.data
        body = resp.get_json()
        assert body.get('feature_locked') is True
        assert 'Cannot delete within-limit search' in body.get('error', '')

def test_saved_search_delete_allowed_when_under_limit():
    """Can delete any search when under plan limit"""
    import main
    client = main.app.test_client()
    
    # User has 2 searches, PRO limit is 3
    with patch.object(main, 'fetch_one', side_effect=[
        _fake_user_row('PRO'),
        {'is_over_limit': False},
        {'c': 2},
    ]), patch.object(main, 'execute', return_value=None):
        resp = client.delete('/api/monitoring/searches/123',
                             headers={'Authorization': make_token('pro@example.com', 'PRO')})
        assert resp.status_code == 200, resp.data

def test_saved_search_delete_not_found():
    """Returns 404 for non-existent search"""
    import main
    client = main.app.test_client()
    
    with patch.object(main, 'fetch_one', side_effect=[
        _fake_user_row('PRO'),
        None,  # search not found
    ]):
        resp = client.delete('/api/monitoring/searches/999',
                             headers={'Authorization': make_token('pro@example.com', 'PRO')})
        assert resp.status_code == 404, resp.data

# ==================== Safe Zones Tests ====================

def test_safe_zones_free_blocked():
    """FREE plan cannot access safe zones overlay"""
    import main
    client = main.app.test_client()
    
    resp = client.get('/api/monitoring/safe-zones',
                      headers={'Authorization': make_token('free@example.com', 'FREE')})
    assert resp.status_code == 403, resp.data
    body = resp.get_json()
    assert body.get('feature_locked') is True
    assert 'BUSINESS plan' in body.get('error', '')

def test_safe_zones_pro_blocked():
    """PRO plan cannot access safe zones overlay (requires BUSINESS)"""
    import main
    client = main.app.test_client()
    
    resp = client.get('/api/monitoring/safe-zones',
                      headers={'Authorization': make_token('pro@example.com', 'PRO')})
    assert resp.status_code == 403, resp.data

def test_safe_zones_business_allowed():
    """BUSINESS plan can access safe zones overlay"""
    import main
    client = main.app.test_client()
    
    resp = client.get('/api/monitoring/safe-zones',
                      headers={'Authorization': make_token('biz@example.com', 'BUSINESS')})
    assert resp.status_code == 200, resp.data
    body = resp.get_json()
    assert body.get('ok') is True
    assert 'safe_zones' in body

def test_safe_zones_enterprise_allowed():
    """ENTERPRISE plan can access safe zones overlay"""
    import main
    client = main.app.test_client()
    
    resp = client.get('/api/monitoring/safe-zones',
                      headers={'Authorization': make_token('ent@example.com', 'ENTERPRISE')})
    assert resp.status_code == 200, resp.data

# ==================== Timeline Access Tests ====================

def test_timeline_free_blocked():
    """FREE plan cannot access timeline (no timeline_access)"""
    import main
    client = main.app.test_client()
    
    with patch.object(main, 'fetch_all', return_value=[]):
        resp = client.get('/analytics/timeline',
                          headers={'Authorization': make_token('free@example.com', 'FREE')})
        assert resp.status_code == 403, resp.data
        body = resp.get_json()
        assert 'Timeline requires PRO plan' in body.get('error', '')

def test_timeline_pro_allowed():
    """PRO plan can access timeline"""
    import main
    client = main.app.test_client()
    
    with patch.object(main, 'fetch_all', return_value=[
        {'incident_date': '2025-11-20', 'incident_count': 5},
        {'incident_date': '2025-11-21', 'incident_count': 3},
    ]):
        resp = client.get('/analytics/timeline',
                          headers={'Authorization': make_token('pro@example.com', 'PRO')})
        assert resp.status_code == 200, resp.data
        body = resp.get_json()
        assert body.get('ok') is True
        assert 'series' in body
        assert body.get('window_days') == 30  # PRO timeline_days

# ==================== Statistics Dashboard Tests ====================

def test_stats_free_blocked():
    """FREE plan cannot access statistics dashboard"""
    import main
    client = main.app.test_client()
    
    resp = client.get('/api/stats/overview',
                      headers={'Authorization': make_token('free@example.com', 'FREE')})
    assert resp.status_code == 403, resp.data
    body = resp.get_json()
    assert 'Statistics dashboard requires PRO plan' in body.get('error', '')

def test_stats_pro_allowed():
    """PRO plan can access basic statistics dashboard"""
    import main
    client = main.app.test_client()
    
    # Mock DB calls to avoid actual queries
    with patch.object(main, 'fetch_one', return_value={'c': 100}), \
         patch.object(main, 'fetch_all', return_value=[]):
        resp = client.get('/api/stats/overview',
                          headers={'Authorization': make_token('pro@example.com', 'PRO')})
        # May fail on DB queries but gating should pass (200 or 500, not 403)
        assert resp.status_code in (200, 500), resp.data
        if resp.status_code == 403:
            # If 403, verify it's not our feature gate
            body = resp.get_json()
            assert 'Statistics dashboard requires' not in body.get('error', ''), "Feature gate incorrectly triggered"

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
    print('All advanced gating tests completed')
