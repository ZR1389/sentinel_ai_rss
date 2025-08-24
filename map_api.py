# map_api.py — Map endpoints (static + GeoJSON incidents)
from __future__ import annotations

from flask import Blueprint, jsonify, send_from_directory, current_app, request
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional, Tuple
import json
import os
import unicodedata

try:
    # Preferred helper that returns list[dict]
    from db_utils import fetch_all
except Exception:
    fetch_all = None  # type: ignore

map_api = Blueprint("map_api", __name__, static_folder="web")

# Resolve absolute static dir
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_STATIC_DIR = map_api.static_folder if os.path.isabs(map_api.static_folder) \
    else os.path.join(_BASE_DIR, map_api.static_folder)

# Where to load polygons for reverse geocoding (place a copy of your countries.geojson here)
COUNTRIES_GEOJSON_PATH = os.getenv("COUNTRIES_GEOJSON_PATH") or os.path.join(_STATIC_DIR, "countries.geojson")

# ---------------- Static map files ----------------
@map_api.route("/map")
def serve_map():
    return send_from_directory(_STATIC_DIR, "index.html")

@map_api.route("/map/<path:path>")
def serve_map_static(path: str):
    return send_from_directory(_STATIC_DIR, path)

# ---------------- helpers ----------------
def _row_get(r: Any, key: str, idx: int | None = None):
    """Support tuple or dict rows seamlessly (we expect dicts from db_utils)."""
    if isinstance(r, dict):
        return r.get(key)
    if isinstance(r, (list, tuple)) and idx is not None:
        try:
            return r[idx]
        except Exception:
            return None
    return None

def _strip_accents(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))

# Common country-name normalization to match Natural Earth ADMIN names.
# Keys are LOWERCASE, accent-stripped variants → values are NE ADMIN names.
_NE_NAME_ALIASES: Dict[str, str] = {
    # United States
    "united states": "United States of America",
    "usa": "United States of America",
    "u.s.a": "United States of America",
    "us": "United States of America",
    "u.s.": "United States of America",
    "united states of america": "United States of America",
    # UK
    "united kingdom": "United Kingdom",
    "uk": "United Kingdom",
    "u.k.": "United Kingdom",
    "great britain": "United Kingdom",
    "britain": "United Kingdom",
    # Russia
    "russia": "Russian Federation",
    "russian federation": "Russian Federation",
    # Iran
    "iran": "Iran, Islamic Republic of",
    "iran islamic republic of": "Iran, Islamic Republic of",
    # Syria
    "syria": "Syrian Arab Republic",
    "syrian arab republic": "Syrian Arab Republic",
    # North/South Korea
    "north korea": "Korea, Democratic People's Republic of",
    "democratic peoples republic of korea": "Korea, Democratic People's Republic of",
    "dprk": "Korea, Democratic People's Republic of",
    "south korea": "Korea, Republic of",
    "republic of korea": "Korea, Republic of",
    # Czechia
    "czech republic": "Czechia",
    # Eswatini
    "swaziland": "Eswatini",
    # Turkey
    "turkey": "Türkiye",
    "tuerkiye": "Türkiye",
    "turkiye": "Türkiye",
    # Ivory Coast
    "cote divoire": "Côte d’Ivoire",
    "cote d ivoire": "Côte d’Ivoire",
    "cote d'ivoire": "Côte d’Ivoire",
    "ivory coast": "Côte d’Ivoire",
    # Cape Verde
    "cape verde": "Cabo Verde",
    # Burma/Myanmar
    "burma": "Myanmar",
    "myanmar (burma)": "Myanmar",
    # Macedonia
    "macedonia": "North Macedonia",
    "former yugoslav republic of macedonia": "North Macedonia",
    "fyrom": "North Macedonia",
    # Laos
    "laos": "Lao PDR",
    "lao pdr": "Lao PDR",
    # Congo naming
    "republic of the congo": "Republic of the Congo",
    "congo-brazzaville": "Republic of the Congo",
    "congo": "Republic of the Congo",  # adjust upstream if you need DRC vs ROC
    "democratic republic of the congo": "Democratic Republic of the Congo",
    "congo-kinshasa": "Democratic Republic of the Congo",
    # Palestine
    "palestine": "Palestine",
    "state of palestine": "Palestine",
    # Bolivia
    "bolivia": "Bolivia",
    "bolivia (plurinational state of)": "Bolivia",
    # Moldova
    "moldova": "Moldova",
    "republic of moldova": "Moldova",
    # Vatican
    "vatican": "Vatican",
    "vatican city": "Vatican",
}

