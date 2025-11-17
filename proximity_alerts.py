"""proximity_alerts.py

Find threats near travelers using haversine distance (no PostGIS).
Two-phase approach: bounding box filter + precise distance calculation.
"""

import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from geo_utils import haversine_distance, bounding_box, validate_coordinates

logger = logging.getLogger("proximity_alerts")


def _get_db_helpers():
    try:
        from db_utils import _get_db_connection
        return _get_db_connection
    except Exception as e:
        logger.error("[proximity] DB helpers unavailable: %s", e)
        return None


def find_threats_near_traveler(traveler_id: int, hours_lookback: int = 24) -> List[Dict]:
    """
    Find all threats within traveler's alert radius in last N hours.
    
    Process:
    1. Get traveler location and radius
    2. Calculate bounding box for fast SQL filter
    3. Query threats in bounding box
    4. Calculate exact haversine distance
    5. Filter to threats within actual radius
    
    Args:
        traveler_id: Traveler profile ID
        hours_lookback: How many hours to look back
    
    Returns:
        List of threats with distance
    """
    get_conn_cm = _get_db_helpers()
    if not get_conn_cm:
        return []
    
    try:
        with get_conn_cm() as conn:
            cur = conn.cursor()
            
            # Get traveler location and radius
            cur.execute(
                """
                SELECT latitude, longitude, alert_radius_km, email, name
                FROM traveler_profiles
                WHERE id = %s AND active = true
                """,
                (traveler_id,)
            )
            
            traveler = cur.fetchone()
            if not traveler:
                logger.warning(f"[proximity] Traveler {traveler_id} not found or inactive")
                return []
            
            t_lat, t_lon, radius_km, email, name = traveler
            
            if not validate_coordinates(t_lat, t_lon):
                logger.error(f"[proximity] Invalid coordinates for traveler {traveler_id}")
                return []
            
            cutoff_time = datetime.utcnow() - timedelta(hours=hours_lookback)
            
            # Calculate bounding box for fast SQL filter
            min_lat, max_lat, min_lon, max_lon = bounding_box(
                float(t_lat), float(t_lon), radius_km
            )
            
            threats = []
            
            # ================================================================
            # Query GDELT threats
            # ================================================================
            cur.execute(
                """
                SELECT 
                    global_event_id,
                    sql_date,
                    actor1,
                    actor2,
                    action_country,
                    ABS(goldstein) as severity,
                    num_articles,
                    latitude,
                    longitude
                FROM gdelt_events
                WHERE 
                    created_at >= %s
                    AND quad_class IN (3, 4)
                    AND goldstein < -5
                    AND latitude IS NOT NULL
                    AND longitude IS NOT NULL
                    AND latitude BETWEEN %s AND %s
                    AND longitude BETWEEN %s AND %s
                ORDER BY created_at DESC
                """,
                (cutoff_time, min_lat, max_lat, min_lon, max_lon)
            )
            
            for row in cur.fetchall():
                threat_lat = float(row[7])
                threat_lon = float(row[8])
                
                distance_km = haversine_distance(
                    float(t_lat), float(t_lon), 
                    threat_lat, threat_lon
                )
                
                if distance_km <= radius_km:
                    threats.append({
                        'source': 'GDELT',
                        'id': row[0],
                        'date': str(row[1]),
                        'actor1': row[2],
                        'actor2': row[3],
                        'country': row[4],
                        'severity': float(row[5]),
                        'articles': row[6],
                        'distance_km': round(distance_km, 1),
                        'lat': threat_lat,
                        'lon': threat_lon
                    })
            
            # ================================================================
            # TODO: Add RSS threats query here
            # ================================================================
            # cur.execute("""
            #     SELECT id, title, location, latitude, longitude, published_date, severity
            #     FROM rss_alerts
            #     WHERE published_date >= %s
            #       AND latitude BETWEEN %s AND %s
            #       AND longitude BETWEEN %s AND %s
            # """, (cutoff_time, min_lat, max_lat, min_lon, max_lon))
            # 
            # for row in cur.fetchall():
            #     ... calculate distance and append ...
            
            # ================================================================
            # TODO: Add ACLED threats query here
            # ================================================================
            
            # Sort by distance (closest first)
            threats.sort(key=lambda x: x['distance_km'])
            
            logger.info(f"[proximity] Found {len(threats)} threats for traveler {traveler_id} within {radius_km}km")
            return threats
            
    except Exception as e:
        logger.error(f"[proximity] Query failed for traveler {traveler_id}: {e}")
        return []


