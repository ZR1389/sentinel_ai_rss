"""gdelt_query.py

High-performance query layer for GDELT threat intelligence.
Works directly with gdelt_events table created by gdelt_ingest.py
"""

from typing import List, Dict, Optional
from datetime import datetime, timedelta
import logging

logger = logging.getLogger("gdelt_query")

def _get_db_helpers():
    """Reuse your existing db_utils connection helper"""
    try:
        from db_utils import _get_db_connection
        return _get_db_connection
    except Exception as e:
        logger.error("[gdelt_query] DB helpers unavailable: %s", e)
        return None


class GDELTQuery:
    
    @staticmethod
    def get_threats_near_location(lat: float, lon: float, radius_km: int = 50, days: int = 7) -> List[Dict]:
        """Get conflict events within radius of coordinates.
        
        Filters:
        - QuadClass 3 (Verbal Conflict) or 4 (Material Conflict)
        - Goldstein < -5 (significant negative events)
        - Last N days
        - Within radius_km
        """
        get_conn_cm = _get_db_helpers()
        if not get_conn_cm:
            return []
        
        cutoff_date = (datetime.utcnow() - timedelta(days=days)).strftime('%Y%m%d')
        
        query = """
        WITH threat_events AS (
            SELECT 
                global_event_id,
                sql_date,
                actor1,
                actor2,
                action_country,
                goldstein,
                num_articles,
                num_sources,
                action_lat,
                action_long,
                raw->60 as source_url,
                (
                    6371 * acos(
                        cos(radians(%s)) * cos(radians(action_lat)) *
                        cos(radians(action_long) - radians(%s)) +
                        sin(radians(%s)) * sin(radians(action_lat))
                    )
                ) AS distance_km
            FROM gdelt_events
            WHERE 
                sql_date >= %s
                AND quad_class IN (3, 4)
                AND goldstein < -5
                AND action_lat IS NOT NULL
                AND action_long IS NOT NULL
        )
        SELECT * FROM threat_events
        WHERE distance_km <= %s
        ORDER BY sql_date DESC, goldstein ASC
        LIMIT 50
        """
        
        try:
            with get_conn_cm() as conn:
                cur = conn.cursor()
                cur.execute(query, (lat, lon, lat, int(cutoff_date), radius_km))
                rows = cur.fetchall()
                
                results = []
                for row in rows:
                    results.append({
                        'event_id': row[0],
                        'date': str(row[1]),
                        'actor1': row[2],
                        'actor2': row[3],
                        'country': row[4],
                        'severity': abs(float(row[5])),  # Make positive for display
                        'articles': row[6],
                        'sources': row[7],
                        'lat': float(row[8]),
                        'lon': float(row[9]),
                        'source_url': row[10],
                        'distance_km': round(float(row[11]), 1)
                    })
                
                return results
                
        except Exception as e:
            logger.error("[gdelt_query] Location query failed: %s", e)
            return []
    
    @staticmethod
    def get_country_summary(country_code: str, days: int = 30) -> Optional[Dict]:
        """Aggregate threat metrics for a country."""
        get_conn_cm = _get_db_helpers()
        if not get_conn_cm:
            return None
        
        cutoff_date = (datetime.utcnow() - timedelta(days=days)).strftime('%Y%m%d')
        
        query = """
        SELECT 
            COUNT(*) as total_events,
            AVG(goldstein) as avg_severity,
            MIN(goldstein) as worst_severity,
            COUNT(DISTINCT actor1) as unique_actors,
            SUM(num_articles) as total_coverage,
            MAX(sql_date) as most_recent_date
        FROM gdelt_events
        WHERE 
            action_country = %s
            AND sql_date >= %s
            AND quad_class IN (3, 4)
            AND goldstein < -5
        """
        
        try:
            with get_conn_cm() as conn:
                cur = conn.cursor()
                cur.execute(query, (country_code, int(cutoff_date)))
                row = cur.fetchone()
                
                if not row or row[0] == 0:
                    return None
                
                return {
                    'country': country_code,
                    'period_days': days,
                    'total_events': row[0],
                    'avg_severity': abs(round(float(row[1]), 2)) if row[1] else 0,
                    'worst_severity': abs(round(float(row[2]), 2)) if row[2] else 0,
                    'unique_actors': row[3],
                    'total_coverage': row[4],
                    'most_recent': str(row[5]) if row[5] else None
                }
                
        except Exception as e:
            logger.error("[gdelt_query] Country summary failed: %s", e)
            return None
    
    @staticmethod
    def get_trending_threats(days: int = 7, min_articles: int = 10) -> List[Dict]:
        """Get most-covered conflict events recently."""
        get_conn_cm = _get_db_helpers()
        if not get_conn_cm:
            return []
        
        cutoff_date = (datetime.utcnow() - timedelta(days=days)).strftime('%Y%m%d')
        
        query = """
        SELECT 
            global_event_id,
            sql_date,
            actor1,
            actor2,
            action_country,
            goldstein,
            num_articles,
            num_sources,
            raw->60 as source_url
        FROM gdelt_events
        WHERE 
            sql_date >= %s
            AND quad_class IN (3, 4)
            AND goldstein < -5
            AND num_articles >= %s
        ORDER BY num_articles DESC, goldstein ASC
        LIMIT 20
        """
        
        try:
            with get_conn_cm() as conn:
                cur = conn.cursor()
                cur.execute(query, (int(cutoff_date), min_articles))
                rows = cur.fetchall()
                
                results = []
                for row in rows:
                    results.append({
                        'event_id': row[0],
                        'date': str(row[1]),
                        'actor1': row[2],
                        'actor2': row[3],
                        'country': row[4],
                        'severity': abs(float(row[5])),
                        'articles': row[6],
                        'sources': row[7],
                        'source_url': row[8]
                    })
                
                return results
                
        except Exception as e:
            logger.error("[gdelt_query] Trending query failed: %s", e)
            return []
