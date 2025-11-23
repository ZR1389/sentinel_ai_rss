"""Reusable feature gating decorators.

Provides @feature_required(feature_name, required_plan=None) to enforce plan features
consistently across endpoints. Falls back to JWT plan first, then DB lookup, then FREE.
Logs denials via log_security_event.
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

def feature_required(feature_name: str, required_plan: Optional[str] = None):
    """Decorator enforcing that a plan feature is enabled.

    Args:
        feature_name: Key in PLAN_FEATURES.
        required_plan: If provided, returned in denial payload.
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
            return f(*args, **kwargs)
        return wrapper
    return decorator

__all__ = ['feature_required']