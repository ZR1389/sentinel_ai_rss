"""
location_quality_monitor.py

Monitor location data quality with dashboards and anomaly detection.
Provides insights without consuming OpenCage quota.
"""

import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import random

logger = logging.getLogger(__name__)

def get_location_quality_report(days: int = 7) -> Dict:
    """
    Generate location quality report for the past N days.
    
    Returns:
        {
            'by_method': [...],
            'total_alerts': int,
            'quality_score': float,
            'anomalies': [...]
        }
    """
    try:
        from db_utils import fetch_all
        
        # Location method distribution
        method_stats = fetch_all(
            """
            SELECT 
                location_method,
                COUNT(*) as alert_count,
                ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 2) as percentage
            FROM alerts
            WHERE created_at > NOW() - INTERVAL %s
            GROUP BY location_method
            ORDER BY alert_count DESC
            """,
            (f'{days} days',)
        )
        
        # Total count
        total = fetch_all(
            """
            SELECT COUNT(*) as total
            FROM alerts
            WHERE created_at > NOW() - INTERVAL %s
            """,
            (f'{days} days',)
        )
        
        total_count = total[0]['total'] if total and len(total) > 0 else 0
        
        # Calculate quality score (TIER1 methods = high quality)
        tier1_methods = ['coordinates', 'db_cache', 'nlp_nominatim', 'nominatim']
        tier1_count = sum(row['alert_count'] for row in method_stats if row['location_method'] in tier1_methods)
        quality_score = (tier1_count / total_count * 100) if total_count > 0 else 0
        
        # Format method stats
        by_method = [
            {
                'method': row['location_method'] or 'unknown',
                'count': row['alert_count'],
                'percentage': float(row['percentage'])
            }
            for row in method_stats
        ]
        
        # Detect anomalies
        anomalies = detect_location_anomalies(days)
        
        return {
            'by_method': by_method,
            'total_alerts': total_count,
            'quality_score': round(quality_score, 2),
            'anomalies': anomalies,
            'period_days': days
        }
        
    except Exception as e:
        logger.error(f"[LocationQuality] Failed to generate report: {e}")
        return {
            'by_method': [],
            'total_alerts': 0,
            'quality_score': 0.0,
            'anomalies': [],
            'error': str(e)
        }


