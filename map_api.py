from flask import Blueprint, jsonify, send_from_directory
from db_utils import fetch_all

map_api = Blueprint('map_api', __name__, static_folder='web')

@map_api.route('/map')
def serve_map():
    return send_from_directory(map_api.static_folder, 'index.html')

@map_api.route('/map/<path:path>')
def serve_map_static(path):
    return send_from_directory(map_api.static_folder, path)

@map_api.route('/map_alerts')
def map_alerts():
    q = """
        SELECT uuid, title, summary, link, city, country, region, score, threat_level, latitude, longitude, published
        FROM alerts
        WHERE latitude IS NOT NULL AND longitude IS NOT NULL
        ORDER BY published DESC
        LIMIT 500
    """
    rows = fetch_all(q)
    def feature(row):
        coords = [float(row['longitude']), float(row['latitude'])]
        risk = (row.get('threat_level') or "low").lower()
        return {
            "type": "Feature",
            "geometry": { "type": "Point", "coordinates": coords },
            "properties": {
                "uuid": row['uuid'],
                "title": row.get('title'),
                "summary": row.get('summary'),
                "link": row.get('link'),
                "city": row.get('city'),
                "country": row.get('country'),
                "region": row.get('region'),
                "score": row.get('score'),
                "risk_level": risk.capitalize(),
                "risk_color": {
                    "critical":"#d90429","high":"#ff7f50","moderate":"#ffe156","low":"#3bb2d0"
                }.get(risk, "#3bb2d0"),
                "risk_radius": {
                    "critical":14, "high":11, "moderate":8, "low":6
                }.get(risk, 6),
            }
        }
    geojson = {
        "type": "FeatureCollection",
        "features": [feature(row) for row in rows]
    }
    return jsonify(geojson)