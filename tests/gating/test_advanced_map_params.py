"""
Test advanced map parameter enforcement and export format tiers.

Tests runtime enforcement of:
- map_custom_filters (BUSINESS+)
- map_historical_playback (BUSINESS+)
- map_comparison_mode (BUSINESS+)
- map_export format tiers ('csv' for PRO, 'all' for BUSINESS+)

These tests avoid real DB operations by monkeypatching fetch_all and providing fake JWTs.
"""
import os
import jwt
import json
import datetime
from unittest.mock import patch
from core.config import CONFIG

JWT_SECRET = CONFIG.security.jwt_secret or 'testsecret'

def make_token(email: str, plan: str):
    """Create test JWT token."""
    payload = {
        'user_email': email,
        'plan': plan,
        'type': 'access',
        'exp': datetime.datetime.utcnow() + datetime.timedelta(minutes=5)
    }
    return 'Bearer ' + jwt.encode(payload, JWT_SECRET, algorithm='HS256')

def _fake_user_row(plan: str):
    """Fake user DB row."""
    return {'id': 1, 'email': 'test@example.com', 'plan': plan}

def _fake_fetch_all_empty(*args, **kwargs):
    """Return empty list for fetch_all (no alerts)."""
    return []


def test_map_custom_filters_free_denied():
    """FREE plan should be denied custom_filter parameter."""
    import main
    client = main.app.test_client()
    
    with patch.object(main, 'fetch_all', side_effect=_fake_fetch_all_empty):
        response = client.get('/api/map-alerts?custom_filter=advanced_logic',
                            headers={'Authorization': make_token('free@test.com', 'FREE')})
    
    assert response.status_code == 403
    data = json.loads(response.data)
    assert data['feature_locked'] is True
    assert data['feature'] == 'map_custom_filters'
    assert data['required_plan'] == 'BUSINESS'


def test_map_custom_filters_pro_denied():
    """PRO plan should be denied custom_filter parameter."""
    import main
    client = main.app.test_client()
    
    with patch.object(main, 'fetch_all', side_effect=_fake_fetch_all_empty):
        response = client.get('/api/map-alerts?custom_filter=advanced_logic',
                            headers={'Authorization': make_token('pro@test.com', 'PRO')})
    
    assert response.status_code == 403
    data = json.loads(response.data)
    assert data['feature'] == 'map_custom_filters'
    assert data['required_plan'] == 'BUSINESS'


def test_map_custom_filters_business_allowed():
    """BUSINESS plan should allow custom_filter parameter."""
    import main
    client = main.app.test_client()
    
    with patch.object(main, 'fetch_all', side_effect=_fake_fetch_all_empty):
        response = client.get('/api/map-alerts?custom_filter=advanced_logic&limit=10',
                            headers={'Authorization': make_token('business@test.com', 'BUSINESS')})
    
    # Should not be denied for feature access
    assert response.status_code in (200, 400, 500)
    if response.status_code != 200:
        data = json.loads(response.data)
        # Ensure it's not a feature gate denial
        assert 'feature_locked' not in data or data.get('feature') != 'map_custom_filters'


def test_map_playback_mode_free_denied():
    """FREE plan should be denied playback_mode parameter."""
    import main
    client = main.app.test_client()
    
    with patch.object(main, 'fetch_all', side_effect=_fake_fetch_all_empty):
        response = client.get('/api/map-alerts?playback_mode=timeline',
                            headers={'Authorization': make_token('free@test.com', 'FREE')})
    
    assert response.status_code == 403
    data = json.loads(response.data)
    assert data['feature_locked'] is True
    assert data['feature'] == 'map_historical_playback'
    assert data['required_plan'] == 'BUSINESS'


