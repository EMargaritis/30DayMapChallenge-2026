#!/usr/bin/env python3
"""
Chatty Maps London replication, step 3: street segments from OpenStreetMap.

Paper (section 2.2 and footnote 3): a segment is "often a street's portion between two road
intersections but, more generally, it includes any outdoor place (e.g. highways, squares,
steps, footpaths, cycle-ways)". We therefore take every OSM way with a highway tag and split it
at intersection nodes (nodes shared with another highway way) and at its two ends.

Output: segments_london.gpkg (EPSG:27700, British National Grid) with columns
  seg_id, way_id, highway, length_m, geometry
"""
import os, sys, time
from array import array
import numpy as np
import osmium
import shapely
import geopandas as gpd

HERE = os.path.dirname(os.path.abspath(__file__))
PBF = os.path.join(HERE, "london.osm.pbf")
OUT = os.path.join(HERE, "segments_london.gpkg")
# Assumption A-seg-3: every highway value is a segment type except these non street values
EXCLUDE = {"proposed", "corridor", "elevator", "razed", "abandoned", "disused"}

t0 = time.time()
way_id, way_hw, way_start = [], [], [0]
refs, lons, lats = array("q"), array("d"), array("d")
for o in osmium.FileProcessor(PBF, osmium.osm.NODE | osmium.osm.WAY).with_locations():
    if not o.is_way():
        continue
    hw = o.tags.get("highway")
    if not hw or hw in EXCLUDE:
        continue
    try:
        pts = [(n.ref, n.lon, n.lat) for n in o.nodes]
    except osmium.InvalidLocationError:
        continue
    if len(pts) < 2:
        continue
    for r, x, y in pts:
        refs.append(r); lons.append(x); lats.append(y)
    way_id.append(o.id); way_hw.append(hw); way_start.append(len(refs))
print("ways kept:", len(way_id), "| node refs:", len(refs), "| %.0fs" % (time.time() - t0), flush=True)

refs = np.frombuffer(refs, dtype=np.int64)
lons = np.frombuffer(lons, dtype=np.float64)
lats = np.frombuffer(lats, dtype=np.float64)
uniq, inv, cnt = np.unique(refs, return_inverse=True, return_counts=True)
shared = cnt[inv] > 1                      # node used more than once among highway ways
print("shared nodes computed | %.0fs" % (time.time() - t0), flush=True)

geoms, rows = [], []
seg = 0
for k in range(len(way_id)):
    a, b = way_start[k], way_start[k + 1]
    cut = np.flatnonzero(shared[a:b])
    cut = np.unique(np.concatenate(([0], cut, [b - a - 1])))
    for i in range(len(cut) - 1):
        s, e = a + cut[i], a + cut[i + 1]
        if e - s < 1:
            continue
        xy = np.column_stack((lons[s:e + 1], lats[s:e + 1]))
        geoms.append(xy)
        rows.append((seg, way_id[k], way_hw[k]))
        seg += 1
print("segments:", seg, "| %.0fs" % (time.time() - t0), flush=True)

lines = [shapely.LineString(g) for g in geoms]
gdf = gpd.GeoDataFrame(rows, columns=["seg_id", "way_id", "highway"], geometry=lines, crs="EPSG:4326").to_crs(27700)
gdf["length_m"] = gdf.geometry.length.round(2)
gdf = gdf[gdf.length_m > 0]
import shutil, tempfile
tmp = os.path.join(tempfile.gettempdir(), "segments_london.gpkg")
if os.path.exists(tmp):
    os.remove(tmp)
gdf.to_file(tmp, driver="GPKG")      # write locally first: SQLite cannot write directly on some mounted folders
shutil.copy(tmp, OUT)
print("saved", OUT, len(gdf), "segments | %.0fs" % (time.time() - t0))
print(gdf.highway.value_counts().head(12).to_string())
print(gdf.length_m.describe().round(1).to_string())
