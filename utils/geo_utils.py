"""geo_utils.py

Geographic utilities without PostGIS dependency.
Haversine distance, bounding boxes, coordinate validation.
"""

import math
from typing import Tuple, Optional

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate great-circle distance between two points in kilometers.
    
    Args:
        lat1, lon1: First point coordinates
        lat2, lon2: Second point coordinates
    
    Returns:
        Distance in kilometers
    """
    # Earth's radius in kilometers
    R = 6371.0
    
    # Convert degrees to radians
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)
    
    # Haversine formula
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    
    a = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    
    distance = R * c
    return distance


def bounding_box(lat: float, lon: float, radius_km: float) -> Tuple[float, float, float, float]:
    """
    Calculate bounding box for proximity search.
    
    Returns a square around the point for fast database filtering
    before calculating exact distances.
    
    Args:
        lat: Center latitude
        lon: Center longitude
        radius_km: Radius in kilometers
    
    Returns:
        (min_lat, max_lat, min_lon, max_lon)
    """
    # Approximate degrees per km (varies by latitude)
    lat_km = 111.0  # roughly 111km per degree latitude
    lon_km = 111.0 * math.cos(math.radians(lat))  # varies by latitude
    
    lat_delta = radius_km / lat_km
    lon_delta = radius_km / lon_km if lon_km > 0 else 0
    
    return (
        lat - lat_delta,  # min_lat
        lat + lat_delta,  # max_lat
        lon - lon_delta,  # min_lon
        lon + lon_delta   # max_lon
    )


def validate_coordinates(lat: Optional[float], lon: Optional[float]) -> bool:
    """
    Validate that coordinates are within valid ranges.
    
    Args:
        lat: Latitude (-90 to 90)
        lon: Longitude (-180 to 180)
    
    Returns:
        True if valid, False otherwise
    """
    if lat is None or lon is None:
        return False
    
    try:
        lat = float(lat)
        lon = float(lon)
        
        if not (-90 <= lat <= 90):
            return False
        if not (-180 <= lon <= 180):
            return False
        
        return True
    except (ValueError, TypeError):
        return False


def normalize_longitude(lon: float) -> float:
    """
    Normalize longitude to -180 to 180 range.
    
    Args:
        lon: Longitude value
    
    Returns:
        Normalized longitude
    """
    while lon > 180:
        lon -= 360
    while lon < -180:
        lon += 360
    return lon
