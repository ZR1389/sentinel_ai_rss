"""alerts_config_utils.py - Validation & sanitization for geofenced alerts configuration.

Shape (incoming JSON):
  alerts_config: {
      enabled: bool,
      channels: ["email", "sms"],
      radius_km: int (1-50),
      geofences: [ { id: str|int, lat: float, lon: float } ]
  }

Rules:
  - If missing or enabled = False -> returns a normalized disabled config.
  - Channels restricted to known set; duplicates removed; empty -> disabled.
  - radius_km clamped to 1..50 if enabled.
  - Geofences list limited to 25 entries (prevent payload bloat) and sanitized.
  - Invalid lat/lon or missing id -> entry dropped.
  - If resulting geofences empty -> enabled forced False.

Tier gating (BUSINESS, ENTERPRISE): Caller must pass user_plan; if not a business tier
the config is forced disabled regardless of client request.

Returned normalized structure always contains keys:
  {
    "enabled": bool,
    "channels": list[str],
    "radius_km": int | None,
    "geofences": list[dict]
  }

Raises ValueError only for grossly malformed types (non-dict) so that caller can
surface VALIDATION_ERROR; otherwise it auto-sanitizes.
"""

from __future__ import annotations
from typing import Any, Dict, List

ALLOWED_CHANNELS = {"email", "sms"}
BUSINESS_PLANS = {"BUSINESS", "ENTERPRISE"}

def validate_alerts_config(raw: Any, user_plan: str) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        # Treat non-dict as disabled rather than hard error to be forgiving
        return {"enabled": False, "channels": [], "radius_km": None, "geofences": []}

    enabled = bool(raw.get("enabled"))
    channels_raw = raw.get("channels") or []
    if not isinstance(channels_raw, list):
        channels_raw = []
    # Normalize channels
    channels: List[str] = []
    for ch in channels_raw:
        if isinstance(ch, str):
            ch_l = ch.strip().lower()
            if ch_l in ALLOWED_CHANNELS and ch_l not in channels:
                channels.append(ch_l)

    radius = raw.get("radius_km")
    if isinstance(radius, (int, float)):
        radius_int = int(radius)
    else:
        radius_int = None

    geofences_raw = raw.get("geofences") or []
    if not isinstance(geofences_raw, list):
        geofences_raw = []

    sanitized_geofences: List[Dict[str, Any]] = []
    for gf in geofences_raw:
        if not isinstance(gf, dict):
            continue
        gid = gf.get("id")
        lat = gf.get("lat")
        lon = gf.get("lon")
        if gid is None:
            continue
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            continue
        if lat < -90 or lat > 90 or lon < -180 or lon > 180:
            continue
        sanitized_geofences.append({"id": str(gid), "lat": float(lat), "lon": float(lon)})
        if len(sanitized_geofences) >= 25:
            break

    # Clamp radius if enabled
    if radius_int is not None:
        if radius_int < 1:
            radius_int = 1
        elif radius_int > 50:
            radius_int = 50

    # Determine final enabled state
    if not sanitized_geofences or not channels:
        enabled = False

    # Tier gating
    plan_norm = (user_plan or "").upper()
    if plan_norm not in BUSINESS_PLANS:
        enabled = False

    # If disabled, null radius & empty collections to reduce noise
    if not enabled:
        return {"enabled": False, "channels": [], "radius_km": None, "geofences": []}

    return {
        "enabled": True,
        "channels": channels,
        "radius_km": radius_int if radius_int is not None else 10,  # default 10km
        "geofences": sanitized_geofences
    }

__all__ = ["validate_alerts_config", "ALLOWED_CHANNELS", "BUSINESS_PLANS"]