def normalize_to_ne_admin(name: str) -> str:
    """
    Normalize a country string to Natural Earth's ADMIN field.
    If not found in alias map, returns original trimmed name.
    """
    if not name:
        return name
    raw = name.strip()
    low = _strip_accents(raw).lower().replace(".", "")
    return _NE_NAME_ALIASES.get(low, raw)

# --- Geo JSON cache & point-in-polygon (pure Python, no dependencies) ---
_COUNTRIES_CACHE: Optional[Dict[str, Any]] = None
_POLYS_INDEX: Optional[List[Tuple[str, List[List[Tuple[float,float]]]]]] = None
_BBOX_INDEX: Optional[List[Tuple[str, Tuple[float,float,float,float]]]] = None
_NAME_FIELD = "ADMIN"  # Natural Earth countries name key

def _load_countries() -> bool:
    """
    Load and cache countries.geojson (MultiPolygon/Polygon) into simple structures.
    Returns True if loaded.
    """
    global _COUNTRIES_CACHE, _POLYS_INDEX, _BBOX_INDEX
    if _POLYS_INDEX is not None and _BBOX_INDEX is not None:
        return True
    try:
        with open(COUNTRIES_GEOJSON_PATH, "r", encoding="utf-8") as f:
            gj = json.load(f)
        if not (gj and gj.get("type") == "FeatureCollection"):
            return False
        feats = gj.get("features") or []
        polys: List[Tuple[str, List[List[Tuple[float,float]]]]] = []
        bboxes: List[Tuple[str, Tuple[float,float,float,float]]] = []

        def rings_from_geom(geom: Dict[str, Any]) -> List[List[Tuple[float,float]]]:
            t = geom.get("type")
            coords = geom.get("coordinates")
            rs: List[List[Tuple[float,float]]] = []
            if t == "Polygon":
                for ring in coords or []:
                    rs.append([(float(x), float(y)) for x, y in ring])
            elif t == "MultiPolygon":
                for poly in coords or []:
                    for ring in poly:
                        rs.append([(float(x), float(y)) for x, y in ring])
            return rs

        def bbox_of(ring: List[Tuple[float,float]]) -> Tuple[float,float,float,float]:
            xs = [p[0] for p in ring]
            ys = [p[1] for p in ring]
            return (min(xs), min(ys), max(xs), max(ys))

        for ft in feats:
            props = ft.get("properties") or {}
            name = str(props.get(_NAME_FIELD) or "").strip()
            if not name:
                continue
            geom = ft.get("geometry") or {}
            rings = rings_from_geom(geom)
            if not rings:
                continue
            polys.append((name, rings))
            # overall bbox from outer ring of first polygon; cheap filter
            bb = bbox_of(rings[0])
            bboxes.append((name, bb))

        _COUNTRIES_CACHE = gj
        _POLYS_INDEX = polys
        _BBOX_INDEX = bboxes
        return True
    except Exception as e:
        try:
            current_app.logger.error("Failed to load countries geojson from %s: %s", COUNTRIES_GEOJSON_PATH, e)
        except Exception:
            pass
        _COUNTRIES_CACHE = None
        _POLYS_INDEX = None
        _BBOX_INDEX = None
        return False

