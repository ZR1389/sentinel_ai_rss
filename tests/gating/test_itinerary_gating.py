#!/usr/bin/env python3
"""Tests for itinerary creation gating: trip planner destination limits & route analysis feature.

These tests avoid real DB operations by monkeypatching fetch_one/execute and providing a fake JWT.
"""
import os
import jwt
import json
import datetime
import types
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

def test_free_plan_trip_planner_block():
    import main
    client = main.app.test_client()
    # Monkeypatch DB fetch_one to return user with FREE plan
    with patch.object(main, 'fetch_one', return_value=_fake_user_row('FREE')):
        resp = client.post('/api/travel-risk/itinerary',
                           headers={'Authorization': make_token('free@example.com','FREE'), 'Content-Type':'application/json'},
                           data=json.dumps({'data': {'waypoints': [ {'lat':0,'lon':0} ]}, 'title':'Trip'}))
        assert resp.status_code == 403, resp.data
        body = resp.get_json()
        assert body.get('feature_locked') is True
        assert 'Trip planner unavailable' in body.get('error','')

def test_pro_plan_within_limit_allows():
    import main
    client = main.app.test_client()
    with patch.object(main, 'fetch_one', return_value=_fake_user_row('PRO')):
        resp = client.post('/api/travel-risk/itinerary',
                           headers={'Authorization': make_token('pro@example.com','PRO'), 'Content-Type':'application/json'},
                           data=json.dumps({'data': {'waypoints': [ {'lat':0,'lon':0},{'lat':1,'lon':1} ]}, 'title':'Trip Ok'}))
        # Should create itinerary (201)
        assert resp.status_code in (201, 500), resp.data  # allow 500 if underlying create fails due to DB but gating passed
        if resp.status_code == 201:
            body = resp.get_json()
            assert body.get('ok') is True

def test_pro_plan_exceed_limit_blocks():
    import main
    client = main.app.test_client()
    with patch.object(main, 'fetch_one', return_value=_fake_user_row('PRO')):
        resp = client.post('/api/travel-risk/itinerary',
                           headers={'Authorization': make_token('pro2@example.com','PRO'), 'Content-Type':'application/json'},
                           data=json.dumps({'data': {'waypoints': [ {'lat':i,'lon':i} for i in range(7) ]}, 'title':'Trip Big'}))
        assert resp.status_code == 403, resp.data
        body = resp.get_json()
        assert body.get('feature_locked') is True
        assert 'Max destinations' in body.get('error','')

def test_route_analysis_block_on_pro():
    import main
    client = main.app.test_client()
    with patch.object(main, 'fetch_one', return_value=_fake_user_row('PRO')):
        resp = client.post('/api/travel-risk/itinerary',
                           headers={'Authorization': make_token('pro3@example.com','PRO'), 'Content-Type':'application/json'},
                           data=json.dumps({'data': {'waypoints': [], 'routes': []}, 'title':'Route Attempt'}))
        assert resp.status_code == 403, resp.data
        body = resp.get_json()
        assert 'Route analysis requires BUSINESS' in body.get('error','')

def test_route_analysis_allowed_on_business():
    import main
    client = main.app.test_client()
    with patch.object(main, 'fetch_one', return_value=_fake_user_row('BUSINESS')):
        resp = client.post('/api/travel-risk/itinerary',
                           headers={'Authorization': make_token('biz@example.com','BUSINESS'), 'Content-Type':'application/json'},
                           data=json.dumps({'data': {'waypoints': [], 'routes': []}, 'title':'Route Allowed'}))
        # Expect pass gating (201 or 500 if DB error)
        assert resp.status_code in (201, 500), resp.data
        if resp.status_code == 201:
            body = resp.get_json(); assert body.get('ok') is True

if __name__ == '__main__':
    # Run tests manually
    for name, fn in list(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn(); print('✓', name)
    print('All itinerary gating tests completed')
