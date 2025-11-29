"""alert_engine_stub.py - Geofenced alert evaluation with rate limiting & debounce.

Complete workflow:
 1. Batch ingest new threats/incidents with lat/lon.
 2. Load active itineraries where data.alerts_config.enabled = true.
 3. For each unique geofence point compute nearby threats within configured radius (<=50km).
 4. Debounce via SHA256 hash (itinerary_uuid + geofence_id + threat_id) with 24h TTL.
 5. Enforce per-itinerary rate limits (5 alerts/hour max).
 6. Return filtered alert events ready for notification dispatch.

Integration points:
- alert_rate_limiter: Redis-backed debounce + rate limiting with in-memory fallback
- Dispatchers (email_dispatcher, telegram_dispatcher): Called by consumer after evaluation
"""

from __future__ import annotations
from typing import List, Dict, Any, Tuple
import math
import logging
from alert_rate_limiter import (
    is_alert_debounced,
    mark_alert_sent,
    check_rate_limit,
    increment_rate_limit,
    get_rate_limit_stats
)

logger = logging.getLogger(__name__)

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def evaluate_threats(
    threats: List[Dict[str, Any]], 
    itineraries: List[Dict[str, Any]],
    apply_rate_limiting: bool = True,
    apply_debounce: bool = True
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Evaluate threats against enabled geofenced alerts configs.
    
    Args:
        threats: List of threat dicts with 'latitude', 'longitude', and unique 'id'
        itineraries: List of itinerary dicts with alerts_config enabled
        apply_rate_limiting: If True, enforce 5 alerts/hour per itinerary (default True)
        apply_debounce: If True, suppress duplicate alerts within 24h (default True)
    
    Returns:
        Tuple of (alerts, stats):
        - alerts: List of alert event dicts ready for dispatch:
          {
            'itinerary_uuid': str,
            'geofence_id': str,
            'distance_km': float,
            'channels': ['email','sms'],
            'threat_ref': threat_dict
          }
        - stats: Evaluation statistics:
          {
            'total_candidates': int,       # Alerts matched by distance
            'debounced': int,               # Suppressed by debounce
            'rate_limited': int,            # Suppressed by rate limit
            'allowed': int,                 # Alerts ready to send
            'per_itinerary': {              # Per-itinerary breakdown
              'uuid-123': {
                'candidates': 5,
                'debounced': 2,
                'rate_limited': 1,
                'allowed': 2,
                'rate_limit_stats': {...}
              }
            }
          }
    
    Processing flow:
    1. Haversine distance matching (geofence radius check)
    2. Debounce filtering (24h TTL on itinerary+geofence+threat combo)
    3. Rate limit enforcement (5 alerts/hour per itinerary)
    4. Mark allowed alerts as sent (update debounce + rate limit counters)
    """
    alerts: List[Dict[str, Any]] = []
    stats = {
        'total_candidates': 0,
        'debounced': 0,
        'rate_limited': 0,
        'allowed': 0,
        'per_itinerary': {}
    }
    
    for itin in itineraries:
        itin_uuid = itin.get('itinerary_uuid')
        if not itin_uuid:
            continue
            
        # Initialize per-itinerary stats
        itin_stats = {
            'candidates': 0,
            'debounced': 0,
            'rate_limited': 0,
            'allowed': 0,
            'rate_limit_stats': {}
        }
        
        data = itin.get('data') or {}
        cfg = data.get('alerts_config') or {}
        if not cfg.get('enabled'):
            continue
            
        radius = cfg.get('radius_km') or 0
        geofences = cfg.get('geofences') or []
        channels = cfg.get('channels') or []
        if radius <= 0 or not geofences or not channels:
            continue
        
        # Get current rate limit status
        rate_limit_stats = get_rate_limit_stats(itin_uuid) if apply_rate_limiting else None
        itin_stats['rate_limit_stats'] = rate_limit_stats
        
        for gf in geofences:
            glat = gf.get('lat')
            glon = gf.get('lon')
            gid = gf.get('id')
            if glat is None or glon is None or gid is None:
                continue
                
            for threat in threats:
                tlat = threat.get('latitude')
                tlon = threat.get('longitude')
                tid = threat.get('id')
                if tlat is None or tlon is None or tid is None:
                    continue
                    
                dist = _haversine_km(glat, glon, tlat, tlon)
                if dist <= radius:
                    # Candidate alert (within geofence radius)
                    stats['total_candidates'] += 1
                    itin_stats['candidates'] += 1
                    
                    # Check debounce (has this exact alert been sent recently?)
                    if apply_debounce and is_alert_debounced(itin_uuid, gid, tid):
                        stats['debounced'] += 1
                        itin_stats['debounced'] += 1
                        logger.debug(
                            "[alert_engine] Debounced: itinerary=%s geofence=%s threat=%s", 
                            itin_uuid, gid, tid
                        )
                        continue
                    
                    # Check rate limit (has itinerary exceeded 5 alerts/hour?)
                    if apply_rate_limiting:
                        allowed, current_count, limit = check_rate_limit(itin_uuid)
                        if not allowed:
                            stats['rate_limited'] += 1
                            itin_stats['rate_limited'] += 1
                            logger.warning(
                                "[alert_engine] Rate limited: itinerary=%s (count=%d/%d)", 
                                itin_uuid, current_count, limit
                            )
                            continue
                    
                    # Alert allowed - add to results
                    alert_event = {
                        'itinerary_uuid': itin_uuid,
                        'geofence_id': gid,
                        'distance_km': round(dist, 2),
                        'channels': channels,
                        'threat_ref': threat
                    }
                    alerts.append(alert_event)
                    stats['allowed'] += 1
                    itin_stats['allowed'] += 1
                    
                    # Mark as sent (update debounce + rate limit)
                    if apply_debounce:
                        mark_alert_sent(itin_uuid, gid, tid)
                    if apply_rate_limiting:
                        increment_rate_limit(itin_uuid)
                    
                    logger.info(
                        "[alert_engine] Alert allowed: itinerary=%s geofence=%s threat=%s distance=%.2fkm",
                        itin_uuid, gid, tid, dist
                    )
        
        # Store per-itinerary stats
        if itin_stats['candidates'] > 0:
            stats['per_itinerary'][itin_uuid] = itin_stats
    
    return alerts, stats

__all__ = ['evaluate_threats', 'get_rate_limit_stats']
