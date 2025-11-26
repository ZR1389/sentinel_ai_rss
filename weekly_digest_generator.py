"""
Weekly Digest Generator - Phase 2
Generates and emails weekly threat digest PDFs on schedule
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any
import pytz
import json

from db_utils import fetch_all, fetch_one, execute
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML
import uuid

logger = logging.getLogger(__name__)


def generate_weekly_digest_pdf(user_id: int, email: str, filters: Dict, week_start: datetime, week_end: datetime) -> tuple[str, str]:
    """
    Generate a weekly digest PDF for the specified user and date range.
    
    Args:
        user_id: Database user ID
        email: User email
        filters: JSONB filters (countries, severity, categories)
        week_start: Start of week (datetime)
        week_end: End of week (datetime)
    
    Returns:
        Tuple of (file_path, file_id)
    """
    try:
        # Build query filters
        where_clauses = ["published >= %s", "published < %s"]
        params = [week_start, week_end]
        
        if filters.get('countries'):
            where_clauses.append("country = ANY(%s)")
            params.append(filters['countries'])
        
        if filters.get('severity'):
            where_clauses.append("label = ANY(%s)")
            params.append(filters['severity'])
        
        if filters.get('categories'):
            where_clauses.append("category = ANY(%s)")
            params.append(filters['categories'])
        
        where_sql = " AND ".join(where_clauses)
        
        # Fetch alerts for the week
        alerts = fetch_all(f"""
            SELECT id, title, summary, label as severity, score as threat_score,
                   city, country, published as published_at, source as source_name,
                   category, subcategory
            FROM alerts
            WHERE {where_sql}
            ORDER BY published DESC
            LIMIT 100
        """, tuple(params))
        
        if not alerts:
            logger.info(f"No alerts found for weekly digest: user={email}, filters={filters}")
            return None, None
        
        # Calculate summary statistics
        total_alerts = len(alerts)
        critical_count = sum(1 for a in alerts if (a.get('severity') or a.get('label')) == 'CRITICAL')
        high_count = sum(1 for a in alerts if (a.get('severity') or a.get('label')) == 'HIGH')
        medium_count = sum(1 for a in alerts if (a.get('severity') or a.get('label')) == 'MEDIUM')
        low_count = sum(1 for a in alerts if (a.get('severity') or a.get('label')) == 'LOW')
        
        # Get previous week for trend
        prev_week_start = week_start - timedelta(days=7)
        prev_week_count = fetch_one(f"""
            SELECT COUNT(*) as count FROM alerts WHERE {where_sql}
        """, (prev_week_start, week_start) + tuple(params[2:]))
        
        prev_count = prev_week_count['count'] if isinstance(prev_week_count, dict) else prev_week_count[0]
        if prev_count > 0:
            trend_percent = int(((total_alerts - prev_count) / prev_count) * 100)
            trend = 'up' if trend_percent > 5 else ('down' if trend_percent < -5 else 'stable')
        else:
            trend_percent = 0
            trend = 'stable'
        
        # Geographic breakdown
        geo_breakdown = fetch_all(f"""
            SELECT country,
                   COUNT(*) as total,
                   SUM(CASE WHEN label='CRITICAL' THEN 1 ELSE 0 END) as critical,
                   SUM(CASE WHEN label='HIGH' THEN 1 ELSE 0 END) as high,
                   SUM(CASE WHEN label='MEDIUM' THEN 1 ELSE 0 END) as medium,
                   SUM(CASE WHEN label='LOW' THEN 1 ELSE 0 END) as low
            FROM alerts
            WHERE {where_sql}
            GROUP BY country
            ORDER BY total DESC
            LIMIT 10
        """, tuple(params))
        
        # Category breakdown
        cat_breakdown = fetch_all(f"""
            SELECT category,
                   COUNT(*) as count
            FROM alerts
            WHERE {where_sql} AND category IS NOT NULL
            GROUP BY category
            ORDER BY count DESC
            LIMIT 10
        """, tuple(params))
        
        # Get top 5 highest severity threats
        top_threats = alerts[:5]
        
        # Format data for template
        template_data = {
            'week_start': week_start.strftime('%Y-%m-%d'),
            'week_end': week_end.strftime('%Y-%m-%d'),
            'generated_at': datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'),
            'user_email': email,
            'summary': {
                'total_alerts': total_alerts,
                'critical_count': critical_count,
                'high_count': high_count,
                'medium_count': medium_count,
                'low_count': low_count,
                'trend': trend,
                'trend_percent': abs(trend_percent),
                'executive_summary': f"This week saw {total_alerts} threat alerts across monitored regions. "
                                   f"{critical_count} critical and {high_count} high-severity incidents were detected. "
                                   f"Threat activity is {trend} compared to the previous week.",
                'source_count': len(set(a.get('source_name') or 'Unknown' for a in alerts))
            },
            'top_threats': [format_alert(a) for a in top_threats],
            'geographic_breakdown': [format_geo(g) for g in geo_breakdown],
            'category_breakdown': [format_category(c) for c in cat_breakdown],
            'all_alerts': [format_alert(a) for a in alerts],
            'recommendations': generate_recommendations(alerts, critical_count, high_count),
            'primary_color': '#2563eb'
        }
        
        # Render template
        env = Environment(loader=FileSystemLoader('templates/pdf'))
        template = env.get_template('weekly_digest.html')
        html_content = template.render(**template_data)
        
        # Generate PDF
        file_id = str(uuid.uuid4())
        filename = f"weekly_digest_{week_start.strftime('%Y%m%d')}_{file_id}.pdf"
        file_path = os.path.join('downloads', filename)
        
        HTML(string=html_content).write_pdf(file_path)
        
        # Save to database
        expires_at = datetime.utcnow() + timedelta(days=7)  # 7-day expiry for digests
        execute("""
            INSERT INTO pdf_exports (id, user_id, filename, template, expires_at)
            VALUES (%s, %s, %s, %s, %s)
        """, (file_id, user_id, filename, 'weekly_digest', expires_at))
        
        logger.info(f"Weekly digest PDF generated: user={email}, file={filename}, alerts={total_alerts}")
        return file_path, file_id
        
    except Exception as e:
        logger.error(f"Weekly digest PDF generation failed: user={email}, error={e}")
        import traceback
        traceback.print_exc()
        return None, None


def format_alert(alert: Dict) -> Dict:
    """Format alert dict for template."""
    severity = alert.get('severity') or alert.get('label') or 'UNKNOWN'
    pub_at = alert.get('published_at')
    if isinstance(pub_at, datetime):
        pub_at_str = pub_at.strftime('%Y-%m-%d %H:%M UTC')
    else:
        pub_at_str = str(pub_at) if pub_at else 'N/A'
    
    return {
        'title': alert.get('title') or 'Untitled Alert',
        'summary': alert.get('summary') or 'No summary available',
        'severity': severity,
        'threat_score': alert.get('threat_score'),
        'city': alert.get('city'),
        'country': alert.get('country') or 'Unknown',
        'published_at': pub_at_str,
        'source_name': alert.get('source_name'),
        'category': alert.get('category'),
        'subcategory': alert.get('subcategory')
    }


def format_geo(geo: Dict) -> Dict:
    """Format geographic breakdown for template."""
    return {
        'country': geo.get('country') or 'Unknown',
        'total': geo.get('total') or 0,
        'critical': geo.get('critical') or 0,
        'high': geo.get('high') or 0,
        'medium': geo.get('medium') or 0,
        'low': geo.get('low') or 0
    }


def format_category(cat: Dict) -> Dict:
    """Format category breakdown for template."""
    return {
        'category': cat.get('category') or 'Unknown',
        'count': cat.get('count') or 0,
        'trend': 0  # TODO: Calculate trend from previous week
    }


def generate_recommendations(alerts: List[Dict], critical_count: int, high_count: int) -> List[str]:
    """Generate contextual recommendations based on alerts."""
    recs = []
    
    if critical_count > 0:
        recs.append(f"{critical_count} critical-severity alerts require immediate attention and risk assessment.")
    
    if high_count > 5:
        recs.append(f"{high_count} high-severity incidents detected. Review travel advisories for affected regions.")
    
    # Check for specific countries with high activity
    country_counts = {}
    for alert in alerts:
        country = alert.get('country')
        if country:
            country_counts[country] = country_counts.get(country, 0) + 1
    
    high_activity_countries = [c for c, count in country_counts.items() if count > 5]
    if high_activity_countries:
        recs.append(f"High threat activity in: {', '.join(high_activity_countries[:3])}. Avoid non-essential travel.")
    
    if not recs:
        recs.append("No immediate high-priority threats identified. Continue monitoring for updates.")
    
    return recs


def send_digest_email(email: str, file_path: str, week_start: datetime, week_end: datetime):
    """Send weekly digest PDF via email using Brevo."""
    try:
        # Import Brevo client
        import sib_api_v3_sdk
        from sib_api_v3_sdk.rest import ApiException
        
        api_key = os.getenv('BREVO_API_KEY')
        if not api_key:
            logger.error("BREVO_API_KEY not configured")
            return False
        
        configuration = sib_api_v3_sdk.Configuration()
        configuration.api_key['api-key'] = api_key
        api_instance = sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(configuration))
        
        # Read PDF file and encode
        import base64
        with open(file_path, 'rb') as f:
            pdf_content = base64.b64encode(f.read()).decode('utf-8')
        
        # Send email
        send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
            to=[{"email": email}],
            sender={"email": "noreply@sentinel-ai.app", "name": "Sentinel AI"},
            subject=f"Weekly Threat Digest: {week_start.strftime('%b %d')} - {week_end.strftime('%b %d, %Y')}",
            html_content=f"""
            <html>
            <body style="font-family: Arial, sans-serif; color: #1a1a1a;">
                <h2>Your Weekly Threat Digest is Ready</h2>
                <p>Attached is your customized weekly threat intelligence digest for the period 
                <strong>{week_start.strftime('%B %d')} - {week_end.strftime('%B %d, %Y')}</strong>.</p>
                <p>This digest includes:</p>
                <ul>
                    <li>Summary of all threat alerts matching your filters</li>
                    <li>Geographic and category breakdowns</li>
                    <li>Top threats requiring attention</li>
                    <li>Actionable recommendations</li>
                </ul>
                <p style="margin-top: 20px;">
                    <a href="https://sentinel-ai.app/dashboard" style="background-color: #2563eb; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px;">
                        View Dashboard
                    </a>
                </p>
                <p style="color: #6b7280; font-size: 12px; margin-top: 30px;">
                    This is an automated weekly digest. To manage your digest preferences, visit your account settings.
                </p>
            </body>
            </html>
            """,
            attachment=[{
                "content": pdf_content,
                "name": os.path.basename(file_path)
            }]
        )
        
        api_response = api_instance.send_transac_email(send_smtp_email)
        logger.info(f"Weekly digest email sent: email={email}, message_id={api_response.message_id}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send digest email: email={email}, error={e}")
        return False
