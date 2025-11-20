#!/usr/bin/env python3
import json
import os
import sys
import textwrap
from urllib.parse import urlencode

import requests

DEFAULT_URL = "https://sentinelairss-production.up.railway.app/api/map-alerts/aggregates"


def fetch_aggregates(url: str, params: dict) -> dict:
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def build_leaflet_html(payload: dict, title: str = "Aggregates Map") -> str:
    features = payload.get("features", [])
    meta = payload.get("meta", {})
    info = {
        "features": len(features),
        "aggregates": len(payload.get("aggregates", [])),
        "group": meta.get("group"),
        "days_back": meta.get("days_back"),
    }

    # Embed data as a JS variable. Keep only what's needed in the client.
    embedded = {
        "type": "FeatureCollection",
        "features": features,
    }

    html = f"""
    <!doctype html>
    <html>
    <head>
      <meta charset=\"utf-8\" />
      <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
      <title>{title}</title>
      <link rel=\"stylesheet\" href=\"https://unpkg.com/leaflet@1.9.4/dist/leaflet.css\" integrity=\"sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=\" crossorigin=\"\" />
      <style>
        html, body, #map {{ height: 100%; margin: 0; padding: 0; }}
        .legend {{ background: white; padding: 8px 12px; line-height: 1.4; box-shadow: 0 1px 4px rgba(0,0,0,0.2); }}
      </style>
    </head>
    <body>
      <div id=\"map\"></div>

      <script src=\"https://unpkg.com/leaflet@1.9.4/dist/leaflet.js\" integrity=\"sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=\" crossorigin=\"\"></script>
      <script>
        const featureCollection = {json.dumps(embedded)};

        const map = L.map('map').setView([20, 0], 2);
        L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
          maxZoom: 18,
          attribution: '&copy; OpenStreetMap contributors'
        }}).addTo(map);

        function markerStyle(props) {{
          const color = props.risk_color || '#2563eb';
          const count = props.count || 1;
          // Scale radius a bit so we see clusters distinctly (pixels)
          const r = Math.max(4, Math.min(24, Math.sqrt(count)));
          return {{
            radius: r,
            color: color,
            fillColor: color,
            fillOpacity: 0.6,
            weight: 1
          }};
        }}

        const layer = L.geoJSON(featureCollection, {{
          pointToLayer: (feature, latlng) => L.circleMarker(latlng, markerStyle(feature.properties)),
          onEachFeature: (feature, layer) => {{
            const p = feature.properties || {{}};
            const title = p.title || `${{p.country || p.region || p.city || 'Group'}} - ${{p.count || 0}} alerts`;
            const lines = [
              `<strong>${{title}}</strong>`,
              p.display_summary ? `<div style=\"margin-top:4px\">${{p.display_summary}}</div>` : '',
              p.avg_score ? `Avg score: ${{p.avg_score.toFixed ? p.avg_score.toFixed(2) : p.avg_score}}` : '',
              p.severity ? `Severity: ${{p.severity}}` : ''
            ].filter(Boolean);
            layer.bindPopup(lines.join('<br/>'));
          }}
        }}).addTo(map);

        if (layer.getBounds && layer.getLayers().length > 0) {{
          map.fitBounds(layer.getBounds().pad(0.2));
        }}

        // Simple legend/info box
        const infoDiv = L.control({{position: 'topright'}});
        infoDiv.onAdd = function() {{
          const div = L.DomUtil.create('div', 'legend');
          div.innerHTML = `
            <div><strong>Aggregates</strong></div>
            <div>Features: {info['features']}</div>
            <div>Aggregates: {info['aggregates']}</div>
            <div>Group: {info['group']}</div>
            <div>Days back: {info['days_back']}</div>
          `;
          return div;
        }};
        infoDiv.addTo(map);
      </script>
    </body>
    </html>
    """
    return textwrap.dedent(html)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Render aggregates as a local Leaflet HTML map")
    ap.add_argument("--url", default=DEFAULT_URL, help="Aggregates endpoint URL")
    ap.add_argument("--by", default="country", choices=["country", "region", "city"], help="Group by level")
    ap.add_argument("--days-back", type=int, default=30, help="Days back window")
    ap.add_argument("--outfile", default="aggregates_map.html", help="Output HTML file")
    args = ap.parse_args()

    params = {"by": args.by, "days_back": args.days_back}

    print(f"Fetching: {args.url}?{urlencode(params)}")
    payload = fetch_aggregates(args.url, params)
    ok = payload.get("ok", True)
    if not ok:
        print("Endpoint indicated failure:", payload)
        sys.exit(1)

    features = payload.get("features", [])
    aggregates = payload.get("aggregates", [])
    print(f"Features: {len(features)}, Aggregates: {len(aggregates)}")
    if features:
        f0 = features[0]
        print("Sample feature type:", f0.get("type"), "geom:", f0.get("geometry", {}).get("type"))
        print("Sample props keys:", list((f0.get("properties") or {}).keys())[:10])

    html = build_leaflet_html(payload)
    with open(args.outfile, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Wrote: {args.outfile}. Open it in a browser to verify.")


if __name__ == "__main__":
    main()