def detect_location_anomalies(days: int = 7) -> List[Dict]:
    """
    Detect suspicious location data that may need review.
    
    Returns list of anomalies:
        [
            {'type': 'invalid_coords', 'alert_id': ..., 'details': ...},
            {'type': 'missing_country', 'alert_id': ..., 'details': ...},
            ...
        ]
    """
    anomalies = []
    
    try:
        from db_utils import fetch_all
        
        # 1. Invalid coordinates (out of bounds)
        invalid_coords = fetch_all(
            """
            SELECT id, title, latitude, longitude, city, country
            FROM alerts
            WHERE created_at > NOW() - INTERVAL %s
              AND (
                  latitude IS NOT NULL AND (latitude < -90 OR latitude > 90)
                  OR longitude IS NOT NULL AND (longitude < -180 OR longitude > 180)
              )
            LIMIT 10
            """,
            (f'{days} days',)
        )
        
        for row in invalid_coords:
            anomalies.append({
                'type': 'invalid_coords',
                'severity': 'high',
                'alert_id': row['id'],
                'title': row['title'],
                'latitude': row['latitude'],
                'longitude': row['longitude'],
                'details': f"Coordinates out of valid range: ({row['latitude']}, {row['longitude']})"
            })
        
        # 2. City without country (data quality issue)
        missing_country = fetch_all(
            """
            SELECT id, title, city, country
            FROM alerts
            WHERE created_at > NOW() - INTERVAL %s
              AND city IS NOT NULL
              AND (country IS NULL OR country = '')
            LIMIT 10
            """,
            (f'{days} days',)
        )
        
        for row in missing_country:
            anomalies.append({
                'type': 'missing_country',
                'severity': 'medium',
                'alert_id': row['id'],
                'title': row['title'],
                'city': row['city'],
                'details': f"City '{row['city']}' has no country"
            })
        
        # 3. Coordinates without city/country (location_method issue)
        orphan_coords = fetch_all(
            """
            SELECT id, title, latitude, longitude, location_method
            FROM alerts
            WHERE created_at > NOW() - INTERVAL %s
              AND latitude IS NOT NULL
              AND (city IS NULL OR city = '')
              AND (country IS NULL OR country = '')
            LIMIT 10
            """,
            (f'{days} days',)
        )
        
        for row in orphan_coords:
            anomalies.append({
                'type': 'orphan_coords',
                'severity': 'low',
                'alert_id': row['id'],
                'title': row['title'],
                'latitude': row['latitude'],
                'longitude': row['longitude'],
                'location_method': row['location_method'],
                'details': f"Has coordinates but no city/country (method: {row['location_method']})"
            })
        
        # 4. Duplicate coordinates (potential data quality issue)
        duplicate_coords = fetch_all(
            """
            SELECT latitude, longitude, COUNT(*) as count
            FROM alerts
            WHERE created_at > NOW() - INTERVAL %s
              AND latitude IS NOT NULL
            GROUP BY latitude, longitude
            HAVING COUNT(*) > 10
            ORDER BY COUNT(*) DESC
            LIMIT 5
            """,
            (f'{days} days',)
        )
        
        for row in duplicate_coords:
            if row['count'] > 20:  # More than 20 alerts at exact same location
                anomalies.append({
                    'type': 'duplicate_coords',
                    'severity': 'low',
                    'latitude': row['latitude'],
                    'longitude': row['longitude'],
                    'count': row['count'],
                    'details': f"{row['count']} alerts at same coordinates - may indicate centroid usage"
                })
        
        logger.info(f"[LocationQuality] Found {len(anomalies)} anomalies in past {days} days")
        
    except Exception as e:
        logger.error(f"[LocationQuality] Failed to detect anomalies: {e}")
    
    return anomalies


def should_validate_with_opencage(alert: Dict) -> bool:
    """
    Determine if an alert should be validated with OpenCage (1% sampling).
    
    Use cases:
    - Random 1% sample for quality assurance
    - All high-severity anomalies
    - Alerts with low-confidence location methods
    
    Returns:
        True if alert should be validated with OpenCage
    """
    # High-severity anomalies always validate
    if alert.get('latitude') and (
        abs(alert['latitude']) > 90 or 
        abs(alert.get('longitude', 0)) > 180
    ):
        logger.info(f"[LocationQuality] OpenCage validation: invalid coordinates for alert {alert.get('id')}")
        return True
    
    # Missing country with city = medium priority
    if alert.get('city') and not alert.get('country'):
        logger.info(f"[LocationQuality] OpenCage validation: missing country for alert {alert.get('id')}")
        return True
    
    # Weak location methods = validate 10%
    weak_methods = ['country_centroid', 'legacy_precise', 'unknown', 'none']
    if alert.get('location_method') in weak_methods:
        if random.random() < 0.10:  # 10% of weak methods
            logger.info(f"[LocationQuality] OpenCage validation: weak method '{alert.get('location_method')}' for alert {alert.get('id')}")
            return True
    
    # Random 1% sampling for all alerts (quality assurance)
    if random.random() < 0.01:
        logger.info(f"[LocationQuality] OpenCage validation: random 1% sample for alert {alert.get('id')}")
        return True
    
    return False