def _point_in_ring(lon: float, lat: float, ring: List[Tuple[float,float]]) -> bool:
    """
    Ray-casting point-in-polygon for a single ring (lon,lat).
    Assumes ring is closed or not (works either way).
    """
    x, y = lon, lat
    inside = False
    n = len(ring)
    if n < 3:
        return False
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        intersect = ((y1 > y) != (y2 > y)) and (x < (x2 - x1) * (y - y1) / ( (y2 - y1) or 1e-16) + x1)
        if intersect:
            inside = not inside
    return inside

def _lonlat_to_country(lon: float, lat: float) -> Optional[str]:
    """
    Very lightweight reverse geocode: bbox prefilter + ring test on cached polygons.
    Returns country ADMIN name or None.
    """
    if _POLYS_INDEX is None or _BBOX_INDEX is None:
        if not _load_countries():
            return None
    assert _POLYS_INDEX is not None and _BBOX_INDEX is not None
    cands = []
    for name, (minx, miny, maxx, maxy) in _BBOX_INDEX:
        if (minx - 0.2) <= lon <= (maxx + 0.2) and (miny - 0.2) <= lat <= (maxy + 0.2):
            cands.append(name)
    if not cands:
        return None
    for name, rings in _POLYS_INDEX:
        if name not in cands:
            continue
        # Even–odd rule across rings
        inside_any = False
        for ring in rings:
            if _point_in_ring(lon, lat, ring):
                inside_any = not inside_any
        if inside_any:
            return name
    return None

@lru_cache(maxsize=10000)
def _lonlat_to_country_cached(lon: float, lat: float) -> Optional[str]:
    return _lonlat_to_country(lon, lat)

# ---------------- Geo data health ----------------
@map_api.route("/geo_health")
def geo_health():
    ok = _load_countries()
    size = 0
    try:
        if ok and _COUNTRIES_CACHE and isinstance(_COUNTRIES_CACHE.get("features"), list):
            size = len(_COUNTRIES_CACHE["features"])
    except Exception:
        size = 0
    exists = os.path.exists(COUNTRIES_GEOJSON_PATH)
    return jsonify({
        "ok": bool(ok),
        "countries_geojson_path": COUNTRIES_GEOJSON_PATH,
        "file_exists": bool(exists),
        "features": size
    })

# ---------------- Reverse country lookup ----------------
@map_api.route("/reverse_country")
def reverse_country():
    """
    GET /reverse_country?lat=<float>&lon=<float>
    Returns the Natural Earth ADMIN country for the given coordinates.
    """
    lat_s = request.args.get("lat", type=str)
    lon_s = request.args.get("lon", type=str)
    if lat_s is None or lon_s is None:
        return jsonify({"ok": False, "error": "Query params 'lat' and 'lon' are required"}), 400
    try:
        lat = float(lat_s)
        lon = float(lon_s)
    except Exception:
        return jsonify({"ok": False, "error": "lat/lon must be floats"}), 400

    if not _load_countries():
        return jsonify({"ok": False, "error": f"Failed to load countries.geojson from {COUNTRIES_GEOJSON_PATH}"}), 500

    country = _lonlat_to_country_cached(lon, lat)
    return jsonify({
        "ok": bool(country),
        "lat": lat,
        "lon": lon,
        "country": country
    }), 200

