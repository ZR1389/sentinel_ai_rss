#!/usr/bin/env python3
"""Unit tests for feature gating decorators.

Tests feature_required, feature_limit, and feature_tier decorators in isolation
with mocked plan resolution and feature lookups.
"""
from unittest.mock import patch, MagicMock
from flask import Flask, g, jsonify
from utils.feature_decorators import feature_required, feature_limit, feature_tier

# Test Flask app
app = Flask(__name__)
app.config['TESTING'] = True

def test_feature_required_allows_when_enabled():
    """Test feature_required allows execution when feature is enabled."""
    with app.test_request_context():
        g.user_email = 'test@example.com'
        g.user_plan = 'PRO'
        
        @feature_required('test_feature', required_plan='PRO')
        def handler():
            return jsonify({'ok': True})
        
        with patch('utils.feature_decorators.get_plan_feature', return_value=True):
            with patch('utils.feature_decorators.log_security_event'):
                response = handler()
                assert response.get_json()['ok'] is True

def test_feature_required_denies_when_disabled():
    """Test feature_required denies when feature is disabled."""
    with app.test_request_context():
        g.user_email = 'test@example.com'
        g.user_plan = 'FREE'
        
        @feature_required('premium_feature', required_plan='PRO')
        def handler():
            return jsonify({'ok': True})
        
        with patch('utils.feature_decorators.get_plan_feature', return_value=False):
            with patch('utils.feature_decorators.log_security_event') as mock_log:
                response = handler()
                data = response.get_json()
                
                assert response.status_code == 403
                assert data['feature_locked'] is True
                assert data['required_plan'] == 'PRO'
                assert 'premium feature' in data['error'].lower()
                
                # Verify logging called
                mock_log.assert_called_once()
                call_kwargs = mock_log.call_args[1]
                assert call_kwargs['event_type'] == 'feature_denied'
                assert call_kwargs['email'] == 'test@example.com'

def test_feature_limit_allows_zero_usage_on_free():
    """Test feature_limit allows zero-usage requests on FREE plan when configured."""
    with app.test_request_context():
        g.user_email = 'free@example.com'
        g.user_plan = 'FREE'
        
        usage_count = 0
        @feature_limit('trip_planner_destinations', required_plan='PRO', 
                      usage_getter=lambda: usage_count, allow_zero_usage=True,
                      disabled_message='Trip planner unavailable on FREE plan')
        def handler():
            return jsonify({'ok': True})
        
        with patch('utils.feature_decorators.get_plan_feature', return_value=0):
            with patch('utils.feature_decorators.log_security_event'):
                response = handler()
                assert response.get_json()['ok'] is True

def test_feature_limit_denies_nonzero_usage_when_limit_zero():
    """Test feature_limit denies non-zero usage when limit is 0."""
    with app.test_request_context():
        g.user_email = 'free@example.com'
        g.user_plan = 'FREE'
        
        usage_count = 3
        @feature_limit('trip_planner_destinations', required_plan='PRO',
                      usage_getter=lambda: usage_count, allow_zero_usage=True,
                      disabled_message='Trip planner unavailable on FREE plan')
        def handler():
            return jsonify({'ok': True})
        
        with patch('utils.feature_decorators.get_plan_feature', return_value=0):
            with patch('utils.feature_decorators.log_security_event') as mock_log:
                response = handler()
                data = response.get_json()
                
                assert response.status_code == 403
                assert data['feature_locked'] is True
                assert data['required_plan'] == 'PRO'
                assert 'Trip planner unavailable' in data['error']
                
                mock_log.assert_called_once()

def test_feature_limit_allows_within_limit():
    """Test feature_limit allows when usage is within limit."""
    with app.test_request_context():
        g.user_email = 'pro@example.com'
        g.user_plan = 'PRO'
        
        usage_count = 3
        @feature_limit('saved_searches', required_plan='PRO',
                      usage_getter=lambda: usage_count)
        def handler():
            return jsonify({'ok': True})
        
        with patch('utils.feature_decorators.get_plan_feature', return_value=5):
            with patch('utils.feature_decorators.log_security_event'):
                response = handler()
                assert response.get_json()['ok'] is True

def test_feature_limit_denies_when_exceeded():
    """Test feature_limit denies when usage exceeds limit."""
    with app.test_request_context():
        g.user_email = 'pro@example.com'
        g.user_plan = 'PRO'
        
        usage_count = 7
        @feature_limit('saved_searches', required_plan='PRO',
                      usage_getter=lambda: usage_count,
                      limit_message_template='Max searches ({limit}) exceeded')
        def handler():
            return jsonify({'ok': True})
        
        with patch('utils.feature_decorators.get_plan_feature', return_value=5):
            with patch('utils.feature_decorators.log_security_event') as mock_log:
                response = handler()
                data = response.get_json()
                
                assert response.status_code == 403
                assert data['feature_locked'] is True
                assert data['limit'] == 5
                assert data['provided'] == 7
                assert 'Max searches (5) exceeded' in data['error']
                assert data['required_plan'] == 'BUSINESS'  # Auto-escalation from PRO
                
                mock_log.assert_called_once()
                call_kwargs = mock_log.call_args[1]
                assert 'Quota exceeded' in call_kwargs['details']

