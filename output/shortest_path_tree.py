"""
最短路径树图 —— 斗南 → 云南路网前 N 个最近基地
================================================
生成自包含 Leaflet HTML（file:// 直接可用）

边界底图数据：
  - continent.geojson         洲界
  - china_boundary.geojson    国界线
  - 云南行政区_市级.shp       云南地州界

路网数据：
  - yn_graph_cache.pkl        scgraph GeoGraph / 路网缓存
"""

import os, sys, json, pickle, math, struct, warnings
import numpy as np
from collections import OrderedDict

warnings.filterwarnings("ignore")

# ── paths ──────────────────────────────────────────────────────────
BASE       = r"C:/Users/Lenovo/Desktop/flower"
CACHE_PATH = BASE + "/output/yn_graph_cache.pkl"
PBF_PATH   = r"C:/Users/Lenovo/Downloads/yunnan-260722.osm.pbf"
CONTINENT  = BASE + "/geojson/continent.geojson"
CN_BOUND   = BASE + "/geojson/china_boundary.geojson"
CHINA_PROV = BASE + "/geojson/china_provinces.geojson"
YN_PREF    = BASE + "/B1_全球辐射/云南行政区_市级.shp"
OUT_HTML   = BASE + "/output/shortest_path_tree.html"

DOUNAN_LON, DOUNAN_LAT = 102.787, 24.902
FLOWER_BASES = BASE + "/B2_供应链/input/flower_bases_yn.shp"
N_PER_CITY = 999

# ═══════════════════════════════════════════════════════════════════
#  Helper: read GeoJSON (try various encodings)
# ═══════════════════════════════════════════════════════════════════
def read_geojson(path):
    for enc in ("utf-8", "gbk", "gb18030"):
        try:
            with open(path, encoding=enc) as f:
                return json.load(f)
        except Exception:
            continue
    raise ValueError(f"Cannot read {path}")

# ═══════════════════════════════════════════════════════════════════
#  Helper: shapefile → GeoJSON (with GBK field name fix)
# ═══════════════════════════════════════════════════════════════════
def shp_to_geojson(shp_path):
    """Read a shapefile and return a GeoJSON FeatureCollection (WGS84)."""
    import shapefile

    sf = shapefile.Reader(shp_path)

    # Extract field names from pyshp (they come as bytes in latin-1)
    field_names = []
    for f in sf.fields[1:]:  # skip DeletionFlag
        raw = f[0].encode("latin-1", errors="replace")
        try:
            nm = raw.decode("gbk").strip()
        except Exception:
            nm = raw.decode("utf-8", errors="replace").strip()
        if not nm:
            nm = f"field_{len(field_names)}"
        field_names.append(nm)

    features = []
    for idx in range(len(sf.records())):
        rec = sf.record(idx)
        shape = sf.shape(idx)

        # Properties
        props = OrderedDict()
        for j, nm in enumerate(field_names):
            val = rec[j]
            if isinstance(val, bytes):
                try:
                    val = val.decode("gbk")
                except Exception:
                    val = val.decode("utf-8", errors="replace")
            props[nm] = val

        # Geometry (convert to GeoJSON)
        def _parts_to_coords(shape):
            """Convert pyshp shape points (lon,lat) to GeoJSON coords."""
            pts = shape.points
            parts = list(shape.parts) + [len(pts)]
            rings = []
            for pi in range(len(parts) - 1):
                ring = []
                for j in range(parts[pi], parts[pi + 1]):
                    ring.append([pts[j][0], pts[j][1]])  # [lon, lat]
                # close ring if not closed
                if ring and ring[0] != ring[-1]:
                    ring.append(ring[0])
                rings.append(ring)
            return rings

        if shape.shapeType == 5:  # polygon
            rings = _parts_to_coords(shape)
            if len(rings) == 1:
                geom = {"type": "Polygon", "coordinates": rings}
            else:
                geom = {"type": "MultiPolygon", "coordinates": [[r] for r in rings]}
        elif shape.shapeType == 3:  # polyline
            rings = _parts_to_coords(shape)
            if len(rings) == 1:
                geom = {"type": "LineString", "coordinates": rings[0]}
            else:
                geom = {"type": "MultiLineString", "coordinates": rings}
        else:
            continue

        features.append({"type": "Feature", "properties": props, "geometry": geom})

    sf.close()
    return {"type": "FeatureCollection", "features": features}


