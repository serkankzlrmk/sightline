#!/usr/bin/env python3
"""Generate a simplified world map SVG from Natural Earth data.

Usage:
    python scripts/generate_world_map.py           # 50m (default, more detail)
    python scripts/generate_world_map.py --110m     # 110m (lighter, less detail)
    python scripts/generate_world_map.py --10m      # 10m (very detailed, ~300KB SVG)

Output:
    static/world-map.svg

Requires: geopandas, shapely
"""

import os
import sys

try:
    import geopandas as gpd
    from shapely.geometry import mapping
except ImportError:
    print("Error: geopandas and shapely are required.")
    print("Install with: pip install geopandas shapely")
    sys.exit(1)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)

RESOLUTIONS = {
    "110m": {
        "file": "ne_110m_countries.geojson",
        "tolerance": 0.5,
        "url": "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_countries.geojson",
    },
    "50m": {
        "file": "ne_50m_countries.geojson",
        "tolerance": 0.3,
        "url": "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson",
    },
    "10m": {
        "file": "ne_10m_countries.geojson",
        "tolerance": 0.15,
        "url": "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_0_countries.geojson",
    },
}

res_key = "50m"
if "--110m" in sys.argv:
    res_key = "110m"
elif "--10m" in sys.argv:
    res_key = "10m"

RES = RESOLUTIONS[res_key]
GEOJSON_PATH = os.path.join(PROJECT_DIR, "static", RES["file"])
OUTPUT_PATH = os.path.join(PROJECT_DIR, "static", "world-map.svg")

SVG_W = 1000
SVG_H = 500

CRISIS_COUNTRIES = {
    "SDN": {"name": "Sudan", "lat": 15.5, "lng": 32.5},
    "UKR": {"name": "Ukraine", "lat": 48.4, "lng": 31.2},
    "SYR": {"name": "Syria", "lat": 35.0, "lng": 38.0},
    "ETH": {"name": "Ethiopia", "lat": 9.1, "lng": 40.5},
    "COD": {"name": "Dem. Rep. Congo", "lat": -2.5, "lng": 23.6},
    "YEM": {"name": "Yemen", "lat": 15.5, "lng": 48.5},
    "MMR": {"name": "Myanmar", "lat": 19.7, "lng": 96.2},
    "AFG": {"name": "Afghanistan", "lat": 33.9, "lng": 67.7},
    "SOM": {"name": "Somalia", "lat": 5.1, "lng": 46.2},
    "SSD": {"name": "S. Sudan", "lat": 6.9, "lng": 31.3},
    "NER": {"name": "Niger", "lat": 17.6, "lng": 8.1},
    "MLI": {"name": "Mali", "lat": 17.6, "lng": -4.0},
    "BFA": {"name": "Burkina Faso", "lat": 12.2, "lng": -1.5},
    "CMR": {"name": "Cameroon", "lat": 7.4, "lng": 12.3},
    "NGA": {"name": "Nigeria", "lat": 9.1, "lng": 8.7},
    "TCD": {"name": "Chad", "lat": 15.5, "lng": 18.7},
    "PSE": {"name": "Palestine", "lat": 31.9, "lng": 35.2},
    "LBN": {"name": "Lebanon", "lat": 33.9, "lng": 35.5},
    "VEN": {"name": "Venezuela", "lat": 6.4, "lng": -66.6},
    "COL": {"name": "Colombia", "lat": 4.6, "lng": -74.1},
    "HTI": {"name": "Haiti", "lat": 18.9, "lng": -72.3},
    "BDI": {"name": "Burundi", "lat": -3.4, "lng": 30.0},
    "CAF": {"name": "Central African Rep.", "lat": 6.6, "lng": 20.9},
    "IRN": {"name": "Iran", "lat": 32.4, "lng": 53.7},
    "PAK": {"name": "Pakistan", "lat": 30.4, "lng": 69.3},
    "IRQ": {"name": "Iraq", "lat": 33.2, "lng": 43.7},
    "LBY": {"name": "Libya", "lat": 26.3, "lng": 17.2},
    "ERI": {"name": "Eritrea", "lat": 15.2, "lng": 39.8},
    "MOZ": {"name": "Mozambique", "lat": -18.7, "lng": 35.5},
}

CRISIS_NAMES = set(v["name"] for v in CRISIS_COUNTRIES.values())

# Natural Earth name mapping (our name -> their name)
NAME_MAP = {
    "Dem. Rep. Congo": "Dem. Rep. Congo",
    "S. Sudan": "S. Sudan",
    "Central African Rep.": "Central African Rep.",
}


def lon_lat_to_svg(lon, lat):
    x = ((lon + 180) / 360) * SVG_W
    y = ((90 - lat) / 180) * SVG_H
    return x, y


