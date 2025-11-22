import types
import json
from flask import g

# Import application
import main

# Snapshot originals we will monkeypatch
_original_fetch_one = getattr(main, 'fetch_one', None)
_original_fetch_all = getattr(main, 'fetch_all', None)
_original_execute = getattr(main, 'execute', None)

# In-memory state
USERS = {
    'free@example.com': {
        'id': 1,
        'email': 'free@example.com',
        'plan': 'FREE',
        'is_trial': False,
        'lifetime_chat_messages': 0,
    },
    'pro@example.com': {
        'id': 2,
        'email': 'pro@example.com',
        'plan': 'PRO',
        'is_trial': False,
    }
}
FEATURE_USAGE = {  # (user_id, feature, period_start) -> usage_count
}

# Simple period key (month start) static for tests
import datetime
PERIOD_START = datetime.date.today().replace(day=1)

# Helper SQL recognizers
def _mock_fetch_one(sql, params):
    sql_low = sql.lower()
    if 'from users where email' in sql_low:
        email = params[0]
        user = USERS.get(email)
        if not user:
            return None
        # emulate dict row
        return user
    if 'select usage_count from feature_usage' in sql_low:
        # monthly usage
        if 'feature=' in sql_low:
            if isinstance(params, tuple) and len(params) == 2:
                # pattern from sentinel_chat monthly path
                user_id, feature = params
            else:
                # pattern with subselect (user_id derived from email)
                email, feature = params
                user_id = USERS[email]['id']
            key = (user_id, feature, PERIOD_START)
            usage = FEATURE_USAGE.get(key, 0)
            return {'usage_count': usage}
    if 'select id, lifetime_chat_messages from users where email' in sql_low:
        email = params[0]
        user = USERS.get(email)
        return {'id': user['id'], 'lifetime_chat_messages': user.get('lifetime_chat_messages', 0)} if user else None
    if 'select id from users where email' in sql_low:
        email = params[0]
        user = USERS.get(email)
        return {'id': user['id']} if user else None
    return None

def _mock_fetch_all(sql, params=None):
    sql_low = sql.lower()
    if 'from alerts' in sql_low and 'make_interval' in sql_low:
        # Return few fake alert rows with lat/lon
        return [
            {'uuid': 'a1', 'published': '2025-11-01T00:00:00Z', 'source': 'src', 'title': 'T1', 'link': 'L', 'region': 'R', 'country': 'C', 'city': 'X', 'threat_level': 'high', 'score': 70, 'confidence': 80, 'lat': 10.0, 'lon': 20.0},
            {'uuid': 'a2', 'published': '2025-11-02T00:00:00Z', 'source': 'src', 'title': 'T2', 'link': 'L', 'region': 'R', 'country': 'C', 'city': 'Y', 'threat_level': 'medium', 'score': 40, 'confidence': 60, 'lat': 11.0, 'lon': 21.0},
        ]
    return []

def _mock_execute(sql, params=None):
    sql_low = sql.lower()
    if 'update users set lifetime_chat_messages' in sql_low:
        user_id = params[0]
        for u in USERS.values():
            if u['id'] == user_id:
                u['lifetime_chat_messages'] = u.get('lifetime_chat_messages', 0) + 1
    if 'increment_feature_usage' in sql_low:
        user_id, feature = params
        key = (user_id, feature, PERIOD_START)
        FEATURE_USAGE[key] = FEATURE_USAGE.get(key, 0) + 1

# Monkeypatch main module attributes
main.fetch_one = _mock_fetch_one
main.fetch_all = _mock_fetch_all
main.execute = _mock_execute

# Monkeypatch plan feature lookup to static mapping for test speed
def _test_get_plan_feature(plan, feature, default=None):
    plan = plan.upper()
    if plan == 'FREE':
        mapping = {
            'chat_messages_lifetime': 3,
            'chat_messages_monthly': 0,
            'map_access_days': 2,
        }
    else:  # PRO
        mapping = {
            'chat_messages_monthly': 500,
            'chat_messages_lifetime': None,
            'map_access_days': 30,
        }
    return mapping.get(feature, default)

main.get_plan_feature = _test_get_plan_feature

# get_plan_limits needed (used in sentinel_chat)
import plan_utils
original_get_plan_limits = plan_utils.get_plan_limits

def _test_get_plan_limits(email):
    user = USERS[email]
    plan = user['plan']
    if plan == 'FREE':
        return {'plan': 'FREE', 'chat_messages_per_month': 0}
    return {'plan': 'PRO', 'chat_messages_per_month': 500}

plan_utils.get_plan_limits = _test_get_plan_limits

# ---------- Tests ----------

def test_free_chat_lifetime_quota():
    client = main.app.test_client()
    # send three messages
    for i in range(1, 4):
        resp = client.post('/api/sentinel-chat', json={'message': f'msg {i}'}, headers={'X-Debug-Email': 'free@example.com'})
        # Work around login decorator by manually setting g.user_email via request context
        if resp.status_code == 401:  # If decorator enforced auth, call underlying
            with main.app.test_request_context('/api/sentinel-chat', method='POST', json={'message': f'msg {i}'}):
                g.user_email = 'free@example.com'
                resp = main.sentinel_chat()  # Already plan-specific now
        data = resp.get_json()
        assert data['ok'] is True
    # fourth should fail
    with main.app.test_request_context('/api/sentinel-chat', method='POST', json={'message': 'msg 4'}):
        g.user_email = 'free@example.com'
        resp = main.sentinel_chat()
        assert resp.status_code == 403
        data = resp.get_json()
        assert data['feature_locked'] is True


def test_pro_chat_monthly_usage_increment():
    client = main.app.test_client()
    # initial usage 0
    with main.app.test_request_context('/api/sentinel-chat', method='POST', json={'message': 'hello'}):
        g.user_email = 'pro@example.com'
        resp = main.sentinel_chat()
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['usage']['used'] == 1
    # second increments
    with main.app.test_request_context('/api/sentinel-chat', method='POST', json={'message': 'world'}):
        g.user_email = 'pro@example.com'
        resp = main.sentinel_chat()
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['usage']['used'] == 2


def test_free_map_alerts_gated_window_violation():
    with main.app.test_request_context('/api/map-alerts/gated?days=30', method='GET'):
        g.user_email = 'free@example.com'
        resp = main.map_alerts_gated()
        assert resp.status_code == 403
        data = resp.get_json()
        assert data['feature_locked'] is True


def test_pro_map_alerts_gated_success():
    with main.app.test_request_context('/api/map-alerts/gated?days=30', method='GET'):
        g.user_email = 'pro@example.com'
        resp = main.map_alerts_gated()
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['ok'] is True
        assert data['window_days'] == 30

# Cleanup monkeypatches (optional)

def teardown_module(module):
    plan_utils.get_plan_limits = original_get_plan_limits
    main.fetch_one = _original_fetch_one
    main.fetch_all = _original_fetch_all
    main.execute = _original_execute
