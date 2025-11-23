"""Reusable feature gating decorators.

Provides @feature_required(feature_name, required_plan=None) to enforce plan features
consistently across endpoints. Falls back to JWT plan first, then DB lookup, then FREE.
Logs denials via log_security_event and tracks usage via feature_usage table.
"""
from functools import wraps
from typing import Optional, Callable
from flask import g, jsonify, make_response
import os

try:
    from config_data.plans import get_plan_feature
except Exception:  # pragma: no cover
    get_plan_feature = lambda plan, feat, default=None: default  # type: ignore

try:
    from security_log_utils import log_security_event
except Exception:  # pragma: no cover
    def log_security_event(**kwargs):  # type: ignore
        pass

def _get_user_id(email: Optional[str] = None) -> Optional[int]:
    """Get user ID from email for usage tracking."""
    if not email:
        email = getattr(g, 'user_email', None)
    if not email:
        return None
    
    try:
        from db_utils import fetch_one
        user = fetch_one("SELECT id FROM users WHERE email=%s", (email,))
        return user['id'] if user else None
    except Exception:
        return None

def _track_feature_usage(feature_name: str, user_id: Optional[int] = None, increment: int = 1) -> None:
    """Track feature usage in feature_usage table.
    
    Args:
        feature_name: Feature name to track (will be normalized)
        user_id: User ID (optional, will attempt to get from g.user_email)
        increment: Number of uses to record (default 1)
    """
    if user_id is None:
        user_id = _get_user_id()
    
    if user_id is None:
        return  # Can't track without user ID
    
    try:
        from db_utils import execute
        # Call the safe increment function from migration
        execute("SELECT increment_feature_usage_safe(%s, %s, %s)", (user_id, feature_name, increment))
    except Exception as e:
        # Non-critical: log but don't fail the request
        try:
            from logging_config import get_logger
            logger = get_logger("feature_decorators")
            logger.warning(f"Failed to track feature usage for {feature_name}: {e}")
        except Exception:
            pass

def _resolve_plan(email_getter: Callable[[], Optional[str]] | None = None) -> str:
    """Resolve user plan: JWT -> DB via plan_utils -> FREE."""
    # JWT first
    jwt_plan = getattr(g, 'user_plan', None)
    if jwt_plan:
        return str(jwt_plan).strip().upper()
    # DB lookup
    if email_getter:
        try:
            email = email_getter()
            if email:
                from plan_utils import get_plan_limits  # local import to avoid circular
                limits = get_plan_limits(email) or {}
                plan = (limits.get('plan') or 'FREE').upper()
                return plan
        except Exception:
            pass
    return os.getenv('DEFAULT_PLAN', 'FREE').strip().upper()