def validate_alert_with_opencage(alert: Dict) -> Optional[Dict]:
    """
    Validate an alert's location using OpenCage API.
    
    Returns:
        {
            'validated': bool,
            'opencage_lat': float,
            'opencage_lon': float,
            'distance_km': float,
            'confidence': int,
            'needs_correction': bool
        }
        or None if validation failed
    """
    try:
        from services.geocoding_service import geocode
        
        # Build location query
        location_query = None
        if alert.get('city') and alert.get('country'):
            location_query = f"{alert['city']}, {alert['country']}"
        elif alert.get('country'):
            location_query = alert['country']
        else:
            logger.warning(f"[LocationQuality] Cannot validate alert {alert.get('id')}: no location data")
            return None
        
        # Call OpenCage via geocoding_service (respects quota)
        result = geocode(location_query, force_api=False)
        
        if not result:
            logger.warning(f"[LocationQuality] OpenCage returned no results for: {location_query}")
            return None
        
        opencage_lat = result['lat']
        opencage_lon = result['lon']
        
        # Calculate distance if alert has coordinates
        distance_km = None
        needs_correction = False
        
        if alert.get('latitude') and alert.get('longitude'):
            distance_km = _haversine_distance(
                alert['latitude'], alert['longitude'],
                opencage_lat, opencage_lon
            )
            
            # Flag if distance > 100km (likely wrong location)
            needs_correction = distance_km > 100
        
        validation_result = {
            'validated': True,
            'opencage_lat': opencage_lat,
            'opencage_lon': opencage_lon,
            'opencage_country': result.get('country_code'),
            'opencage_confidence': result.get('confidence', 5),
            'opencage_source': result.get('source', 'opencage'),
            'distance_km': distance_km,
            'needs_correction': needs_correction,
            'query': location_query
        }
        
        logger.info(f"[LocationQuality] OpenCage validation for {location_query}: "
                   f"distance={distance_km:.1f}km, confidence={result.get('confidence')}, "
                   f"needs_correction={needs_correction}")
        
        return validation_result
        
    except Exception as e:
        logger.error(f"[LocationQuality] OpenCage validation failed: {e}")
        return None


def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate distance between two coordinates in kilometers.
    Uses Haversine formula.
    """
    from math import radians, sin, cos, sqrt, atan2
    
    R = 6371  # Earth's radius in kilometers
    
    lat1_rad = radians(lat1)
    lat2_rad = radians(lat2)
    delta_lat = radians(lat2 - lat1)
    delta_lon = radians(lon2 - lon1)
    
    a = sin(delta_lat / 2) ** 2 + cos(lat1_rad) * cos(lat2_rad) * sin(delta_lon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    
    distance = R * c
    return distance


def log_validation_result(alert_id: int, validation: Dict) -> None:
    """
    Log validation result for future analysis.
    Could be extended to store in database for tracking.
    """
    try:
        from db_utils import execute_query
        
        execute_query(
            """
            INSERT INTO location_validations (
                alert_id, 
                validated_at,
                opencage_lat,
                opencage_lon,
                opencage_country,
                opencage_confidence,
                distance_km,
                needs_correction,
                validation_query
            )
            VALUES (%s, NOW(), %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (alert_id) 
            DO UPDATE SET
                validated_at = NOW(),
                opencage_lat = EXCLUDED.opencage_lat,
                opencage_lon = EXCLUDED.opencage_lon,
                distance_km = EXCLUDED.distance_km,
                needs_correction = EXCLUDED.needs_correction
            """,
            (
                alert_id,
                validation.get('opencage_lat'),
                validation.get('opencage_lon'),
                validation.get('opencage_country'),
                validation.get('opencage_confidence'),
                validation.get('distance_km'),
                validation.get('needs_correction'),
                validation.get('query')
            )
        )
        
        logger.info(f"[LocationQuality] Logged validation for alert {alert_id}")
        
    except Exception as e:
        # Table may not exist yet, log to file instead
        logger.warning(f"[LocationQuality] Could not log validation to DB (table may not exist): {e}")


# CLI for manual quality checks
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "report":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
        report = get_location_quality_report(days)
        
        print(f"\n=== Location Quality Report (Last {days} Days) ===")
        print(f"Total Alerts: {report['total_alerts']}")
        print(f"Quality Score: {report['quality_score']}% (TIER1 methods)")
        print(f"\nBy Method:")
        for method in report['by_method']:
            print(f"  {method['method']:20s} {method['count']:5d} ({method['percentage']:5.1f}%)")
        
        print(f"\nAnomalies Found: {len(report['anomalies'])}")
        for anomaly in report['anomalies'][:10]:  # Show first 10
            print(f"  [{anomaly['severity'].upper()}] {anomaly['type']}: {anomaly['details']}")
    else:
        print("Usage: python location_quality_monitor.py report [days]")
        print("Example: python location_quality_monitor.py report 7")
