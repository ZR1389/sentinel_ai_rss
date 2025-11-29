#!/usr/bin/env python3
"""Demo script for SLA mapper - Support level to SLA logging.

This demonstrates how SLA tracking works with structured logging.
Run this to see SLA mappings for all plans and test logging functionality.
"""

import sys
import logging
from datetime import datetime, timedelta, timezone

# Setup logging to see structured output
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s - %(extra)s' if hasattr(logging, 'extra') else '%(asctime)s [%(levelname)s] %(message)s'
)

def demo_sla_mappings():
    """Show SLA mappings for all plans."""
    from sla_mapper import get_all_sla_tiers, format_sla_summary
    
    print("=" * 80)
    print("SLA MAPPINGS BY PLAN")
    print("=" * 80)
    
    tiers = get_all_sla_tiers()
    for plan, sla in tiers.items():
        print(f"\n{plan} Plan:")
        print(f"  Support Level: {sla['support_level']}")
        print(f"  Response Time: {sla['response_time_hours']} hours")
        print(f"  Resolution Time: {sla['resolution_time_hours']} hours")
        print(f"  Priority: {sla['priority']}")
        print(f"  Channels: {', '.join(sla['channels'])}")
        print(f"  Coverage: {'Business hours only' if sla['business_hours_only'] else '24/7'}")
        print(f"  Summary: {format_sla_summary(plan)}")
    
    print("\n" + "=" * 80)


def demo_support_request():
    """Demonstrate support request logging with SLA tracking."""
    from sla_mapper import log_support_request
    
    print("\n" + "=" * 80)
    print("SUPPORT REQUEST LOGGING DEMO")
    print("=" * 80)
    
    # Simulate support requests for different plans
    test_cases = [
        ('user-free@example.com', 'FREE', 'help', {'subject': 'How to use map filters?'}),
        ('user-pro@example.com', 'PRO', 'bug', {'subject': 'Chat export PDF not working'}),
        ('user-biz@example.com', 'BUSINESS', 'feature', {'subject': 'Need custom geofence radius'}),
        ('user-ent@example.com', 'ENTERPRISE', 'urgent', {'subject': 'API down, production impacted'})
    ]
    
    request_ids = []
    for email, plan, req_type, metadata in test_cases:
        print(f"\n📧 Creating support request for {plan} user:")
        request_id = log_support_request(email, plan, req_type, metadata)
        request_ids.append((request_id, plan))
        print(f"   Request ID: {request_id}")
    
    print("\n" + "=" * 80)
    return request_ids


def demo_sla_breach_checking():
    """Demonstrate SLA breach detection."""
    from sla_mapper import check_sla_breach
    
    print("\n" + "=" * 80)
    print("SLA BREACH CHECKING DEMO")
    print("=" * 80)
    
    now = datetime.now(timezone.utc)
    
    # Scenario 1: FREE plan - Responded in 36h (within 48h SLA) ✅
    print("\n✅ Scenario 1: FREE plan - Responded in 36h (within SLA)")
    result = check_sla_breach(
        request_id='req-001',
        created_at=now - timedelta(hours=36),
        responded_at=now,
        plan='FREE'
    )
    print(f"   Response time: {result.get('response_time_hours')}h")
    print(f"   SLA: {result['response_sla_hours']}h")
    print(f"   Breach: {result['response_breach']}")
    
    # Scenario 2: PRO plan - Responded in 30h (breached 24h SLA) ❌
    print("\n❌ Scenario 2: PRO plan - Responded in 30h (breached SLA)")
    result = check_sla_breach(
        request_id='req-002',
        created_at=now - timedelta(hours=30),
        responded_at=now,
        plan='PRO'
    )
    print(f"   Response time: {result.get('response_time_hours')}h")
    print(f"   SLA: {result['response_sla_hours']}h")
    print(f"   Breach: {result['response_breach']}")
    
    # Scenario 3: ENTERPRISE plan - Responded in 2h (within 4h SLA) ✅
    print("\n✅ Scenario 3: ENTERPRISE plan - Responded in 2h (within SLA)")
    result = check_sla_breach(
        request_id='req-003',
        created_at=now - timedelta(hours=2),
        responded_at=now,
        plan='ENTERPRISE'
    )
    print(f"   Response time: {result.get('response_time_hours')}h")
    print(f"   SLA: {result['response_sla_hours']}h")
    print(f"   Breach: {result['response_breach']}")
    
    # Scenario 4: BUSINESS plan - Not responded yet, overdue ❌
    print("\n❌ Scenario 4: BUSINESS plan - Not responded, overdue")
    result = check_sla_breach(
        request_id='req-004',
        created_at=now - timedelta(hours=30),
        plan='BUSINESS'
    )
    print(f"   Response SLA: {result['response_sla_hours']}h")
    print(f"   Breach: {result['response_breach']}")
    print(f"   Overdue by: {result.get('response_overdue_hours')}h")
    
    print("\n" + "=" * 80)


