"""alert_engine_stub.py - Placeholder geofenced alert evaluation logic.

Intended workflow (future implementation):
 1. Batch ingest new threats/incidents with lat/lon.
 2. Load active itineraries where data.alerts_config.enabled = true.
 3. For each unique geofence point (reverse index) compute nearby threats within max radius (<=50km).
 4. Debounce via hashing (itinerary_uuid + geofence_id + threat_id) stored in fast lookup (Redis / DB table).
 5. Respect per-itinerary rate limits (<=5 alerts/hour).
 6. Queue notifications per channel (email, sms) using existing dispatchers.

This stub exposes a single evaluate_threats function signature to be wired later.
"""

from __future__ import annotations
from typing import List, Dict, Any
import math

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def evaluate_threats(threats: List[Dict[str, Any]], itineraries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Evaluate threats against enabled geofenced alerts configs.

    Returns a list of alert events (not yet dispatched). Each event structure:
      {
        'itinerary_uuid': str,
        'geofence_id': str,
        'distance_km': float,
        'channels': ['email','sms'],
        'threat_ref': threat_dict
      }
    This does NOT persist or send notifications; caller will handle that.
    """
    alerts: List[Dict[str, Any]] = []
    for itin in itineraries:
        data = itin.get('data') or {}
        cfg = data.get('alerts_config') or {}
        if not cfg.get('enabled'):
            continue
        radius = cfg.get('radius_km') or 0
        geofences = cfg.get('geofences') or []
        channels = cfg.get('channels') or []
        if radius <= 0 or not geofences or not channels:
            continue
        for gf in geofences:
            glat = gf.get('lat'); glon = gf.get('lon'); gid = gf.get('id')
            if glat is None or glon is None or gid is None:
                continue
            for threat in threats:
                tlat = threat.get('latitude'); tlon = threat.get('longitude')
                if tlat is None or tlon is None:
                    continue
                dist = _haversine_km(glat, glon, tlat, tlon)
                if dist <= radius:
                    alerts.append({
                        'itinerary_uuid': itin.get('itinerary_uuid'),
                        'geofence_id': gid,
                        'distance_km': round(dist, 2),
                        'channels': channels,
                        'threat_ref': threat
                    })
    return alerts

__all__ = ['evaluate_threats']