def test_feature_limit_allows_at_limit():
    """Test feature_limit allows when usage equals limit (not exceeded)."""
    with app.test_request_context():
        g.user_email = 'pro@example.com'
        g.user_plan = 'PRO'
        
        usage_count = 5
        @feature_limit('saved_searches', usage_getter=lambda: usage_count)
        def handler():
            return jsonify({'ok': True})
        
        with patch('utils.feature_decorators.get_plan_feature', return_value=5):
            with patch('utils.feature_decorators.log_security_event'):
                response = handler()
                assert response.get_json()['ok'] is True

def test_feature_tier_allows_matching_value():
    """Test feature_tier allows when plan value matches allowed values."""
    with app.test_request_context():
        g.user_email = 'business@example.com'
        g.user_plan = 'BUSINESS'
        
        @feature_tier('map_export', required_plan='BUSINESS', allow_values=['csv', 'all'])
        def handler():
            return jsonify({'ok': True})
        
        with patch('utils.feature_decorators.get_plan_feature', return_value='all'):
            with patch('utils.feature_decorators.log_security_event'):
                response = handler()
                assert response.get_json()['ok'] is True

def test_feature_tier_denies_non_matching_value():
    """Test feature_tier denies when plan value not in allowed values."""
    with app.test_request_context():
        g.user_email = 'pro@example.com'
        g.user_plan = 'PRO'
        
        @feature_tier('map_export', required_plan='BUSINESS', allow_values=['all'])
        def handler():
            return jsonify({'ok': True})
        
        with patch('utils.feature_decorators.get_plan_feature', return_value='csv'):
            with patch('utils.feature_decorators.log_security_event') as mock_log:
                response = handler()
                data = response.get_json()
                
                assert response.status_code == 403
                assert data['feature_locked'] is True
                assert data['required_plan'] == 'BUSINESS'
                
                mock_log.assert_called_once()

def test_feature_tier_allows_any_truthy_when_no_values():
    """Test feature_tier allows any truthy value when allow_values is None."""
    with app.test_request_context():
        g.user_email = 'pro@example.com'
        g.user_plan = 'PRO'
        
        @feature_tier('some_feature')
        def handler():
            return jsonify({'ok': True})
        
        with patch('utils.feature_decorators.get_plan_feature', return_value='any_value'):
            with patch('utils.feature_decorators.log_security_event'):
                response = handler()
                assert response.get_json()['ok'] is True

def test_plan_resolution_fallback():
    """Test plan resolution falls back to FREE when JWT plan missing."""
    with app.test_request_context():
        g.user_email = 'test@example.com'
        # No g.user_plan set
        
        @feature_required('test_feature')
        def handler():
            return jsonify({'ok': True})
        
        with patch('utils.feature_decorators.get_plan_feature', return_value=False):
            with patch('utils.feature_decorators.log_security_event'):
                response = handler()
                data = response.get_json()
                
                # Should deny and show FREE plan
                assert response.status_code == 403
                assert data['plan'] == 'FREE'

def test_feature_limit_auto_escalation_from_business():
    """Test auto-escalation suggests ENTERPRISE when current plan is BUSINESS."""
    with app.test_request_context():
        g.user_email = 'biz@example.com'
        g.user_plan = 'BUSINESS'
        
        usage_count = 20
        @feature_limit('saved_searches', usage_getter=lambda: usage_count)
        def handler():
            return jsonify({'ok': True})
        
        with patch('utils.feature_decorators.get_plan_feature', return_value=10):
            with patch('utils.feature_decorators.log_security_event'):
                response = handler()
                data = response.get_json()
                
                assert response.status_code == 403
                assert data['required_plan'] == 'ENTERPRISE'

if __name__ == '__main__':
    # Run tests manually
    import sys
    tests = [
        test_feature_required_allows_when_enabled,
        test_feature_required_denies_when_disabled,
        test_feature_limit_allows_zero_usage_on_free,
        test_feature_limit_denies_nonzero_usage_when_limit_zero,
        test_feature_limit_allows_within_limit,
        test_feature_limit_denies_when_exceeded,
        test_feature_limit_allows_at_limit,
        test_feature_tier_allows_matching_value,
        test_feature_tier_denies_non_matching_value,
        test_feature_tier_allows_any_truthy_when_no_values,
        test_plan_resolution_fallback,
        test_feature_limit_auto_escalation_from_business,
    ]
    
    passed = 0
    failed = 0
    for test_fn in tests:
        try:
            test_fn()
            print(f'✓ {test_fn.__name__}')
            passed += 1
        except Exception as e:
            print(f'✗ {test_fn.__name__}: {e}')
            failed += 1
    
    print(f'\n{passed} passed, {failed} failed')
    sys.exit(0 if failed == 0 else 1)