# ═══════════════════════════════════════════════════════════════════
#  1  Load Yunnan road network (scgraph cache)
# ═══════════════════════════════════════════════════════════════════
print("─" * 54)
print("1  Loading road network")

if os.path.isfile(CACHE_PATH):
    with open(CACHE_PATH, "rb") as f:
        cache = pickle.load(f)
    GG = cache["geograph"]
    print(f"   OK  scgraph GeoGraph  |  {len(GG.nodes):,} nodes")
else:
    print("   Loading from PBF …")
    import osmnx as ox
    G_nx = ox.graph_from_file(PBF_PATH, simplify=False, retain_all=True)
    from scgraph.geographs import GeoGraph
    GG = GeoGraph()
    GG.load_from_osmnx_graph(G_nx)
    with open(CACHE_PATH, "wb") as f:
        pickle.dump({"geograph": GG, "node_coords": GG.nodes}, f)
    print(f"   OK  Built & cached  |  {len(GG.nodes):,} nodes")

G = GG.graph_object

# ═══════════════════════════════════════════════════════════════════
#  2  Render full road network as raster image (Pillow + Shapely)
# ═══════════════════════════════════════════════════════════════════
print("\n2  Rendering full road network as PNG …")
import base64
from io import BytesIO
from PIL import Image, ImageDraw
import shapefile as shp
from shapely.geometry import Polygon
from shapely.ops import unary_union

LON_MIN, LON_MAX = 97.0, 107.0
LAT_MIN, LAT_MAX = 21.0, 30.0
W, H = 3000, 3000

def geo_to_px(lon, lat):
    x = (lon - LON_MIN) / (LON_MAX - LON_MIN) * W
    y = (LAT_MAX - lat) / (LAT_MAX - LAT_MIN) * H
    return int(x), int(y)

# Load Yunnan boundary polygon
sf = shp.Reader(YN_PREF)
yn_polys = []
for i in range(len(sf.records())):
    s = sf.shape(i)
    pts = s.points
    parts = list(s.parts) + [len(pts)]
    for pi in range(len(parts) - 1):
        ring = [(pts[j][0], pts[j][1]) for j in range(parts[pi], parts[pi + 1])]
        if ring and ring[0] != ring[-1]:
            ring.append(ring[0])
        yn_polys.append(Polygon(ring))
yn_union = unary_union(yn_polys)
sf.close()
print(f"   Yunnan boundary loaded ({len(yn_polys)} rings)")

# Draw all edges within bbox onto transparent image
img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)
EDGE_COLOR = (176, 144, 96, 140)

edge_count = 0
for i in range(len(GG.graph)):
    lat_i, lon_i = GG.nodes[i][0], GG.nodes[i][1]
    if not (LON_MIN <= lon_i <= LON_MAX and LAT_MIN <= lat_i <= LAT_MAX):
        continue
    for j in GG.graph[i]:
        if j <= i:
            continue
        lat_j, lon_j = GG.nodes[j][0], GG.nodes[j][1]
        if not (LON_MIN <= lon_j <= LON_MAX and LAT_MIN <= lat_j <= LAT_MAX):
            continue
        x1, y1 = geo_to_px(lon_i, lat_i)
        x2, y2 = geo_to_px(lon_j, lat_j)
        draw.line([x1, y1, x2, y2], fill=EDGE_COLOR, width=1)
        edge_count += 1
        if edge_count % 200000 == 0:
            print(f"   ... {edge_count:,} edges drawn")

print(f"   Edges drawn: {edge_count:,}")

# Create Yunnan mask and clip
mask_img = Image.new("L", (W, H), 0)
mask_draw = ImageDraw.Draw(mask_img)
for poly in yn_polys:
    pts = [geo_to_px(lon, lat) for lon, lat in poly.exterior.coords]
    if len(pts) > 2:
        mask_draw.polygon(pts, fill=255)
    for interior in poly.interiors:
        hole = [geo_to_px(lon, lat) for lon, lat in interior.coords]
        if len(hole) > 2:
            mask_draw.polygon(hole, fill=0)

