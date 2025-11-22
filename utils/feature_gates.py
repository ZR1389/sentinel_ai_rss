"""Feature gate checking and enforcement.
Adapted for psycopg2 (no SQLAlchemy session). Provides:
    - FeatureGateError for structured gate failures
    - check_feature_access / check_feature_limit helpers
    - requires_feature & check_usage_limit decorators (monthly + lifetime)
Existing naming retained for backward compatibility.
"""

import functools
import datetime
from typing import Callable
import psycopg2
from psycopg2.extras import RealDictCursor

from config import CONFIG
from config.plans import get_plan_feature, has_feature, get_feature_limit

DATABASE_URL = CONFIG.database.url

class FeatureGateError(Exception):
    """Raised when a feature gate check fails."""
    def __init__(self, message: str, required_plan: str | None = None, upgrade_url: str | None = None):
        self.message = message
        self.required_plan = required_plan or 'PRO'
        self.upgrade_url = upgrade_url or '/sentinel-ai#pricing'
        super().__init__(self.message)

def _conn():
    return psycopg2.connect(DATABASE_URL)

def _first_of_month():
    today = datetime.date.today()
    return today.replace(day=1)

def _get_user(email: str) -> dict | None:
    if not email:
        return None
    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT id, email, plan, is_trial, trial_ends_at,
                   lifetime_chat_messages, lifetime_travel_assessments
            FROM users WHERE email=%s
        """, (email,))
        return cur.fetchone()

def _get_monthly_usage(user_id: int, feature: str) -> int:
    period_start = _first_of_month()
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT usage_count FROM feature_usage
             WHERE user_id=%s AND feature=%s AND period_start=%s
        """, (user_id, feature, period_start))
        r = cur.fetchone()
        return int(r[0]) if r else 0

def _increment_monthly_usage(user_id: int, feature: str) -> None:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT increment_feature_usage(%s,%s)", (user_id, feature))
        conn.commit()

def _increment_lifetime(user_id: int, column: str) -> None:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(f"UPDATE users SET {column} = COALESCE({column},0)+1 WHERE id=%s", (user_id,))
        conn.commit()

def _suggest_upgrade(plan: str) -> str:
    order = ['FREE','PRO','BUSINESS','ENTERPRISE']
    try:
        idx = order.index(plan)
        return order[min(idx+1, len(order)-1)] if idx < len(order)-1 else plan
    except ValueError:
        return 'PRO'

def check_feature_access(user: dict | None, feature: str, raise_on_deny: bool = True) -> bool:
    plan = ((user or {}).get('plan') or 'FREE').upper()
    access = has_feature(plan, feature)
    if not access and raise_on_deny:
        # find first plan granting feature
        for candidate in ['PRO','BUSINESS','ENTERPRISE']:
            if has_feature(candidate, feature):
                raise FeatureGateError(f"This feature requires {candidate} plan or higher", required_plan=candidate)
        raise FeatureGateError("This feature requires an upgraded plan", required_plan='PRO')
    return access

def check_feature_limit(user: dict | None, feature: str, current_usage: int, raise_on_deny: bool = True) -> bool:
    plan = ((user or {}).get('plan') or 'FREE').upper()
    limit = get_feature_limit(plan, feature)
    if limit == float('inf'):
        return True
    within = current_usage < limit
    if not within and raise_on_deny:
        required = 'PRO' if plan == 'FREE' else ('BUSINESS' if plan == 'PRO' else 'ENTERPRISE')
        raise FeatureGateError(
            f"You've reached your {feature} limit of {limit}. Upgrade for more.",
            required_plan=required
        )
    return within

def requires_feature(feature: str):
    def decorator(fn: Callable):
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            from flask import jsonify, g
            email = getattr(g, 'user_email', None)
            user = _get_user(email)
            try:
                check_feature_access(user, feature, raise_on_deny=True)
            except FeatureGateError as e:
                return jsonify({'error': e.message,'required_plan': e.required_plan,'upgrade_url': e.upgrade_url,'feature_locked': True}), 403
            return fn(*args, **kwargs)
        return wrapped
    return decorator

def check_usage_limit(feature: str, increment: bool = True):
    def decorator(fn: Callable):
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            from flask import jsonify, g
            email = getattr(g, 'user_email', None)
            user = _get_user(email)
            if not user:
                return jsonify({'error': 'Authentication required'}), 401
            plan = (user.get('plan') or 'FREE').upper()
            # Lifetime feature
            if feature.endswith('_lifetime'):
                col = feature.replace('chat_messages_lifetime','lifetime_chat_messages').replace('travel_assessments_lifetime','lifetime_travel_assessments')
                current = int(user.get(col, 0))
                limit = get_feature_limit(plan, feature)
                if limit != float('inf') and current >= limit:
                    return jsonify({'error': f"You've used all {limit} {feature.replace('_',' ')}",'required_plan': 'PRO','upgrade_url': '/sentinel-ai#pricing','feature_locked': True}), 403
                resp = fn(*args, **kwargs)
                if increment:
                    try:
                        _increment_lifetime(user['id'], col)
                    except Exception:
                        pass
                return resp
            # Monthly feature
            if feature.endswith('_monthly'):
                limit = get_feature_limit(plan, feature)
                if limit == 0:
                    return jsonify({'error': f'{feature} unavailable on {plan} plan','feature_locked': True,'required_plan': _suggest_upgrade(plan)}), 403
                if limit != float('inf'):
                    used = _get_monthly_usage(user['id'], feature)
                    if used >= limit:
                        return jsonify({'error': f"Monthly limit of {limit} {feature.replace('_monthly','')} reached",'required_plan': 'PRO' if plan=='FREE' else ('BUSINESS' if plan=='PRO' else 'ENTERPRISE'),'upgrade_url': '/sentinel-ai#pricing','feature_locked': True}), 403
                resp = fn(*args, **kwargs)
                if increment:
                    try:
                        _increment_monthly_usage(user['id'], feature)
                    except Exception:
                        pass
                return resp
            # Fallback: treat as simple feature gate
            try:
                check_feature_access(user, feature, raise_on_deny=True)
            except FeatureGateError as e:
                return jsonify({'error': e.message,'required_plan': e.required_plan,'upgrade_url': e.upgrade_url,'feature_locked': True}), 403
            return fn(*args, **kwargs)
        return wrapped
    return decorator

def check_feature_access_decorator(feature: str):  # compatibility alias
    return requires_feature(feature)

def check_feature_limit_decorator(feature: str):  # compatibility alias
    return check_usage_limit(feature, increment=False)

__all__ = [
    'FeatureGateError',
    'requires_feature',
    'check_usage_limit',
    'check_feature_access',
    'check_feature_limit',
    'check_feature_access_decorator',
    'check_feature_limit_decorator',
    'get_feature_limit'
]