def demo_integration_pattern():
    """Show how to integrate SLA logging in endpoints."""
    print("\n" + "=" * 80)
    print("INTEGRATION PATTERN (for main.py)")
    print("=" * 80)
    
    code = '''
# Add import at top of main.py (after logging setup):
from sla_mapper import get_sla_for_plan, format_sla_summary

# In /auth/status endpoint, add to response JSON:
"support_level": format_sla_summary(plan_name),

# After successful auth, log SLA context:
sla = get_sla_for_plan(plan_name)
if sla:
    logger.info(
        "[sla] User authenticated",
        extra={
            'event': 'user_login',
            'user_email': email,
            'plan': plan_name,
            'support_level': sla['support_level'],
            'response_sla_hours': sla['response_time_hours'],
            'priority': sla['priority'],
            'channels': sla['channels']
        }
    )

# In error handlers (500, 400), log with SLA context:
@app.errorhandler(500)
def server_error_500(e):
    email = get_logged_in_email() if 'get_logged_in_email' in globals() else None
    plan = get_user_plan(email) if email else 'FREE'
    sla = get_sla_for_plan(plan)
    
    logger.error(
        "[sla] Server error occurred",
        extra={
            'event': 'server_error',
            'user_email': email,
            'plan': plan,
            'support_level': sla['support_level'] if sla else 'unknown',
            'priority': sla['priority'] if sla else 'low',
            'error': str(e)
        }
    )
    # ... existing error handling

# In support ticket creation endpoint (future):
@app.route("/api/support/ticket", methods=["POST"])
@login_required
def create_support_ticket():
    email = get_logged_in_email()
    plan = get_user_plan(email)
    data = request.get_json()
    
    request_id = log_support_request(
        user_email=email,
        plan=plan,
        request_type=data.get('type', 'help'),
        metadata={
            'subject': data.get('subject'),
            'description': data.get('description'),
            'urgency': data.get('urgency', 'normal')
        }
    )
    
    return jsonify({'ok': True, 'request_id': request_id})
'''
    
    print(code)
    print("=" * 80)


def main():
    """Run all demos."""
    print("\n" + "█" * 80)
    print("█" + " " * 78 + "█")
    print("█" + " " * 20 + "SLA MAPPER DEMONSTRATION" + " " * 34 + "█")
    print("█" + " " * 78 + "█")
    print("█" * 80)
    
    try:
        demo_sla_mappings()
        demo_support_request()
        demo_sla_breach_checking()
        demo_integration_pattern()
        
        print("\n✅ All demos completed successfully!")
        print("\nNext steps:")
        print("  1. Review sla_mapper.py for implementation details")
        print("  2. Integrate logging calls in main.py endpoints")
        print("  3. Monitor structured logs for SLA tracking")
        print("  4. Set up alerts for SLA breaches (future)")
        
    except Exception as e:
        print(f"\n❌ Demo failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