def feature_required(feature_name: str, required_plan: Optional[str] = None, track_usage: bool = True):
    """Decorator enforcing that a plan feature is enabled.

    Args:
        feature_name: Key in PLAN_FEATURES.
        required_plan: If provided, returned in denial payload.
        track_usage: If True, track successful usage in feature_usage table.
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            plan = _resolve_plan(lambda: getattr(g, 'user_email', None))
            allowed = bool(get_plan_feature(plan, feature_name, False))
            if not allowed:
                # Log denial
                log_security_event(
                    event_type='feature_denied',
                    email=getattr(g, 'user_email', None),
                    details=f'Feature {feature_name} denied for plan {plan}',
                )
                payload = {
                    'error': f'{feature_name.replace("_", " ").title()} requires {required_plan or "upgrade"} plan',
                    'feature_locked': True,
                    'feature': feature_name,
                    'plan': plan,
                }
                if required_plan:
                    payload['required_plan'] = required_plan
                return make_response(jsonify(payload), 403)
            
            # Track usage before executing function
            if track_usage:
                _track_feature_usage(feature_name)
            
            return f(*args, **kwargs)
        return wrapper
    return decorator

def feature_limit(feature_name: str, required_plan: Optional[str] = None, usage_getter: Optional[Callable[[], int]] = None, allow_zero_usage: bool = True, disabled_message: Optional[str] = None, limit_message_template: Optional[str] = None, track_usage: bool = True):
    """Decorator enforcing numeric feature limit (quota).

    If the plan feature value is a number and usage_getter() returns a count
    that exceeds the limit, deny. If feature value is falsy/None, treat as disabled.

    Args:
        feature_name: Feature key expected to have an integer limit.
        required_plan: Plan suggested for upgrade messaging.
        usage_getter: Callable returning current usage count (int).
        allow_zero_usage: If True, allow requests with zero usage even when limit is 0 (e.g., FREE plan empty itinerary).
        disabled_message: Custom error message when feature is disabled (limit==0). If None, generates from feature_name.
        limit_message_template: Template for limit exceeded message. Use {limit} placeholder. If None, auto-generates.
        track_usage: If True, track successful usage in feature_usage table.
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            plan = _resolve_plan(lambda: getattr(g, 'user_email', None))
            limit_val = get_plan_feature(plan, feature_name, None)
            
            # Get usage count
            used = 0
            if usage_getter:
                try:
                    used = int(usage_getter())
                except Exception:
                    used = 0
            
            # If limit is 0 or None, check if we should deny
            if limit_val in (None, 0):
                # Allow zero-usage requests if configured (e.g., empty itinerary on FREE plan)
                if allow_zero_usage and used == 0:
                    if track_usage:
                        _track_feature_usage(feature_name, increment=used)
                    return f(*args, **kwargs)
                # Otherwise deny feature access
                log_security_event(event_type='feature_denied', email=getattr(g, 'user_email', None), details=f'Quota feature {feature_name} disabled for plan {plan}, usage={used}')
                error_msg = disabled_message or f'{feature_name.replace("_", " ").title()} unavailable on {plan} plan'
                payload = {
                    'error': error_msg,
                    'feature_locked': True,
                    'feature': feature_name,
                    'plan': plan,
                }
                if required_plan:
                    payload['required_plan'] = required_plan
                return make_response(jsonify(payload), 403)
            
            # Check if usage exceeds limit
            if isinstance(limit_val, int) and used > limit_val:
                # Auto-escalate based on current plan
                if plan == 'PRO':
                    escalate = 'BUSINESS'
                elif plan == 'BUSINESS':
                    escalate = 'ENTERPRISE'
                elif plan == 'FREE':
                    escalate = required_plan or 'PRO'
                else:
                    escalate = required_plan or 'UPGRADE'
                
                log_security_event(event_type='feature_denied', email=getattr(g, 'user_email', None), details=f'Quota exceeded {feature_name} used={used} limit={limit_val} plan={plan}')
                if limit_message_template:
                    error_msg = limit_message_template.format(limit=limit_val)
                else:
                    error_msg = f'Max {feature_name.replace("_", " ")} ({limit_val}) exceeded'
                return make_response(jsonify({
                    'error': error_msg,
                    'feature_locked': True,
                    'feature': feature_name,
                    'plan': plan,
                    'limit': limit_val,
                    'provided': used,
                    'required_plan': escalate
                }), 403)
            
            # Track usage with the actual usage count
            if track_usage:
                _track_feature_usage(feature_name, increment=max(1, used))
            
            return f(*args, **kwargs)
        return wrapper
    return decorator

def feature_tier(feature_name: str, required_plan: Optional[str] = None, allow_values: Optional[list[str]] = None, track_usage: bool = True):
    """Decorator enforcing a tiered feature value.

    Example: map_export feature returns 'csv' or 'all'.
    allow_values restricts execution unless the plan's value is in the set.
    If allow_values is None treat any truthy value as enabled.
    
    Args:
        feature_name: Feature key to check.
        required_plan: Plan suggested for upgrade messaging.
        allow_values: List of acceptable values for the feature.
        track_usage: If True, track successful usage in feature_usage table.
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            plan = _resolve_plan(lambda: getattr(g, 'user_email', None))
            value = get_plan_feature(plan, feature_name, None)
            allowed = False
            if allow_values is None:
                allowed = bool(value)
            else:
                allowed = value in allow_values
            if not allowed:
                log_security_event(event_type='feature_denied', email=getattr(g, 'user_email', None), details=f'Tier feature {feature_name} value={value} not permitted plan={plan}')
                payload = {
                    'error': f'{feature_name.replace("_", " ").title()} requires {required_plan or "upgrade"} plan',
                    'feature_locked': True,
                    'feature': feature_name,
                    'plan': plan,
                }
                if required_plan:
                    payload['required_plan'] = required_plan
                return make_response(jsonify(payload), 403)
            
            # Track usage before executing function
            if track_usage:
                _track_feature_usage(feature_name)
            
            return f(*args, **kwargs)
        return wrapper
    return decorator

__all__ = ['feature_required', 'feature_limit', 'feature_tier']