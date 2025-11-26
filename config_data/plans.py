"""
Plan configuration and feature gates
"""

PLAN_FEATURES = {
    'FREE': {
        'chat_messages_monthly': 0,
        'chat_messages_lifetime': 3,
        'conversation_threads': 5,
        'messages_per_thread': 3,
        'can_archive_threads': False,
        'chat_export_pdf': False,
        'map_access_days': 2,
        'map_filters': False,
        'map_custom_filters': False,
        'map_historical_playback': False,
        'map_comparison_mode': False,
        'map_export': None,
        'pdf_exports_monthly': 1,
        'travel_assessments_lifetime': 1,
        'travel_assessments_monthly': 0,
        'trip_planner_destinations': 0,
        'route_analysis': False,
        'briefing_packages': False,
        'safe_zones_overlay': False,
        'saved_searches': 0,
        'email_alerts': False,
        'sms_alerts': False,
        'geofenced_alerts': False,
        'timeline_access': False,
        'timeline_days': 0,
        'statistics_dashboard': None,
        'weekly_trends': False,
        'support_level': 'email_48h',
        'team_users': 0,
        'custom_reports': False,
        'api_access': False,
        'analyst_access': False,
        'monthly_briefing': False,
    },
    'PRO': {
        'chat_messages_monthly': 500,
        'chat_messages_lifetime': None,
        'conversation_threads': 50,
        'messages_per_thread': 50,
        'can_archive_threads': True,
        'chat_export_pdf': True,
        'map_access_days': 30,
        'map_filters': True,
        'map_custom_filters': False,
        'map_historical_playback': False,
        'map_comparison_mode': False,
        'map_export': 'csv',
        'pdf_exports_monthly': 10,
        'travel_assessments_lifetime': None,
        'travel_assessments_monthly': None,
        'trip_planner_destinations': 5,
        'route_analysis': False,
        'briefing_packages': True,
        'safe_zones_overlay': False,
        'saved_searches': 3,
        'email_alerts': True,
        'sms_alerts': False,
        'geofenced_alerts': False,
        'timeline_access': True,
        'timeline_days': 30,
        'statistics_dashboard': 'basic',
        'weekly_trends': True,
        'support_level': 'email_24h',
        'team_users': 0,
        'custom_reports': False,
        'api_access': False,
        'analyst_access': False,
        'monthly_briefing': False,
    },
    'BUSINESS': {
        'chat_messages_monthly': 1000,
        'chat_messages_lifetime': None,
        'conversation_threads': 100,
        'messages_per_thread': 100,
        'can_archive_threads': True,
        'chat_export_pdf': True,
        'map_access_days': 90,
        'map_filters': True,
        'map_custom_filters': True,
        'map_historical_playback': True,
        'map_comparison_mode': True,
        'map_export': 'all',
        'pdf_exports_monthly': None,
        'travel_assessments_lifetime': None,
        'travel_assessments_monthly': None,
        'trip_planner_destinations': 10,
        'route_analysis': True,
        'briefing_packages': True,
        'safe_zones_overlay': True,
        'saved_searches': 10,
        'email_alerts': True,
        'sms_alerts': True,
        'geofenced_alerts': True,
        'timeline_access': True,
        'timeline_days': 90,
        'statistics_dashboard': 'advanced',
        'weekly_trends': True,
        'support_level': 'priority_24h',
        'team_users': 3,
        'custom_reports': False,
        'api_access': False,
        'analyst_access': False,
        'monthly_briefing': False,
    },
    'ENTERPRISE': {
        'chat_messages_monthly': 2500,
        'chat_messages_lifetime': None,
        'conversation_threads': None,
        'messages_per_thread': None,
        'can_archive_threads': True,
        'chat_export_pdf': True,
        'map_access_days': 365,
        'map_filters': True,
        'map_custom_filters': True,
        'map_historical_playback': True,
        'map_comparison_mode': True,
        'map_export': 'all',
        'pdf_exports_monthly': None,
        'travel_assessments_lifetime': None,
        'travel_assessments_monthly': None,
        'trip_planner_destinations': None,
        'route_analysis': True,
        'briefing_packages': True,
        'safe_zones_overlay': True,
        'saved_searches': None,
        'email_alerts': True,
        'sms_alerts': True,
        'geofenced_alerts': True,
        'timeline_access': True,
        'timeline_days': 365,
        'statistics_dashboard': 'custom',
        'weekly_trends': True,
        'support_level': 'analyst_4h',
        'team_users': None,
        'custom_reports': True,
        'api_access': True,
        'analyst_access': True,
        'monthly_briefing': True,
    }
}

PLAN_PRICING = {
    'FREE': 0,
    'PRO': 79,
    'BUSINESS': 149,
    'ENTERPRISE': 299
}

TRIAL_CONFIG = {
    'PRO': {'duration_days': 7, 'requires_card': True},
    'BUSINESS': {'duration_days': 7, 'requires_card': True},
    'ENTERPRISE': {'duration_days': 14, 'requires_card': False}
}

def get_plan_feature(plan: str, feature: str, default=None):
    plan = plan.upper() if plan else 'FREE'
    return PLAN_FEATURES.get(plan, PLAN_FEATURES['FREE']).get(feature, default)

def has_feature(plan: str, feature: str) -> bool:
    value = get_plan_feature(plan, feature)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    if value is None:
        return True
    return bool(value)

def get_feature_limit(plan: str, feature: str) -> int:
    value = get_plan_feature(plan, feature)
    if value is None:
        return float('inf')
    if isinstance(value, (int, float)):
        return int(value)
    return 0
