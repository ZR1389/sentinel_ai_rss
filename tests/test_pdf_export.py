#!/usr/bin/env python3
"""
Test PDF Export System - Phase 1
Tests PDF generation with real alert data from database
"""

import os
import sys
import json
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db_utils import fetch_one, fetch_all
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML

def test_template_rendering():
    """Test that templates can be loaded and rendered."""
    print("=" * 60)
    print("TEST 1: Template Rendering")
    print("=" * 60)
    
    # Test base template exists
    base_path = "templates/pdf/base.html"
    alert_path = "templates/pdf/threat_alert.html"
    
    if not os.path.exists(base_path):
        print(f"❌ FAIL: Base template not found at {base_path}")
        return False
    
    if not os.path.exists(alert_path):
        print(f"❌ FAIL: Alert template not found at {alert_path}")
        return False
    
    print(f"✓ Base template found: {base_path}")
    print(f"✓ Alert template found: {alert_path}")
    
    # Test Jinja2 loading
    try:
        env = Environment(loader=FileSystemLoader('templates/pdf'))
        template = env.get_template('threat_alert.html')
        print(f"✓ Jinja2 template loaded successfully")
    except Exception as e:
        print(f"❌ FAIL: Template loading error: {e}")
        return False
    
    # Test rendering with sample data
    sample_alert = {
        'title': 'Test Security Alert',
        'severity': 'HIGH',
        'threat_score': 7.5,
        'city': 'Karachi',
        'country': 'Pakistan',
        'published_at': '2025-11-25 12:00 UTC',
        'source_name': 'Test Source',
        'summary': 'This is a test security alert for PDF generation validation.',
        'description': 'Full description of the security incident with additional context and details.',
        'categories': ['Security', 'Terrorism', 'Crime'],
        'recommendations': 'Avoid the affected area. Monitor local news for updates.',
        'affected_areas': ['District A', 'District B'],
        'latitude': 24.8607,
        'longitude': 67.0011,
        'link': 'https://example.com/alert/12345'
    }
    
    try:
        html_content = template.render(
            alert=sample_alert,
            generated_at=datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'),
            user_email='test@example.com',
            page_size='A4',
            margin_top='2cm',
            margin_right='2cm',
            margin_bottom='2cm',
            margin_left='2cm',
            primary_color='#2563eb',
            logo_url=None
        )
        print(f"✓ Template rendered successfully ({len(html_content)} chars)")
        
        # Save HTML for inspection
        with open('/tmp/test_alert.html', 'w') as f:
            f.write(html_content)
        print(f"✓ Sample HTML saved to /tmp/test_alert.html")
        
    except Exception as e:
        print(f"❌ FAIL: Template rendering error: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print(f"✅ PASS: Template rendering test")
    return True


def test_pdf_generation():
    """Test PDF generation with WeasyPrint."""
    print("\n" + "=" * 60)
    print("TEST 2: PDF Generation with WeasyPrint")
    print("=" * 60)
    
    try:
        # Render HTML
        env = Environment(loader=FileSystemLoader('templates/pdf'))
        template = env.get_template('threat_alert.html')
        
        sample_alert = {
            'title': 'PDF Generation Test Alert',
            'severity': 'CRITICAL',
            'threat_score': 9.2,
            'city': 'Islamabad',
            'country': 'Pakistan',
            'published_at': datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'),
            'source_name': 'Test PDF Generator',
            'summary': 'Testing PDF generation with WeasyPrint library.',
            'description': 'This is a comprehensive test of the PDF export system including all template features.',
            'categories': ['Test', 'System Validation'],
            'recommendations': 'Verify PDF quality and formatting.',
            'latitude': 33.6844,
            'longitude': 73.0479
        }
        
        html_content = template.render(
            alert=sample_alert,
            generated_at=datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'),
            user_email='test@example.com',
            primary_color='#2563eb'
        )
        
        # Generate PDF
        pdf_path = '/tmp/test_alert.pdf'
        HTML(string=html_content).write_pdf(pdf_path)
        
        # Check file was created
        if not os.path.exists(pdf_path):
            print(f"❌ FAIL: PDF file not created at {pdf_path}")
            return False
        
        file_size = os.path.getsize(pdf_path)
        print(f"✓ PDF generated: {pdf_path} ({file_size} bytes)")
        
        if file_size < 1000:
            print(f"⚠️  WARNING: PDF size suspiciously small ({file_size} bytes)")
        
    except ImportError as e:
        print(f"❌ FAIL: WeasyPrint not installed: {e}")
        print("Run: pip install WeasyPrint")
        return False
    except Exception as e:
        print(f"❌ FAIL: PDF generation error: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print(f"✅ PASS: PDF generation test")
    return True


def test_database_alert_fetch():
    """Test fetching real alert data from database."""
    print("\n" + "=" * 60)
    print("TEST 3: Real Alert Data Fetch")
    print("=" * 60)
    
    try:
        # Fetch a high-severity alert
        alert = fetch_one("""
            SELECT 
                id, title, summary, label as severity, score as threat_score,
                city, country, region, latitude, longitude,
                published as published_at, source as source_name, link,
                category, subcategory
            FROM alerts 
            WHERE label IN ('HIGH', 'CRITICAL')
            AND title IS NOT NULL
            AND summary IS NOT NULL
            ORDER BY published DESC
            LIMIT 1
        """)
        
        if not alert:
            print("⚠️  WARNING: No alerts found in database")
            print("Creating sample alert for testing...")
            # Use sample data instead
            alert = {
                'id': 999,
                'title': 'Sample High-Priority Security Alert',
                'summary': 'This is a sample alert created for testing purposes.',
                'severity': 'HIGH',
                'threat_score': 8.0,
                'city': 'Karachi',
                'country': 'Pakistan',
                'region': 'South Asia',
                'latitude': 24.8607,
                'longitude': 67.0011,
                'published_at': datetime.utcnow(),
                'source_name': 'Test System',
                'link': 'https://example.com',
                'category': 'Security',
                'subcategory': 'Test'
            }
        else:
            print(f"✓ Alert fetched: ID={alert['id']}")
            print(f"  Title: {alert['title'][:60]}...")
            print(f"  Severity: {alert['severity']}")
            print(f"  Location: {alert.get('city', 'N/A')}, {alert.get('country', 'N/A')}")
        
        # Generate PDF from real alert
        env = Environment(loader=FileSystemLoader('templates/pdf'))
        template = env.get_template('threat_alert.html')
        
        # Format published_at
        pub_at = alert['published_at']
        if isinstance(pub_at, datetime):
            pub_at_str = pub_at.strftime('%Y-%m-%d %H:%M UTC')
        else:
            pub_at_str = str(pub_at)
        
        html_content = template.render(
            alert={
                **alert,
                'published_at': pub_at_str,
                'categories': [alert.get('category'), alert.get('subcategory')],
                'description': alert.get('summary', ''),  # Use summary as description
                'affected_areas': [],
                'recommendations': 'Monitor situation closely. Avoid affected areas if possible.'
            },
            generated_at=datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'),
            user_email='test@example.com',
            primary_color='#2563eb'
        )
        
        pdf_path = '/tmp/real_alert.pdf'
        HTML(string=html_content).write_pdf(pdf_path)
        
        file_size = os.path.getsize(pdf_path)
        print(f"✓ Real alert PDF: {pdf_path} ({file_size} bytes)")
        
    except Exception as e:
        print(f"❌ FAIL: Database alert fetch error: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print(f"✅ PASS: Real alert PDF generation test")
    return True


def test_plan_limits():
    """Test plan limit configuration."""
    print("\n" + "=" * 60)
    print("TEST 4: Plan Limit Configuration")
    print("=" * 60)
    
    try:
        from config_data.plans import get_plan_feature, PLAN_FEATURES
        
        limits = {
            'FREE': get_plan_feature('FREE', 'pdf_exports_monthly'),
            'PRO': get_plan_feature('PRO', 'pdf_exports_monthly'),
            'BUSINESS': get_plan_feature('BUSINESS', 'pdf_exports_monthly'),
            'ENTERPRISE': get_plan_feature('ENTERPRISE', 'pdf_exports_monthly')
        }
        
        print("PDF Export Limits by Plan:")
        for plan, limit in limits.items():
            limit_str = 'Unlimited' if limit is None else f'{limit}/month'
            status = '✓' if limit is not None or plan in ('BUSINESS', 'ENTERPRISE') else '⚠️'
            print(f"  {status} {plan}: {limit_str}")
        
        # Validate expected limits
        expected = {
            'FREE': 1,
            'PRO': 10,
            'BUSINESS': None,  # Unlimited
            'ENTERPRISE': None  # Unlimited
        }
        
        for plan, expected_limit in expected.items():
            actual_limit = limits[plan]
            if actual_limit != expected_limit:
                print(f"❌ FAIL: {plan} limit mismatch - expected {expected_limit}, got {actual_limit}")
                return False
        
    except Exception as e:
        print(f"❌ FAIL: Plan limits test error: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print(f"✅ PASS: Plan limit configuration test")
    return True


def main():
    print("\n" + "=" * 70)
    print(" PDF EXPORT SYSTEM - PHASE 1 TEST SUITE")
    print("=" * 70 + "\n")
    
    results = []
    
    # Run all tests
    results.append(("Template Rendering", test_template_rendering()))
    results.append(("PDF Generation", test_pdf_generation()))
    results.append(("Real Alert Data", test_database_alert_fetch()))
    results.append(("Plan Limits", test_plan_limits()))
    
    # Summary
    print("\n" + "=" * 70)
    print(" TEST SUMMARY")
    print("=" * 70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\nResults: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed! PDF export system ready for deployment.")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed. Review errors above.")
        return 1


if __name__ == '__main__':
    sys.exit(main())
