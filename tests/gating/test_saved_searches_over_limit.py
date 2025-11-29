#!/usr/bin/env python3
"""Tests for saved_searches over-limit marking and persistence.

Mocks DB helpers to avoid real database reliance.
"""
import os
import jwt
import json
import datetime
from unittest.mock import patch
from core.config import CONFIG

JWT_SECRET = CONFIG.security.jwt_secret or 'testsecret'

def make_token(email: str, plan: str):
    payload = {
        'user_email': email,
        'plan': plan,
        'type': 'access',
        'exp': datetime.datetime.utcnow() + datetime.timedelta(minutes=5)
    }
    return 'Bearer ' + jwt.encode(payload, JWT_SECRET, algorithm='HS256')

# Fake rows builder
def _row(i):
    return {'id': i, 'name': f'Search {i}', 'query': {}, 'alert_enabled': True, 'alert_frequency': 'daily', 'created_at': datetime.datetime.utcnow()}

def test_saved_searches_over_limit_pro():
    import main
    client = main.app.test_client()
    rows = [_row(i) for i in range(1,6)]  # 5 searches, PRO limit = 3
    with patch.object(main, 'fetch_all', return_value=rows), \
         patch.object(main, 'fetch_one', return_value={'id':1,'plan':'PRO'}), \
         patch.object(main, 'execute', return_value=None):
        resp = client.get('/api/monitoring/searches', headers={'Authorization': make_token('pro@example.com','PRO')})
        assert resp.status_code == 200, resp.data
        body = resp.get_json()
        assert body['plan'] == 'PRO'
        assert body['limit'] == 3
        over = [s for s in body['searches'] if s.get('over_limit')]
        assert len(over) == 2  # searches 4 & 5
        # ensure alert_enabled false on over-limit
        assert all(not s['alert_enabled'] for s in over)

def test_saved_searches_unlimited_enterprise():
    import main
    client = main.app.test_client()
    rows = [_row(i) for i in range(1,11)]
    with patch.object(main, 'fetch_all', return_value=rows), \
         patch.object(main, 'fetch_one', return_value={'id':1,'plan':'ENTERPRISE'}), \
         patch.object(main, 'execute', return_value=None):
        resp = client.get('/api/monitoring/searches', headers={'Authorization': make_token('ent@example.com','ENTERPRISE')})
        assert resp.status_code == 200
        body = resp.get_json(); assert body['plan']=='ENTERPRISE'
        # Unlimited => no over_limit flags
        assert all(not s.get('over_limit') for s in body['searches'])

if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn(); print('✓', name)
    print('All saved_searches tests completed')