road_rgba = Image.new("RGBA", (W, H), (0, 0, 0, 0))
road_rgba.paste(img, (0, 0), mask_img)

buf = BytesIO()
road_rgba.save(buf, format="PNG")
buf.seek(0)
road_img_b64 = base64.b64encode(buf.read()).decode()
print(f"   PNG size: {len(road_img_b64) * 3 // 4 / 1024:.0f} KB")

# ═══════════════════════════════════════════════════════════════════
#  3  Nearest node → 斗南
# ═══════════════════════════════════════════════════════════════════
print("\n3  Locating 斗南")
dounan_id = GG.geokdtree.closest_idx((DOUNAN_LAT, DOUNAN_LON))
dounan_coord = GG.nodes[dounan_id]
print(f"   OK  Node #{dounan_id}  @  ({dounan_coord[1]:.4f}, {dounan_coord[0]:.4f})")

# ═══════════════════════════════════════════════════════════════════
#  4  Shortest path tree from 斗南 (Dijkstra)
# ═══════════════════════════════════════════════════════════════════
print(f"\n4  Shortest path tree (Dijkstra) …")
tree = G.get_shortest_path_tree(dounan_id)
pred = tree["predecessors"]
dmat = tree["distance_matrix"]

# ═══════════════════════════════════════════════════════════════════
#  5  Load flower bases → select nearest 15 per city
# ═══════════════════════════════════════════════════════════════════
print(f"\n4  Loading flower bases & selecting per-city")

import shapefile
sf_bases = shapefile.Reader(FLOWER_BASES)

# Decode city names and group bases by city
city_bases = {}  # city_name → [(node_id, dist, lon, lat, name, address)]
for i in range(len(sf_bases.records())):
    rec = sf_bases.record(i)
    shp = sf_bases.shape(i)
    lon, lat = shp.points[0][0], shp.points[0][1]

    # Decode string fields
    def _decode(v):
        if isinstance(v, bytes):
            try:
                return v.decode("gbk")
            except:
                return v.decode("utf-8", errors="replace")
        return str(v)

    name = _decode(rec[0])
    city = _decode(rec[1])
    addr = _decode(rec[2])

    # Find nearest graph node
    node_id = GG.geokdtree.closest_idx((lat, lon))
    dist_rad = dmat[node_id] if node_id < len(dmat) else float("inf")

    if dist_rad == float("inf") or dist_rad <= 0:
        continue  # unreachable

    if city not in city_bases:
        city_bases[city] = []
    city_bases[city].append((node_id, dist_rad, lon, lat, name, addr))

sf_bases.close()

# For each city, sort by Dijkstra distance and take top N_PER_CITY
selected = []  # (node_id, dist_rad, lon, lat, city, name)
city_counts = {}
for city, bases in sorted(city_bases.items()):
    bases.sort(key=lambda x: x[1])  # sort by distance
    picked = bases[:N_PER_CITY]
    city_counts[city] = len(picked)
    for node_id, dist_rad, lon, lat, name, addr in picked:
        selected.append((node_id, dist_rad, lon, lat, city, name))

selected.sort(key=lambda x: x[1])  # global sort by distance (for color scale)
print(f"   Total cities: {len(city_bases)}  |  Selected bases: {len(selected)}")
for city, cnt in sorted(city_counts.items(), key=lambda x: -x[1]):
    print(f"     {city}: {cnt}")
max_rad = selected[-1][1] if selected else 1

# ═══════════════════════════════════════════════════════════════════
#  5  Extract tree edges as GeoJSON
# ═══════════════════════════════════════════════════════════════════
print(f"\n6  Extracting path tree")

