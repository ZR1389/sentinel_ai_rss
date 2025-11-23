#!/usr/bin/env python3
"""Tests for route analysis endpoint gating.

Route analysis is a BUSINESS plan feature. Tests verify:
- FREE/PRO plans are blocked
- BUSINESS/ENTERPRISE plans are allowed
- Decorator-based gating with logging
"""
import os
import jwt
import json
import datetime
from unittest.mock import patch
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

def test_route_analysis_blocked_on_free():
    import main
    client = main.app.test_client()
    with patch.object(main, 'fetch_one', return_value=_fake_user_row('FREE')):
        resp = client.post('/api/travel-risk/route-analysis',
                           headers={'Authorization': make_token('free@example.com','FREE'), 'Content-Type':'application/json'},
                           data=json.dumps({'waypoints': [{'lat':0,'lon':0}]}))
        assert resp.status_code == 403, resp.data
        body = resp.get_json()
        assert body.get('feature_locked') is True
        assert 'Route Analysis' in body.get('error','') or 'route analysis' in body.get('error','').lower()
        assert body.get('required_plan') == 'BUSINESS'

def test_route_analysis_blocked_on_pro():
    import main
    client = main.app.test_client()
    with patch.object(main, 'fetch_one', return_value=_fake_user_row('PRO')):
        resp = client.post('/api/travel-risk/route-analysis',
                           headers={'Authorization': make_token('pro@example.com','PRO'), 'Content-Type':'application/json'},
                           data=json.dumps({'waypoints': [{'lat':0,'lon':0}]}))
        assert resp.status_code == 403, resp.data
        body = resp.get_json()
        assert body.get('feature_locked') is True
        assert body.get('required_plan') == 'BUSINESS'

def test_route_analysis_allowed_on_business():
    import main
    client = main.app.test_client()
    with patch.object(main, 'fetch_one', return_value=_fake_user_row('BUSINESS')):
        resp = client.post('/api/travel-risk/route-analysis',
                           headers={'Authorization': make_token('biz@example.com','BUSINESS'), 'Content-Type':'application/json'},
                           data=json.dumps({'waypoints': [{'lat':0,'lon':0}]}))
        assert resp.status_code == 200, resp.data
        body = resp.get_json()
        assert body.get('ok') is True
        assert 'analysis' in body

def test_route_analysis_allowed_on_enterprise():
    import main
    client = main.app.test_client()
    with patch.object(main, 'fetch_one', return_value=_fake_user_row('ENTERPRISE')):
        resp = client.post('/api/travel-risk/route-analysis',
                           headers={'Authorization': make_token('ent@example.com','ENTERPRISE'), 'Content-Type':'application/json'},
                           data=json.dumps({'waypoints': [{'lat':10,'lon':20}, {'lat':11,'lon':21}]}))
        assert resp.status_code == 200, resp.data
        body = resp.get_json()
        assert body.get('ok') is True
        assert 'analysis' in body
        assert body['analysis']['waypoint_count'] == 2

def test_route_analysis_requires_waypoints():
    import main
    client = main.app.test_client()
    with patch.object(main, 'fetch_one', return_value=_fake_user_row('BUSINESS')):
        resp = client.post('/api/travel-risk/route-analysis',
                           headers={'Authorization': make_token('biz@example.com','BUSINESS'), 'Content-Type':'application/json'},
                           data=json.dumps({}))
        assert resp.status_code == 400, resp.data
        body = resp.get_json()
        assert 'waypoints required' in body.get('error','')

if __name__ == '__main__':
    # Run tests manually
    for name, fn in list(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn(); print('✓', name)
    print('All route analysis gating tests completed')
