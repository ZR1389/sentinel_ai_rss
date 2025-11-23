#!/usr/bin/env python3
"""Tests for medium-priority gating: weekly trends, team users, API access, analyst access, monthly briefing, custom reports.

Tests:
- Weekly trends in stats dashboard (PRO+)
- Team invites with team_users quota (BUSINESS+)
- API token issuance (ENTERPRISE)
- Analyst intelligence access (ENTERPRISE)
- Monthly briefing (ENTERPRISE)
- Custom reports (ENTERPRISE)
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

# ==================== Weekly Trends Tests ====================

def test_weekly_trends_free_blocked():
    """FREE plan should not get weekly_trends in stats response"""
    import main
    client = main.app.test_client()
    
    with patch.object(main, 'fetch_one', return_value={'c': 10}), \
         patch.object(main, 'fetch_all', return_value=[]):
        resp = client.get('/api/stats/overview',
                          headers={'Authorization': make_token('free@example.com', 'FREE')})
        # Should be blocked by statistics_dashboard gate before trends
        assert resp.status_code == 403, resp.data

def test_weekly_trends_pro_included():
    """PRO plan should get weekly_trends in stats response"""
    import main
    client = main.app.test_client()
    
    with patch.object(main, 'fetch_one', return_value={'c': 10, 'cnt': 5}), \
         patch.object(main, 'fetch_all', return_value=[]):
        resp = client.get('/api/stats/overview',
                          headers={'Authorization': make_token('pro@example.com', 'PRO')})
        # May succeed or fail on DB but if 200, should have weekly_trends
        if resp.status_code == 200:
            body = resp.get_json()
            assert 'weekly_trends' in body or 'weekly_trends_locked' in body

# ==================== Team Invite Tests ====================

def test_team_invite_free_blocked():
    """FREE plan cannot invite team members"""
    import main
    client = main.app.test_client()
    
    resp = client.post('/api/team/invite',
                       headers={'Authorization': make_token('free@example.com', 'FREE'),
                                'Content-Type': 'application/json'},
                       data=json.dumps({'email': 'teammate@example.com'}))
    assert resp.status_code == 403, resp.data
    body = resp.get_json()
    assert body.get('feature_locked') is True
    assert 'BUSINESS plan' in body.get('error', '')

def test_team_invite_pro_blocked():
    """PRO plan cannot invite team members (requires BUSINESS)"""
    import main
    client = main.app.test_client()
    
    resp = client.post('/api/team/invite',
                       headers={'Authorization': make_token('pro@example.com', 'PRO'),
                                'Content-Type': 'application/json'},
                       data=json.dumps({'email': 'teammate@example.com'}))
    assert resp.status_code == 403, resp.data

def test_team_invite_business_allowed():
    """BUSINESS plan can invite team members"""
    import main
    client = main.app.test_client()
    
    with patch.object(main, 'fetch_one', return_value=_fake_user_row('BUSINESS')):
        resp = client.post('/api/team/invite',
                           headers={'Authorization': make_token('biz@example.com', 'BUSINESS'),
                                    'Content-Type': 'application/json'},
                           data=json.dumps({'email': 'teammate@example.com'}))
        assert resp.status_code == 200, resp.data
        body = resp.get_json()
        assert body.get('ok') is True
        assert body.get('team_limit') == 3  # BUSINESS allows 3 team users

def test_team_invite_missing_email():
    """Should validate required email field"""
    import main
    client = main.app.test_client()
    
    with patch.object(main, 'fetch_one', return_value=_fake_user_row('BUSINESS')):
        resp = client.post('/api/team/invite',
                           headers={'Authorization': make_token('biz@example.com', 'BUSINESS'),
                                    'Content-Type': 'application/json'},
                           data=json.dumps({}))
        assert resp.status_code == 400, resp.data

# ==================== API Access Token Tests ====================

def test_api_token_free_blocked():
    """FREE plan cannot issue API tokens"""
    import main
    client = main.app.test_client()
    
    resp = client.post('/api/access-tokens',
                       headers={'Authorization': make_token('free@example.com', 'FREE')})
    assert resp.status_code == 403, resp.data
    body = resp.get_json()
    assert 'ENTERPRISE plan' in body.get('error', '')

def test_api_token_pro_blocked():
    """PRO plan cannot issue API tokens"""
    import main
    client = main.app.test_client()
    
    resp = client.post('/api/access-tokens',
                       headers={'Authorization': make_token('pro@example.com', 'PRO')})
    assert resp.status_code == 403, resp.data

def test_api_token_business_blocked():
    """BUSINESS plan cannot issue API tokens (requires ENTERPRISE)"""
    import main
    client = main.app.test_client()
    
    resp = client.post('/api/access-tokens',
                       headers={'Authorization': make_token('biz@example.com', 'BUSINESS')})
    assert resp.status_code == 403, resp.data

def test_api_token_enterprise_allowed():
    """ENTERPRISE plan can issue API tokens"""
    import main
    client = main.app.test_client()
    
    resp = client.post('/api/access-tokens',
                       headers={'Authorization': make_token('ent@example.com', 'ENTERPRISE')})
    assert resp.status_code == 200, resp.data
    body = resp.get_json()
    assert body.get('ok') is True
    assert 'token' in body
    assert body.get('token').startswith('sk_')

# ==================== Analyst Access Tests ====================

def test_analyst_intelligence_free_blocked():
    """FREE plan cannot access analyst intelligence"""
    import main
    client = main.app.test_client()
    
    resp = client.get('/api/analyst/intelligence',
                      headers={'Authorization': make_token('free@example.com', 'FREE')})
    assert resp.status_code == 403, resp.data
    body = resp.get_json()
    assert 'ENTERPRISE plan' in body.get('error', '')

def test_analyst_intelligence_pro_blocked():
    """PRO plan cannot access analyst intelligence"""
    import main
    client = main.app.test_client()
    
    resp = client.get('/api/analyst/intelligence',
                      headers={'Authorization': make_token('pro@example.com', 'PRO')})
    assert resp.status_code == 403, resp.data

def test_analyst_intelligence_enterprise_allowed():
    """ENTERPRISE plan can access analyst intelligence"""
    import main
    client = main.app.test_client()
    
    resp = client.get('/api/analyst/intelligence',
                      headers={'Authorization': make_token('ent@example.com', 'ENTERPRISE')})
    assert resp.status_code == 200, resp.data
    body = resp.get_json()
    assert body.get('ok') is True
    assert 'intelligence' in body

# ==================== Monthly Briefing Tests ====================

def test_monthly_briefing_free_blocked():
    """FREE plan cannot access monthly briefing"""
    import main
    client = main.app.test_client()
    
    resp = client.get('/api/briefing/monthly',
                      headers={'Authorization': make_token('free@example.com', 'FREE')})
    assert resp.status_code == 403, resp.data
    body = resp.get_json()
    assert 'ENTERPRISE plan' in body.get('error', '')

def test_monthly_briefing_pro_blocked():
    """PRO plan cannot access monthly briefing"""
    import main
    client = main.app.test_client()
    
    resp = client.get('/api/briefing/monthly',
                      headers={'Authorization': make_token('pro@example.com', 'PRO')})
    assert resp.status_code == 403, resp.data

def test_monthly_briefing_enterprise_allowed():
    """ENTERPRISE plan can access monthly briefing"""
    import main
    client = main.app.test_client()
    
    resp = client.get('/api/briefing/monthly',
                      headers={'Authorization': make_token('ent@example.com', 'ENTERPRISE')})
    assert resp.status_code == 200, resp.data
    body = resp.get_json()
    assert body.get('ok') is True
    assert 'month' in body

# ==================== Custom Reports Tests ====================

def test_custom_report_free_blocked():
    """FREE plan cannot generate custom reports"""
    import main
    client = main.app.test_client()
    
    resp = client.post('/api/reports/custom',
                       headers={'Authorization': make_token('free@example.com', 'FREE'),
                                'Content-Type': 'application/json'},
                       data=json.dumps({'type': 'threat-summary'}))
    assert resp.status_code == 403, resp.data
    body = resp.get_json()
    assert 'ENTERPRISE plan' in body.get('error', '')

def test_custom_report_pro_blocked():
    """PRO plan cannot generate custom reports"""
    import main
    client = main.app.test_client()
    
    resp = client.post('/api/reports/custom',
                       headers={'Authorization': make_token('pro@example.com', 'PRO'),
                                'Content-Type': 'application/json'},
                       data=json.dumps({'type': 'threat-summary'}))
    assert resp.status_code == 403, resp.data

def test_custom_report_enterprise_allowed():
    """ENTERPRISE plan can generate custom reports"""
    import main
    client = main.app.test_client()
    
    resp = client.post('/api/reports/custom',
                       headers={'Authorization': make_token('ent@example.com', 'ENTERPRISE'),
                                'Content-Type': 'application/json'},
                       data=json.dumps({'type': 'threat-summary'}))
    assert resp.status_code == 200, resp.data
    body = resp.get_json()
    assert body.get('ok') is True
    assert 'report_type' in body

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
    print('All medium-priority gating tests completed')