def haversine_km(lon1, lat1, lon2, lat2):
    R = 6371.0
    dlon = math.radians(lon2 - lon1)
    dlat = math.radians(lat2 - lat1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def reconstruct_path(pred, origin, dest):
    path = [dest]
    while path[-1] != origin:
        path.append(pred[path[-1]])
    return list(reversed(path))

collected_nodes = {dounan_id}
tree_edges = set()

for node_id, dist_rad, lon, lat, city, name in selected:
    path = reconstruct_path(pred, dounan_id, node_id)
    collected_nodes.update(path)
    for u, v in zip(path[:-1], path[1:]):
        tree_edges.add((u, v))

# Compute path distances FIRST (needed by merge logic below)
dest_dist_km = {}
dest_city = {}
for node_id, dist_rad, lon, lat, city, name in selected:
    path = reconstruct_path(pred, dounan_id, node_id)
    d_km = 0.0
    for u, v in zip(path[:-1], path[1:]):
        d_km += haversine_km(GG.nodes[u][1], GG.nodes[u][0], GG.nodes[v][1], GG.nodes[v][0])
    dest_dist_km[node_id] = d_km
    dest_city[node_id] = city

max_d_km = max(dest_dist_km.values()) if dest_dist_km else 1
print(f"   Max network distance: {max_d_km:.1f} km")

# Build edge GeoJSON — merge consecutive degree-2 nodes into path segments
children_of = {}
for u, v in tree_edges:
    children_of.setdefault(u, []).append(v)

segments = []  # each: {"coords": [[lon,lat],...], "max_dist": float}
stack = [(dounan_id, [])]  # (node, path_nodes_so_far)

while stack:
    node, path_nodes = stack.pop()
    new_path = path_nodes + [node]
    kids = children_of.get(node, [])
    if len(kids) == 1:
        stack.append((kids[0], new_path))
    else:
        if len(new_path) > 1:
            coords = [[GG.nodes[n][1], GG.nodes[n][0]] for n in new_path]
            maxd = max(dest_dist_km.get(n, 0) for n in new_path)
            segments.append({"coords": coords, "max_dist": maxd})
        if len(kids) > 1:
            for child in reversed(kids):
                stack.append((child, []))

print(f"   Merged segments: {len(segments):,}  (was {len(tree_edges):,} edges)")

edge_features = []
for seg in segments:
    coords = seg["coords"]
    if len(coords) < 2:
        continue
    edge_features.append({
        "type": "Feature",
        "properties": {"max_dist_km": round(seg["max_dist"], 3)},
        "geometry": {"type": "LineString", "coordinates": coords},
    })
    coords = seg["coords"]
    if len(coords) < 2:
        continue
    edge_features.append({
        "type": "Feature",
        "properties": {"max_dist_km": round(seg["max_dist"], 3)},
        "geometry": {"type": "LineString", "coordinates": coords},
    })

# Node features — only destination nodes (skip interior waypoints to reduce size)
node_features = []
for i, (node_id, dist_rad, lon, lat, city, name) in enumerate(selected):
    props = {"node_id": node_id, "city": city, "dist_km": round(dest_dist_km.get(node_id, 0), 3)}
    node_features.append({
        "type": "Feature", "properties": props,
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
    })

# Dounan feature
dounan_feature = {
    "type": "Feature",
    "properties": {"name": "斗南 Dounan", "node_id": dounan_id},
    "geometry": {"type": "Point", "coordinates": [dounan_coord[1], dounan_coord[0]]},
}

geo_tree_edges = {"type": "FeatureCollection", "features": edge_features}
geo_tree_nodes = {"type": "FeatureCollection", "features": node_features}

print(f"   OK  Edges: {len(edge_features):,}  |  Nodes: {len(node_features):,}")

# City breakdown for sidebar
city_breakdown_html = ""
for city, cnt in sorted(city_counts.items(), key=lambda x: -x[1]):
    city_breakdown_html += f'<div class="city-item"><span class="city-name">{city}</span><span class="city-count">{cnt}</span></div>'

# ═══════════════════════════════════════════════════════════════════
#  6  Read boundary GeoJSONs
# ═══════════════════════════════════════════════════════════════════
print(f"\n7  Reading boundary data")

geo_continent = read_geojson(CONTINENT)
print(f"   OK  Continent:  {len(geo_continent['features']):,} features")

raw_cn_bound = read_geojson(CN_BOUND)
# Filter: exclude features entirely within Yunnan bbox
YN_BBOX = {"lon_min": 97.5, "lon_max": 106.2, "lat_min": 21.1, "lat_max": 29.3}
def _all_outside_yn(coords):
    """Return True if ANY point is outside Yunnan bbox."""
    for c in coords:
        lon, lat = c[0], c[1]
        if not (YN_BBOX["lon_min"] <= lon <= YN_BBOX["lon_max"] and
                YN_BBOX["lat_min"] <= lat <= YN_BBOX["lat_max"]):
            return True
    return False
geo_cn_bound = {"type": "FeatureCollection", "features": []}
for feat in raw_cn_bound["features"]:
    geom = feat.get("geometry", {})
    if geom.get("type") == "LineString":
        if _all_outside_yn(geom["coordinates"]):
            geo_cn_bound["features"].append(feat)
    elif geom.get("type") == "MultiLineString":
        keep = [c for c in geom["coordinates"] if _all_outside_yn(c)]
        if keep:
            new_feat = dict(feat)
            new_feat["geometry"] = dict(geom)
            new_feat["geometry"]["coordinates"] = keep
            geo_cn_bound["features"].append(new_feat)
    else:
        geo_cn_bound["features"].append(feat)
print(f"   OK  China boundary (excl. Yunnan):  {len(geo_cn_bound['features']):,} features")

# China provinces — filter out Yunnan to create national fill layer
geo_provinces = read_geojson(CHINA_PROV)
geo_china_fill = {"type": "FeatureCollection", "features": []}
for feat in geo_provinces["features"]:
    pyname = feat["properties"].get("PYNAME") or ""
    if "Yunnan" not in pyname:
        geo_china_fill["features"].append(feat)
print(f"   OK  China provinces (excl. Yunnan):  {len(geo_china_fill['features']):,} features")

geo_yn_pref = shp_to_geojson(YN_PREF)
print(f"   OK  Yunnan prefectures:  {len(geo_yn_pref['features']):,} features")

# ═══════════════════════════════════════════════════════════════════
#  7  Generate Leaflet HTML
# ═══════════════════════════════════════════════════════════════════
print(f"\n8  Generating HTML …")

# Color function: orange→amber→brown based on distance ratio
# We'll do this in JS with HSL interpolation

html = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>云南路网 · 最短路径树 — 斗南至各市最近"""
html += str(N_PER_CITY)
html += r"""个基地</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  html, body { height: 100%; width: 100%; }
  body { margin: 0; padding: 0; }
  #map { width: 100%; height: 100vh; background: #fdf9f5; }
    width: 320px; background: #f8f3eb; border-left: 1px solid #dcd0c0;
    padding: 18px 16px; font-family: 'Segoe UI', system-ui, sans-serif;
    overflow-y: auto; color: #3d2b1f;
  }
  #sidebar h1 { font-size: 16px; font-weight: 700; margin-bottom: 4px; }
  #sidebar h2 { font-size: 13px; font-weight: 400; color: #7a634a; margin-bottom: 14px; }
  #sidebar .stat { font-size: 12px; color: #5c4a33; margin-bottom: 3px; }
  #sidebar .stat span { font-weight: 600; color: #3d2b1f; }
  #sidebar .legend-box { margin-top: 14px; }
  #sidebar .legend-box h3 { font-size: 12px; font-weight: 600; margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px; color: #7a634a; }
  #cbar { height: 18px; width: 100%; border-radius: 3px; margin-bottom: 4px; }
  .cbar-label { display: flex; justify-content: space-between; font-size: 11px; color: #7a634a; }
  .legend-item { display: flex; align-items: center; gap: 8px; font-size: 12px; margin: 4px 0; color: #3d2b1f; }
  .legend-item .swatch { width: 24px; height: 4px; border-radius: 2px; flex-shrink: 0; }
  .legend-item .swatch-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; border: 1px solid rgba(0,0,0,0.15); }
  .legend-item .swatch-star { font-size: 18px; line-height: 1; flex-shrink: 0; }
  .city-item { display: flex; justify-content: space-between; font-size: 11px; padding: 1px 0; color: #5c4a33; }
  .city-item span:last-child { font-weight: 600; color: #3d2b1f; }
  hr { border: none; border-top: 1px solid #dcd0c0; margin: 12px 0; }
  #sidebar .note { font-size: 11px; color: #a0907a; line-height: 1.5; margin-top: 8px; }

  .leaflet-control-legend {
    background: rgba(248,243,235,0.92); padding: 7px 11px; border-radius: 4px;
    font: 12px/1.6 'Segoe UI', system-ui, sans-serif; color: #3d2b1f;
    box-shadow: 0 1px 4px rgba(0,0,0,0.12);
  }
  .leaflet-control-legend .item { display: flex; align-items: center; gap: 5px; }
  .leaflet-control-legend .swatch { width: 18px; height: 3px; border-radius: 2px; flex-shrink: 0; }
  .leaflet-control-legend .dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
  .compass {
    width: 38px; height: 38px; background: rgba(248,243,235,0.9); border-radius: 4px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.12); display: flex; align-items: center;
    justify-content: center; font-size: 20px; cursor: default; color: #3d2b1f;
  }
</style>
</head>
<body>
<div id="map"></div>

<script>
// ===== EMBEDDED GeoJSON DATA =====
var EMBED_CONTINENT = """
html += json.dumps(geo_continent)
html += r""";
var EMBED_CN_BOUND = """
html += json.dumps(geo_cn_bound)
html += r""";

var EMBED_CHINA_FILL = """
html += json.dumps(geo_china_fill)
html += r""";

var EMBED_YN_PREF = """
html += json.dumps(geo_yn_pref)
html += r""";
var EMBED_TREE_EDGES = """
html += json.dumps(geo_tree_edges)
html += r""";
var EMBED_TREE_NODES = """
html += json.dumps(geo_tree_nodes)
html += r""";
var EMBED_DOUNAN = """
html += json.dumps(dounan_feature)
html += r""";
var EMBED_ROAD_NET = """
html += '"' + road_img_b64 + '"'
html += r""";

// ===== Color scale: orange → amber → brown (HSL) =====
// near: hsl(32, 80%, 55%)  vibrant orange
// mid:  hsl(40, 70%, 45%)  golden amber
// far:  hsl(25, 55%, 25%)  dark brown
function pathColor(ratio) {
  // ratio 0..1, 0 = near, 1 = far
  var r = Math.max(0, Math.min(1, ratio));
  var h = 32 - r * 7;       // 32 → 25
  var s = 80 - r * 25;      // 80 → 55
  var l = 55 - r * 30;      // 55 → 25
  return 'hsl(' + h + ', ' + s + '%, ' + l + '%)';
}

// ===== Map =====
var map = L.map('map', {
  center: [24.9, 102.8],
  zoom: 7,
  zoomControl: true,
  attributionControl: false,
  preferCanvas: true,
});

// Scale bar (bottom-right)
L.control.scale({position: 'bottomright', imperial: false, maxWidth: 280}).addTo(map);

// North arrow (top-right)
L.control({position: 'topright'}).onAdd = function() {
  var div = L.DomUtil.create('div', 'compass');
  div.innerHTML = '\u25B2<span style="font-size:10px;margin-left:2px">N</span>';
  div.title = '\u5317';
  return div;
};
// Can't chain onAdd, so call it separately
(function() {
  var ctrl = L.control({position: 'topright'});
  ctrl.onAdd = function() {
    var div = L.DomUtil.create('div', 'compass');
    div.innerHTML = '\u25B2<span style="font-size:10px;margin-left:2px">N</span>';
    return div;
  };
  ctrl.addTo(map);
})();

// Legend (bottom-left)
(function() {
  var ctrl = L.control({position: 'bottomleft'});
  ctrl.onAdd = function() {
    var div = L.DomUtil.create('div', 'leaflet-control-legend');
    div.innerHTML =
      '<div class="item"><span style="display:inline-block;width:16px;height:1.5px;background:#B09060;border-radius:1px;vertical-align:middle"></span> \u5168\u90e8\u8def\u7f51</div>' +
      '<div class="item"><span class="swatch" style="background:#a08460;opacity:0.85"></span>\u5df2\u5bfb\u8def\u5f84</div>' +
      '<div class="item"><span class="dot" style="background:#c9ad7a"></span>\u8def\u5f84\u8282\u70b9</div>' +
      '<div class="item"><span class="dot" style="background:#3d2b1f;width:12px;height:12px;border-radius:0;transform:rotate(45deg)"></span>\u57fa\u5730 (\u8ddd\u79bb\u8272)</div>' +
      '<div class="item">\u2b50 \u6597\u5357 Dounan</div>';
    return div;
  };
  ctrl.addTo(map);
})();

// ----- 1. Continent -----
var continentLayer = L.geoJSON(EMBED_CONTINENT, {
  style: {
    fillColor: '#E8D5B5', fillOpacity: 0.25,
    color: '#E8D5B5', weight: 0.6, opacity: 0.3,
  }
}).addTo(map).bringToBack();

// ----- 2. National boundary (line) -----
var cnBoundLayer = L.geoJSON(EMBED_CN_BOUND, {
  style: {
    color: '#C4A27A', weight: 1.8, opacity: 0.8,
    dashArray: '8,5',
  }
}).addTo(map);

// ----- 3. China fill (provinces excl. Yunnan) -----
var chinaFillLayer = L.geoJSON(EMBED_CHINA_FILL, {
  style: {
    fillColor: '#F5EFE2', fillOpacity: 0.35,
    color: 'transparent', weight: 0,
  }
}).addTo(map);

// ----- 4. Yunnan prefectures -----
var ynPrefLayer = L.geoJSON(EMBED_YN_PREF, {
  style: {
    fillColor: '#C49850', fillOpacity: 0.30,
    color: '#C49850', weight: 0.8, opacity: 0.45,
  },
  onEachFeature: function(feat, layer) {
    if (feat.properties.name) {
      layer.bindTooltip(feat.properties.name, { sticky: true, direction: 'center' });
    }
  }
}).addTo(map);

// ----- 5. Full road network (raster) -----
var roadOverlay = L.imageOverlay('data:image/png;base64,' + EMBED_ROAD_NET,
  [[21, 97], [30, 107]], {opacity: 1}
).addTo(map);

// ----- 6. Tree edges (merged segments, animated) -----
var treeEdgesLayer = L.layerGroup().addTo(map);

// Sort segments by max distance for wave animation
var sortedSegments = EMBED_TREE_EDGES.features.slice().sort(function(a, b) {
  return (a.properties.max_dist_km || 0) - (b.properties.max_dist_km || 0);
});

var animLines = [];
sortedSegments.forEach(function(f) {
  var coords = f.geometry.coordinates.map(function(c) { return [c[1], c[0]]; });
  var line = L.polyline(coords, {
    color: '#a08060',
    weight: 1.5,
    opacity: 0,
    smoothFactor: 0,
  }).addTo(treeEdgesLayer);
  line._maxDist = f.properties.max_dist_km || 0;
  animLines.push(line);
});

// ----- 7. Animation: Dijkstra explore → found → reset cycle -----
(function() {
  if (!animLines.length) return;

  var maxDist = sortedSegments.length > 0 ? sortedSegments[sortedSegments.length - 1].properties.max_dist_km : 1;
  if (maxDist <= 0) maxDist = 1;

  var N_BRACKETS = 18;
  var brackets = [];
  for (var i = 0; i < N_BRACKETS; i++) brackets.push([]);

  animLines.forEach(function(line, idx) {
    var ratio = line._maxDist / maxDist;
    var bi = Math.min(Math.floor(ratio * N_BRACKETS), N_BRACKETS - 1);
    brackets[bi].push(line);
  });

  while (brackets.length && brackets[brackets.length - 1].length === 0) brackets.pop();

  var ORANGE_FOUND = '#a08460';  // settled found paths
  var dotCenter = [EMBED_DOUNAN.geometry.coordinates[1], EMBED_DOUNAN.geometry.coordinates[0]];
  var dot = L.circleMarker(dotCenter, {
    radius: 6, fillColor: '#f28c28', fillOpacity: 1,
    weight: 2, color: '#fff', opacity: 1, zIndexOffset: 999,
  }).addTo(map);

  var currentBracket = 0;
  var isActive = true;
  var BRACKET_MS = 520, PULSE_MS = BRACKET_MS - 100, SETTLE_MS = 100;

  // Hide all, move dot to start
  function resetUnexplored() {
    animLines.forEach(function(line) { line.setStyle({opacity: 0, color: ORANGE_FOUND, weight: 1.5}); });
    dot.setLatLng(dotCenter);
    dot.setRadius(6);
    currentBracket = 0;
    isActive = true;
  }

  // Show all as found (orange)
  function showAllFound() {
    animLines.forEach(function(line) { line.setStyle({opacity: 0.85, color: ORANGE_FOUND, weight: 1.5}); });
  }

  // Phase 1: Explore bracket by bracket
  function animateBracket() {
    if (!isActive) return;

    if (currentBracket >= brackets.length) {
      // Phase 2: All found — show full orange map
      showAllFound();
      map.removeLayer(dot);
      setTimeout(function() {
        // Phase 3: Reset to unexplored, then loop
        resetUnexplored();
        dot.addTo(map);
        setTimeout(animateBracket, 600);
      }, 2800);
      return;
    }

    var edges = brackets[currentBracket];
    if (!edges.length) { currentBracket++; setTimeout(animateBracket, 20); return; }

    var pulseStart = performance.now();

    function pulseFrame(now) {
      var t = Math.min((now - pulseStart) / PULSE_MS, 1);
      var phase = t * Math.PI * 2 * 3.0;
      var raw = (Math.sin(phase) + 1) / 2;
      var intensity = raw * (1 - t * 0.2);
      var weight = 1.5 + intensity * 3.0;
      var opacity = 0.30 + intensity * 0.65;
      var r = Math.round(212 + intensity * (255 - 212));
      var g = Math.round(131 + intensity * (160 - 131));
      var b = Math.round(58 + intensity * (80 - 58));

      edges.forEach(function(line) {
        line.setStyle({weight: weight, opacity: opacity, color: 'rgb(' + r + ',' + g + ',' + b + ')'});
      });

      if (t < 1) {
        requestAnimationFrame(pulseFrame);
      } else {
        // Settle this bracket → orange (found)
        edges.forEach(function(line) { line.setStyle({opacity: 0.85, color: ORANGE_FOUND, weight: 1.5}); });
        currentBracket++;
        setTimeout(animateBracket, SETTLE_MS);
      }
    }
    requestAnimationFrame(pulseFrame);
  }

  animateBracket();

  var pulseDot = function() {
    if (dot._map) { dot.setRadius(5 + Math.sin(Date.now() / 120) * 2); requestAnimationFrame(pulseDot); }
  };
  setTimeout(pulseDot, 100);
})();

// ----- 8. Destination nodes (colored by distance) -----
var destNodes = L.geoJSON(EMBED_TREE_NODES, {
  pointToLayer: function(f, ll) {
    var maxD = 1;
    var ratio = f.properties.dist_km / maxD;
    var c = pathColor(ratio);
    return L.circleMarker(ll, {
      radius: Math.max(4 + (1 - ratio) * 3, 3),
      fillColor: c, fillOpacity: 0.85,
      weight: 0.5, color: 'rgba(0,0,0,0.15)',
    });
  },
  onEachFeature: function(f, layer) {
    var d = f.properties.dist_km;
    var ct = f.properties.city || '';
    layer.bindTooltip((ct ? '<b>' + ct + '</b><br>' : '') + '基地 #' + f.properties.node_id + '<br>距离: ' + d.toFixed(1) + ' km', {direction: 'top'});
  }
}).addTo(map);// ----- 10. Dounan star marker -----
var dounanIcon = L.divIcon({
  className: '',
  html: '<div style="font-size:32px;line-height:1;transform:translate(-50%,-50%);text-shadow:0 0 6px rgba(255,255,255,0.9)">⭐</div>',
  iconSize: [32, 32],
  iconAnchor: [16, 16],
});
var dounanMarker = L.marker(
  [""" + str(DOUNAN_LAT) + ", " + str(DOUNAN_LON) + """],
  { icon: dounanIcon, zIndexOffset: 1000 }
).addTo(map);
dounanMarker.bindTooltip('<b>斗南 Dounan</b><br>花卉交易中心', {direction: 'bottom'});

// ----- Layer ordering -----
continentLayer.bringToBack();
cnBoundLayer.bringToBack();
chinaFillLayer.bringToBack();
ynPrefLayer.bringToBack();
roadOverlay.bringToBack();
treeEdgesLayer.bringToBack();
</script>
</body>
</html>"""

with open(OUT_HTML, "w", encoding="utf-8") as f:
    f.write(html)

print(f"\n   OK  Saved →  {OUT_HTML}")
print("─" * 54)