def test_map_playback_mode_enterprise_allowed():
    """ENTERPRISE plan should allow playback_mode parameter."""
    import main
    client = main.app.test_client()
    
    with patch.object(main, 'fetch_all', side_effect=_fake_fetch_all_empty):
        response = client.get('/api/map-alerts?playback_mode=timeline&limit=10',
                            headers={'Authorization': make_token('enterprise@test.com', 'ENTERPRISE')})
    
    assert response.status_code in (200, 400, 500)
    if response.status_code != 200:
        data = json.loads(response.data)
        assert 'feature_locked' not in data or data.get('feature') != 'map_historical_playback'


def test_map_comparison_baseline_pro_denied():
    """PRO plan should be denied comparison_baseline parameter."""
    import main
    client = main.app.test_client()
    
    with patch.object(main, 'fetch_all', side_effect=_fake_fetch_all_empty):
        response = client.get('/api/map-alerts?comparison_baseline=2024-01-01',
                            headers={'Authorization': make_token('pro@test.com', 'PRO')})
    
    assert response.status_code == 403
    data = json.loads(response.data)
    assert data['feature_locked'] is True
    assert data['feature'] == 'map_comparison_mode'
    assert data['required_plan'] == 'BUSINESS'


def test_map_comparison_business_allowed():
    """BUSINESS plan should allow comparison_baseline parameter."""
    import main
    client = main.app.test_client()
    
    with patch.object(main, 'fetch_all', side_effect=_fake_fetch_all_empty):
        response = client.get('/api/map-alerts?comparison_baseline=2024-01-01&limit=10',
                            headers={'Authorization': make_token('business@test.com', 'BUSINESS')})
    
    assert response.status_code in (200, 400, 500)
    if response.status_code != 200:
        data = json.loads(response.data)
        assert 'feature_locked' not in data or data.get('feature') != 'map_comparison_mode'


def test_map_alerts_gated_custom_filter_enforcement():
    """Authenticated gated endpoint should enforce custom_filter for FREE/PRO."""
    import main
    client = main.app.test_client()
    
    with patch.object(main, 'fetch_one', return_value=_fake_user_row('FREE')):
        with patch.object(main, 'fetch_all', side_effect=_fake_fetch_all_empty):
            response = client.get('/api/map-alerts/gated?custom_filter=logic',
                                headers={'Authorization': make_token('free@test.com', 'FREE')})
    
    assert response.status_code == 403
    data = json.loads(response.data)
    assert data['feature'] == 'map_custom_filters'
    assert data['required_plan'] == 'BUSINESS'


def test_map_alerts_gated_playback_business_allowed():
    """Gated endpoint should allow playback_mode for BUSINESS."""
    import main
    client = main.app.test_client()
    
    with patch.object(main, 'fetch_one', return_value=_fake_user_row('BUSINESS')):
        with patch.object(main, 'fetch_all', side_effect=_fake_fetch_all_empty):
            response = client.get('/api/map-alerts/gated?playback_mode=timeline&days=30',
                                headers={'Authorization': make_token('business@test.com', 'BUSINESS')})
    
    # Should succeed or fail for non-feature reasons
    assert response.status_code in (200, 400, 500)
    if response.status_code != 200:
        data = json.loads(response.data)
        assert 'feature_locked' not in data or data.get('feature') != 'map_historical_playback'


def test_export_alerts_csv_pro_allowed():
    """PRO plan should allow CSV export."""
    import main
    client = main.app.test_client()
    
    with patch.object(main, 'fetch_one', return_value=_fake_user_row('PRO')):
        response = client.post('/api/export/alerts',
                             headers={'Authorization': make_token('pro@test.com', 'PRO'),
                                    'Content-Type': 'application/json'},
                             data=json.dumps({'format': 'csv', 'alert_ids': [1, 2, 3]}))
    
    # Should succeed (format tier check passes)
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['ok'] is True
    assert data['format'] == 'csv'