# ---------------- Incidents as GeoJSON ----------------
@map_api.route("/map_alerts")
def map_alerts():
    """
    Returns a FeatureCollection of recent alerts that have latitude/longitude.
    Output keys match your frontend expectations: risk_level, risk_color, risk_radius.
    """
    q = """
        SELECT
          uuid, title, summary, link, city, country, region, score,
          threat_level, latitude, longitude, published
        FROM alerts
        WHERE latitude IS NOT NULL AND longitude IS NOT NULL
        ORDER BY published DESC NULLS LAST
        LIMIT 500
    """

    rows: Iterable[Any] = []
    try:
        if fetch_all is None:
            raise RuntimeError("db_utils.fetch_all unavailable")
        rows = fetch_all(q) or []
    except Exception as e:
        try:
            current_app.logger.error("/map_alerts query failed: %s", e)
        except Exception:
            pass
        rows = []

    def to_feature(r: Any):
        lat = _row_get(r, "latitude")
        lon = _row_get(r, "longitude")
        try:
            lat = float(lat) if lat is not None else None
            lon = float(lon) if lon is not None else None
        except Exception:
            return None
        if lat is None or lon is None:
            return None

        risk_raw = _row_get(r, "threat_level") or "low"
        risk = str(risk_raw).strip().lower()

        # Normalize country (if provided). If country missing, leave as-is (frontend can still color via /country_risks).
        country_raw = _row_get(r, "country") or ""
        country_ne = normalize_to_ne_admin(str(country_raw)) if country_raw else country_raw

        return {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "uuid": _row_get(r, "uuid"),
                "title": _row_get(r, "title"),
                "summary": _row_get(r, "summary"),
                "link": _row_get(r, "link"),
                "city": _row_get(r, "city"),
                "country": country_ne,
                "region": _row_get(r, "region"),
                "score": _row_get(r, "score"),
                "risk_level": risk.capitalize(),
                "risk_color": {
                    "critical": "#d90429",
                    "high": "#ff7f50",
                    "moderate": "#ffe156",
                    "low": "#3bb2d0",
                }.get(risk, "#3bb2d0"),
                "risk_radius": {
                    "critical": 14,
                    "high": 11,
                    "moderate": 8,
                    "low": 6,
                }.get(risk, 6),
            },
        }

    features = []
    for r in rows:
        ft = to_feature(r)
        if ft:
            features.append(ft)

    return jsonify({"type": "FeatureCollection", "features": features})

# ---------------- Country risk aggregates (works even if country missing) ----------------
@map_api.route("/country_risks")
def country_risks():
    """
    Returns: {"by_country": {"United States of America":"high", "France":"moderate", ...}}
    Uses MAX severity across alerts for each country (critical > high > moderate > low).
    If alerts.country is NULL/empty, we derive the country from latitude/longitude using
    web/countries.geojson (pure-Python point-in-polygon).
    """
    q = """
        SELECT country, threat_level, latitude, longitude
        FROM alerts
        WHERE latitude IS NOT NULL AND longitude IS NOT NULL
        ORDER BY published DESC NULLS LAST
        LIMIT 4000
    """

    rows: List[Dict[str, Any]] = []
    try:
        if fetch_all is None:
            raise RuntimeError("db_utils.fetch_all unavailable")
        rows = fetch_all(q) or []
    except Exception as e:
        try:
            current_app.logger.error("/country_risks query failed: %s", e)
        except Exception:
            pass
        rows = []

    def sev(level: Optional[str]) -> int:
        s = (level or "low").strip().lower()
        return {"critical": 4, "high": 3, "moderate": 2, "low": 1}.get(s, 1)

    by_country_sev: Dict[str, int] = {}
    polygons_ok = _load_countries()

    for r in rows:
        raw_country = (r.get("country") or "").strip()
        lat = r.get("latitude")
        lon = r.get("longitude")
        level = r.get("threat_level") or "low"

        if raw_country:
            country_ne = normalize_to_ne_admin(raw_country)
        else:
            country_ne = None
            try:
                latf = float(lat) if lat is not None else None
                lonf = float(lon) if lon is not None else None
                if latf is not None and lonf is not None and polygons_ok:
                    country_ne = _lonlat_to_country_cached(lonf, latf)
            except Exception:
                country_ne = None

        if not country_ne:
            continue

        rank = sev(level)
        prev = by_country_sev.get(country_ne, 0)
        if rank > prev:
            by_country_sev[country_ne] = rank

    inv = {4: "critical", 3: "high", 2: "moderate", 1: "low"}
    by_country: Dict[str, str] = {name: inv.get(sev_val, "low") for name, sev_val in by_country_sev.items()}

    return jsonify({"by_country": by_country})
