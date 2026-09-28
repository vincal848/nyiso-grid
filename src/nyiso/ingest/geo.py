"""Approximate NYISO load-zone polygons.

No openly licensed NYISO zone boundary file exists (the NYPA ArcGIS layer forbids
redistribution). NYISO zones largely follow county lines, so we:
  1. take US Census county polygons for New York (public domain, via plotly/datasets),
  2. assign each county to the zone holding the most generator nodes inside it
     (counties with no generators take the zone of the nearest generator),
  3. dissolve counties by zone.
Drop an official file at data/ref/zones_override.geojson (property `zone`) to use it instead.
"""
from __future__ import annotations

import json
from collections import Counter

import pandas as pd
from shapely.geometry import Point, box, mapping, shape
from shapely.ops import unary_union

from nyiso.config import RAW, REF
from nyiso.ingest.mis_client import http_get

COUNTIES_URL = "https://raw.githubusercontent.com/plotly/datasets/master/geojson-counties-fips.json"
NY_FIPS = "36"

# Counties whose majority-vote assignment is known to be wrong or tie-prone
# (checked against NYISO's published zone map).
COUNTY_OVERRIDES = {
    "36005": "N.Y.C.", "36047": "N.Y.C.", "36061": "N.Y.C.", "36081": "N.Y.C.", "36085": "N.Y.C.",
    "36059": "LONGIL", "36103": "LONGIL",
    "36079": "HUD VL",   # Putnam
    "36051": "GENESE",   # Livingston
}
# Westchester is split: northern part is H (MILLWD), southern part is I (DUNWOD).
WESTCHESTER = "36119"
MILLWOOD_SPLIT_LAT = 41.13


def ny_counties(refresh: bool = False) -> list[dict]:
    dest = RAW / "ref" / "us_counties.geojson"
    if not dest.exists() or refresh:
        content = http_get(COUNTIES_URL)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
    fc = json.loads(dest.read_text(encoding="latin-1"))
    return [f for f in fc["features"] if f["properties"]["STATE"] == NY_FIPS]


def build_zones(nodes: pd.DataFrame) -> dict:
    override = REF / "zones_override.geojson"
    if override.exists():
        return json.loads(override.read_text())

    pts = nodes.dropna(subset=["lat", "lon"])
    pts = pts[pts["zone"].isin(set(pts["zone"]) - {"H Q", "NPX", "O H", "PJM"})]
    points = [(Point(r.lon, r.lat), r.zone) for r in pts.itertuples()]

    by_zone: dict[str, list] = {}
    county_zone = {}
    for f in ny_counties():
        geom = shape(f["geometry"])
        fips = f["id"]
        if fips == WESTCHESTER:
            minx, miny, maxx, maxy = geom.bounds
            by_zone.setdefault("MILLWD", []).append(geom.intersection(box(minx, MILLWOOD_SPLIT_LAT, maxx, maxy)))
            by_zone.setdefault("DUNWOD", []).append(geom.intersection(box(minx, miny, maxx, MILLWOOD_SPLIT_LAT)))
            county_zone["Westchester (N)"], county_zone["Westchester (S)"] = "MILLWD", "DUNWOD"
            continue
        if fips in COUNTY_OVERRIDES:
            zone = COUNTY_OVERRIDES[fips]
        else:
            votes = Counter(z for p, z in points if geom.contains(p))
            if votes:
                zone = votes.most_common(1)[0][0]
            else:
                c = geom.representative_point()
                zone = min(points, key=lambda pz: pz[0].distance(c))[1]
        county_zone[f["properties"]["NAME"]] = zone
        by_zone.setdefault(zone, []).append(geom)

    features = [{
        "type": "Feature",
        "properties": {"zone": z, "approximate": True,
                       "counties": sorted(n for n, zz in county_zone.items() if zz == z)},
        "geometry": mapping(unary_union(geoms).simplify(0.005, preserve_topology=True)),
    } for z, geoms in sorted(by_zone.items())]
    return {"type": "FeatureCollection", "features": features}