def find_threats_near_location(lat: float, lon: float, radius_km: int = 50, 
                               days: int = 7, sources: List[str] = None) -> List[Dict]:
    """
    Find threats near any coordinate (not just registered travelers).
    Used by travel risk advisor.
    
    Args:
        lat: Latitude
        lon: Longitude
        radius_km: Search radius in kilometers
        days: How many days to look back
        sources: List of sources to query ['gdelt', 'rss', 'acled']
    
    Returns:
        List of threats with distance
    """
    get_conn_cm = _get_db_helpers()
    if not get_conn_cm:
        return []
    
    if not validate_coordinates(lat, lon):
        logger.error(f"[proximity] Invalid coordinates: {lat}, {lon}")
        return []
    
    if sources is None:
        sources = ['gdelt']  # Default to GDELT only
    
    cutoff_date = (datetime.utcnow() - timedelta(days=days)).strftime('%Y%m%d')
    min_lat, max_lat, min_lon, max_lon = bounding_box(lat, lon, radius_km)
    
    try:
        with get_conn_cm() as conn:
            cur = conn.cursor()
            threats = []
            
            # ================================================================
            # GDELT
            # ================================================================
            if 'gdelt' in sources:
                cur.execute(
                    """
                    SELECT 
                        global_event_id,
                        sql_date,
                        actor1,
                        actor2,
                        action_country,
                        ABS(goldstein) as severity,
                        num_articles,
                        num_sources,
                        latitude,
                        longitude
                    FROM gdelt_events
                    WHERE 
                        sql_date >= %s
                        AND quad_class IN (3, 4)
                        AND goldstein < -5
                        AND latitude IS NOT NULL
                        AND longitude IS NOT NULL
                        AND latitude BETWEEN %s AND %s
                        AND longitude BETWEEN %s AND %s
                    """,
                    (int(cutoff_date), min_lat, max_lat, min_lon, max_lon)
                )
                
                for row in cur.fetchall():
                    threat_lat = float(row[8])
                    threat_lon = float(row[9])
                    
                    distance_km = haversine_distance(lat, lon, threat_lat, threat_lon)
                    
                    if distance_km <= radius_km:
                        threats.append({
                            'source': 'GDELT',
                            'event_id': row[0],
                            'date': str(row[1]),
                            'actor1': row[2],
                            'actor2': row[3],
                            'country': row[4],
                            'severity': float(row[5]),
                            'articles': row[6],
                            'sources': row[7],
                            'distance_km': round(distance_km, 1),
                            'lat': threat_lat,
                            'lon': threat_lon
                        })
            
            # ================================================================
            # TODO: Add RSS, ACLED queries
            # ================================================================
            
            # Sort by distance, then severity
            threats.sort(key=lambda x: (x['distance_km'], -x['severity']))
            
            # Limit results
            threats = threats[:50]
            
            logger.info(f"[proximity] Found {len(threats)} threats near ({lat}, {lon}) within {radius_km}km")
            return threats
            
    except Exception as e:
        logger.error(f"[proximity] Location query failed: {e}")
        return []