def test_export_alerts_geojson_pro_denied():
    """PRO plan should be denied GeoJSON export (requires BUSINESS)."""
    import main
    client = main.app.test_client()
    
    with patch.object(main, 'fetch_one', return_value=_fake_user_row('PRO')):
        response = client.post('/api/export/alerts',
                             headers={'Authorization': make_token('pro@test.com', 'PRO'),
                                    'Content-Type': 'application/json'},
                             data=json.dumps({'format': 'geojson', 'alert_ids': [1, 2, 3]}))
    
    assert response.status_code == 403
    data = json.loads(response.data)
    assert data['feature_locked'] is True
    assert data['required_plan'] == 'BUSINESS'
    assert 'allowed_formats' in data
    assert data['allowed_formats'] == ['csv']


def test_export_alerts_shapefile_business_allowed():
    """BUSINESS plan should allow all export formats."""
    import main
    client = main.app.test_client()
    
    with patch.object(main, 'fetch_one', return_value=_fake_user_row('BUSINESS')):
        response = client.post('/api/export/alerts',
                             headers={'Authorization': make_token('business@test.com', 'BUSINESS'),
                                    'Content-Type': 'application/json'},
                             data=json.dumps({'format': 'shapefile', 'alert_ids': [1, 2, 3]}))
    
    # Should succeed (BUSINESS has 'all' formats)
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['ok'] is True
    assert data['format'] == 'shapefile'


def test_export_alerts_kml_enterprise_allowed():
    """ENTERPRISE plan should allow all export formats."""
    import main
    client = main.app.test_client()
    
    with patch.object(main, 'fetch_one', return_value=_fake_user_row('ENTERPRISE')):
        response = client.post('/api/export/alerts',
                             headers={'Authorization': make_token('enterprise@test.com', 'ENTERPRISE'),
                                    'Content-Type': 'application/json'},
                             data=json.dumps({'format': 'kml', 'alert_ids': [1, 2, 3]}))
    
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['ok'] is True
    assert data['format'] == 'kml'


def test_export_alerts_free_denied():
    """FREE plan should be denied export feature entirely."""
    import main
    client = main.app.test_client()
    
    with patch.object(main, 'fetch_one', return_value=_fake_user_row('FREE')):
        response = client.post('/api/export/alerts',
                             headers={'Authorization': make_token('free@test.com', 'FREE'),
                                    'Content-Type': 'application/json'},
                             data=json.dumps({'format': 'csv', 'alert_ids': [1, 2]}))
    
    assert response.status_code == 403
    data = json.loads(response.data)
    assert data['feature_locked'] is True
    # Should be denied by @feature_required decorator before format check
    assert 'required_plan' in data


def test_advanced_params_without_auth_denied():
    """Unauthenticated requests with advanced params should be denied."""
    import main
    client = main.app.test_client()
    
    with patch.object(main, 'fetch_all', side_effect=_fake_fetch_all_empty):
        response = client.get('/api/map-alerts?custom_filter=advanced')
    
    # Should deny with FREE plan fallback
    assert response.status_code == 403
    data = json.loads(response.data)
    assert data['feature_locked'] is True
    assert data['plan'] == 'FREE'


if __name__ == '__main__':
    # Run tests with pytest if available, otherwise simple execution
    try:
        import pytest
        pytest.main([__file__, '-v'])
    except ImportError:
        print("Running tests without pytest...")
        test_map_custom_filters_free_denied()
        test_map_custom_filters_pro_denied()
        test_map_custom_filters_business_allowed()
        test_map_playback_mode_free_denied()
        test_map_playback_mode_enterprise_allowed()
        test_map_comparison_baseline_pro_denied()
        test_map_comparison_business_allowed()
        test_map_alerts_gated_custom_filter_enforcement()
        test_map_alerts_gated_playback_business_allowed()
        test_export_alerts_csv_pro_allowed()
        test_export_alerts_geojson_pro_denied()
        test_export_alerts_shapefile_business_allowed()
        test_export_alerts_kml_enterprise_allowed()
        test_export_alerts_free_denied()
        test_advanced_params_without_auth_denied()
        print("✓ All tests passed!")