def geometry_to_svg_path(geom, tolerance=0.5):
    if geom.geom_type == "Polygon":
        coords = list(geom.exterior.coords)
        path = "M " + " L ".join(f"{lon_lat_to_svg(lon, lat)[0]:.1f},{lon_lat_to_svg(lon, lat)[1]:.1f}" for lon, lat in coords) + " Z"
        for interior in geom.interiors:
            hole_coords = list(interior.coords)
            path += " M " + " L ".join(f"{lon_lat_to_svg(lon, lat)[0]:.1f},{lon_lat_to_svg(lon, lat)[1]:.1f}" for lon, lat in hole_coords) + " Z"
        return path
    elif geom.geom_type == "MultiPolygon":
        paths = []
        for poly in geom.geoms:
            coords = list(poly.exterior.coords)
            p = "M " + " L ".join(f"{lon_lat_to_svg(lon, lat)[0]:.1f},{lon_lat_to_svg(lon, lat)[1]:.1f}" for lon, lat in coords) + " Z"
            for interior in poly.interiors:
                hole_coords = list(interior.coords)
                p += " M " + " L ".join(f"{lon_lat_to_svg(lon, lat)[0]:.1f},{lon_lat_to_svg(lon, lat)[1]:.1f}" for lon, lat in hole_coords) + " Z"
            paths.append(p)
        return " ".join(paths)
    return ""


def main():
    if not os.path.exists(GEOJSON_PATH):
        print(f"Error: {GEOJSON_PATH} not found.")
        print(f"Download from: {RES['url']}")
        sys.exit(1)

    print(f"Loading Natural Earth {res_key} data from {GEOJSON_PATH}...")
    world = gpd.read_file(GEOJSON_PATH)
    print(f"Loaded {len(world)} countries")

    simplified = world.copy()
    simplified["geometry"] = simplified["geometry"].simplify(tolerance=RES["tolerance"], preserve_topology=True)
    svg_parts = []
    svg_parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SVG_W} {SVG_H}" preserveAspectRatio="xMidYMid meet">')
    svg_parts.append('  <!-- Ocean background -->')
    svg_parts.append(f'  <rect width="{SVG_W}" height="{SVG_H}" fill="rgba(245,245,247,1)"/>')

    svg_parts.append('  <!-- Graticule grid -->')
    svg_parts.append('  <g stroke="rgba(0,0,0,.04)" stroke-width=".5" fill="none">')
    for lat in range(-60, 90, 30):
        _, y = lon_lat_to_svg(0, lat)
        svg_parts.append(f'    <line x1="0" y1="{y:.1f}" x2="{SVG_W}" y2="{y:.1f}"/>')
    for lon in range(-180, 180, 30):
        x, _ = lon_lat_to_svg(lon, 0)
        svg_parts.append(f'    <line x1="{x:.1f}" y1="0" x2="{x:.1f}" y2="{SVG_H}"/>')
    svg_parts.append('  </g>')

    svg_parts.append('  <!-- Equator -->')
    _, eq_y = lon_lat_to_svg(0, 0)
    svg_parts.append(f'  <line x1="0" y1="{eq_y:.1f}" x2="{SVG_W}" y2="{eq_y:.1f}" stroke="rgba(0,0,0,.08)" stroke-width=".8" stroke-dasharray="4 4"/>')

    svg_parts.append('  <!-- Country landmasses -->')
    svg_parts.append('  <g id="countries">')

    crisis_count = 0
    for _, row in simplified.iterrows():
        name = row.get("NAME", "")
        iso = row.get("ISO_A3_EH", row.get("ADM0_A3", ""))

        is_crisis = name in CRISIS_NAMES

        try:
            path_d = geometry_to_svg_path(row.geometry)
        except Exception as e:
            print(f"  Skipping {name}: {e}")
            continue

        if not path_d or len(path_d) < 10:
            continue

        if is_crisis:
            fill = "rgba(0,122,255,.06)"
            stroke = "rgba(0,122,255,.2)"
            crisis_count += 1
        else:
            fill = "rgba(0,0,0,.05)"
            stroke = "rgba(0,0,0,.08)"

        svg_parts.append(f'    <path d="{path_d}" fill="{fill}" stroke="{stroke}" stroke-width=".6" stroke-linejoin="round" id="country-{iso}" data-name="{name}"/>')

    svg_parts.append('  </g>')
    svg_parts.append('</svg>')

    svg_content = "\n".join(svg_parts)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(svg_content)

    size_kb = len(svg_content) / 1024
    print(f"\nGenerated: {OUTPUT_PATH}")
    print(f"Size: {size_kb:.1f} KB")
    print(f"Countries: {len(simplified)}")
    print(f"Crisis countries highlighted: {crisis_count}")

    js_crisis = "const CRISIS_COUNTRIES = {\n"
    for code, info in CRISIS_COUNTRIES.items():
        js_crisis += f'  "{code}": {{ "name": "{info["name"]}", "lat": {info["lat"]}, "lng": {info["lng"]} }},\n'
    js_crisis += "};"
    print("\nJS CRISIS_COUNTRIES for app.js:")
    print(js_crisis)


if __name__ == "__main__":
    main()
