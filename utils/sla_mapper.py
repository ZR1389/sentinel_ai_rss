"""sla_mapper.py - Support level to SLA mapping for logging and monitoring.

Maps plan support levels to concrete SLA targets for response time tracking.
Used primarily for structured logging to monitor support performance.

Support Levels (from plans.py):
- FREE: email_48h (email response within 48 hours)
- PRO: email_24h (email response within 24 hours)
- BUSINESS: priority_24h (priority queue, 24h response)
- ENTERPRISE: analyst_4h (dedicated analyst, 4h response)

SLA Targets:
- Response Time: Maximum time to first response
- Resolution Time: Maximum time to resolve issue
- Channels: Available support channels
- Priority: Queue priority level
"""

from __future__ import annotations
import logging
from typing import Dict, Optional, Any
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# SLA definitions by support level
SLA_DEFINITIONS = {
    'email_48h': {
        'response_time_hours': 48,
        'resolution_time_hours': 120,  # 5 days
        'channels': ['email'],
        'priority': 'low',
        'description': 'Email support with 48-hour response',
        'business_hours_only': True,
        'escalation_path': None
    },
    'email_24h': {
        'response_time_hours': 24,
        'resolution_time_hours': 72,  # 3 days
        'channels': ['email', 'chat'],
        'priority': 'normal',
        'description': 'Email and chat support with 24-hour response',
        'business_hours_only': True,
        'escalation_path': None
    },
    'priority_24h': {
        'response_time_hours': 24,
        'resolution_time_hours': 48,  # 2 days
        'channels': ['email', 'chat', 'phone'],
        'priority': 'high',
        'description': 'Priority queue with 24-hour response, phone support',
        'business_hours_only': False,
        'escalation_path': 'manager'
    },
    'analyst_4h': {
        'response_time_hours': 4,
        'resolution_time_hours': 24,  # 1 day
        'channels': ['email', 'chat', 'phone', 'dedicated_slack'],
        'priority': 'critical',
        'description': 'Dedicated analyst with 4-hour response, 24/7 coverage',
        'business_hours_only': False,
        'escalation_path': 'director'
    }
}

# Plan to support level mapping (imported from plans.py logic)
PLAN_SUPPORT_LEVELS = {
    'FREE': 'email_48h',
    'PRO': 'email_24h',
    'BUSINESS': 'priority_24h',
    'ENTERPRISE': 'analyst_4h'
}


def get_sla_for_plan(plan: str) -> Optional[Dict[str, Any]]:
    """Get SLA definition for a given plan.
    
    Args:
        plan: Plan name (FREE, PRO, BUSINESS, ENTERPRISE)
        
    Returns:
        Dict with SLA details or None if plan not found
    """
    support_level = PLAN_SUPPORT_LEVELS.get(plan.upper())
    if not support_level:
        logger.warning(f"[sla_mapper] Unknown plan: {plan}")
        return None
    
    sla = SLA_DEFINITIONS.get(support_level)
    if not sla:
        logger.warning(f"[sla_mapper] Unknown support level: {support_level}")
        return None
    
    # Add metadata
    return {
        'plan': plan.upper(),
        'support_level': support_level,
        **sla
    }


def get_sla_for_support_level(support_level: str) -> Optional[Dict[str, Any]]:
    """Get SLA definition for a specific support level.
    
    Args:
        support_level: Support level identifier (email_48h, email_24h, etc.)
        
    Returns:
        Dict with SLA details or None if not found
    """
    sla = SLA_DEFINITIONS.get(support_level)
    if not sla:
        logger.warning(f"[sla_mapper] Unknown support level: {support_level}")
        return None
    
    return {
        'support_level': support_level,
        **sla
    }


def log_support_request(
    user_email: str,
    plan: str,
    request_type: str,
    metadata: Optional[Dict[str, Any]] = None
) -> str:
    """Log a support request with SLA tracking.
    
    Args:
        user_email: User email address
        plan: User's plan (FREE, PRO, BUSINESS, ENTERPRISE)
        request_type: Type of request (bug, feature, help, etc.)
        metadata: Additional context (optional)
        
    Returns:
        Request ID for tracking
    """
    import uuid
    from datetime import datetime, timezone
    
    request_id = str(uuid.uuid4())
    sla = get_sla_for_plan(plan)
    
    if not sla:
        logger.error(
            "[sla_mapper] Cannot log support request for unknown plan",
            extra={
                'request_id': request_id,
                'user_email': user_email,
                'plan': plan,
                'error': 'unknown_plan'
            }
        )
        return request_id
    
    # Calculate SLA deadlines
    now = datetime.now(timezone.utc)
    response_deadline = now + timedelta(hours=sla['response_time_hours'])
    resolution_deadline = now + timedelta(hours=sla['resolution_time_hours'])
    
    logger.info(
        "[sla_mapper] Support request created",
        extra={
            'request_id': request_id,
            'user_email': user_email,
            'plan': sla['plan'],
            'support_level': sla['support_level'],
            'request_type': request_type,
            'priority': sla['priority'],
            'response_sla_hours': sla['response_time_hours'],
            'resolution_sla_hours': sla['resolution_time_hours'],
            'response_deadline': response_deadline.isoformat(),
            'resolution_deadline': resolution_deadline.isoformat(),
            'channels_available': sla['channels'],
            'business_hours_only': sla['business_hours_only'],
            'metadata': metadata or {}
        }
    )
    
    return request_id