def check_all_travelers(send_alerts: bool = True) -> Dict:
    """
    Check all active travelers for nearby threats.
    Run this on a schedule (hourly/daily).
    
    Args:
        send_alerts: Whether to actually send alerts (False for dry run)
    
    Returns:
        Summary of checks and alerts
    """
    get_conn_cm = _get_db_helpers()
    if not get_conn_cm:
        return {'error': 'Database unavailable'}
    
    try:
        with get_conn_cm() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, email, name, alert_radius_km 
                FROM traveler_profiles 
                WHERE active = true
            """)
            travelers = cur.fetchall()
        
        results = {
            'checked': len(travelers),
            'threats_found': 0,
            'alerts_sent': 0,
            'errors': 0
        }
        
        for traveler_id, email, name, radius_km in travelers:
            try:
                threats = find_threats_near_traveler(traveler_id, hours_lookback=24)
                
                if threats:
                    results['threats_found'] += len(threats)
                    
                    if send_alerts:
                        # Send alert (implement your email/SMS logic)
                        alert_sent = _send_threat_alert(traveler_id, email, name, threats)
                        if alert_sent:
                            results['alerts_sent'] += 1
                        else:
                            results['errors'] += 1
                    
            except Exception as e:
                logger.error(f"[proximity] Error checking traveler {traveler_id}: {e}")
                results['errors'] += 1
        
        logger.info(f"[proximity] Checked {results['checked']} travelers, found {results['threats_found']} threats")
        return results
        
    except Exception as e:
        logger.error(f"[proximity] Traveler check failed: {e}")
        return {'error': str(e)}


def _send_threat_alert(traveler_id: int, email: str, name: str, threats: List[Dict]) -> bool:
    """
    Send alert to traveler via email/SMS/push.
    
    TODO: Implement your actual notification logic here
    (SendGrid, Twilio, Firebase, etc.)
    """
    get_conn_cm = _get_db_helpers()
    if not get_conn_cm:
        return False
    
    try:
        # Log the alert
        with get_conn_cm() as conn:
            cur = conn.cursor()
            
            # Prevent duplicate alerts (check if sent recently)
            cur.execute("""
                SELECT COUNT(*) FROM proximity_alerts
                WHERE traveler_id = %s 
                  AND sent_at > NOW() - INTERVAL '6 hours'
            """, (traveler_id,))
            
            recent_count = cur.fetchone()[0]
            if recent_count > 0:
                logger.info(f"[proximity] Skipping alert for traveler {traveler_id} (already sent recently)")
                return False
            
            # Record alerts
            for threat in threats[:5]:  # Top 5 threats only
                cur.execute("""
                    INSERT INTO proximity_alerts(
                        traveler_id, threat_id, threat_source, threat_date,
                        distance_km, severity_score, alert_method
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    traveler_id,
                    threat.get('id') or threat.get('event_id'),
                    threat['source'],
                    threat.get('date'),
                    threat['distance_km'],
                    threat.get('severity'),
                    'email'
                ))
            
            # Update last alert time
            cur.execute("""
                UPDATE traveler_profiles
                SET last_alert_sent_at = NOW()
                WHERE id = %s
            """, (traveler_id,))
            
            conn.commit()
        
        # TODO: Actually send the email/SMS here
        logger.info(f"[proximity] Would send alert to {email} ({name}): {len(threats)} threats")
        
        # Example email content:
        # subject = f"⚠️ {len(threats)} Security Threats Near Your Location"
        # body = format_threat_alert_email(name, threats)
        # send_email(email, subject, body)
        
        return True
        
    except Exception as e:
        logger.error(f"[proximity] Failed to send alert: {e}")
        return False


def get_traveler_threat_history(traveler_id: int, days: int = 30) -> List[Dict]:
    """Get past alerts for a traveler"""
    get_conn_cm = _get_db_helpers()
    if not get_conn_cm:
        return []
    
    try:
        with get_conn_cm() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT 
                    threat_id, threat_source, threat_date,
                    distance_km, severity_score, sent_at
                FROM proximity_alerts
                WHERE traveler_id = %s
                  AND sent_at > NOW() - INTERVAL '%s days'
                ORDER BY sent_at DESC
            """, (traveler_id, days))
            
            history = []
            for row in cur.fetchall():
                history.append({
                    'threat_id': row[0],
                    'source': row[1],
                    'date': row[2].isoformat() if row[2] else None,
                    'distance_km': float(row[3]) if row[3] else 0,
                    'severity': float(row[4]) if row[4] else 0,
                    'alerted_at': row[5].isoformat()
                })
            
            return history
            
    except Exception as e:
        logger.error(f"[proximity] Failed to get history: {e}")
        return []