def check_sla_breach(
    request_id: str,
    created_at: datetime,
    responded_at: Optional[datetime] = None,
    resolved_at: Optional[datetime] = None,
    plan: str = 'FREE'
) -> Dict[str, Any]:
    """Check if a support request has breached SLA.
    
    Args:
        request_id: Support request ID
        created_at: When request was created
        responded_at: When first response was sent (optional)
        resolved_at: When issue was resolved (optional)
        plan: User's plan
        
    Returns:
        Dict with breach status and details
    """
    from datetime import datetime, timezone
    
    sla = get_sla_for_plan(plan)
    if not sla:
        return {'error': 'unknown_plan'}
    
    now = datetime.now(timezone.utc)
    response_deadline = created_at + timedelta(hours=sla['response_time_hours'])
    resolution_deadline = created_at + timedelta(hours=sla['resolution_time_hours'])
    
    result = {
        'request_id': request_id,
        'plan': plan,
        'support_level': sla['support_level'],
        'response_breach': False,
        'resolution_breach': False,
        'response_sla_hours': sla['response_time_hours'],
        'resolution_sla_hours': sla['resolution_time_hours']
    }
    
    # Check response SLA
    if responded_at:
        response_time = (responded_at - created_at).total_seconds() / 3600
        result['response_time_hours'] = round(response_time, 2)
        result['response_breach'] = response_time > sla['response_time_hours']
    elif now > response_deadline:
        # Not responded yet and past deadline
        result['response_breach'] = True
        result['response_overdue_hours'] = round((now - response_deadline).total_seconds() / 3600, 2)
    
    # Check resolution SLA
    if resolved_at:
        resolution_time = (resolved_at - created_at).total_seconds() / 3600
        result['resolution_time_hours'] = round(resolution_time, 2)
        result['resolution_breach'] = resolution_time > sla['resolution_time_hours']
    elif now > resolution_deadline:
        # Not resolved yet and past deadline
        result['resolution_breach'] = True
        result['resolution_overdue_hours'] = round((now - resolution_deadline).total_seconds() / 3600, 2)
    
    # Log if breached
    if result['response_breach'] or result['resolution_breach']:
        logger.warning(
            "[sla_mapper] SLA breach detected",
            extra={
                **result,
                'response_deadline': response_deadline.isoformat(),
                'resolution_deadline': resolution_deadline.isoformat()
            }
        )
    
    return result


def format_sla_summary(plan: str) -> str:
    """Format SLA summary as human-readable string.
    
    Args:
        plan: Plan name
        
    Returns:
        Formatted SLA summary string
    """
    sla = get_sla_for_plan(plan)
    if not sla:
        return f"Plan '{plan}': No SLA information available"
    
    hours_str = f"{sla['response_time_hours']}h response"
    if sla['response_time_hours'] >= 24:
        days = sla['response_time_hours'] // 24
        hours_str = f"{days}d response"
    
    channels = ", ".join(sla['channels'])
    coverage = "business hours" if sla['business_hours_only'] else "24/7"
    
    return f"{sla['description']} ({hours_str}, {coverage}) via {channels}"


def get_all_sla_tiers() -> Dict[str, Dict[str, Any]]:
    """Get all SLA tiers for comparison/documentation.
    
    Returns:
        Dict mapping plan names to SLA definitions
    """
    return {
        plan: get_sla_for_plan(plan)
        for plan in PLAN_SUPPORT_LEVELS.keys()
    }


__all__ = [
    'get_sla_for_plan',
    'get_sla_for_support_level',
    'log_support_request',
    'check_sla_breach',
    'format_sla_summary',
    'get_all_sla_tiers',
    'SLA_DEFINITIONS',
    'PLAN_SUPPORT_LEVELS'
]
