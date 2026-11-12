#!/usr/bin/env python3
"""Compact data for the interactive Chatty Maps change map (central window)."""
import os, json, gzip, base64, struct
import numpy as np, pandas as pd, geopandas as gpd, shapely
from pyproj import Transformer
HERE = os.path.dirname(os.path.abspath(__file__))
CATS = ["transport", "nature", "human", "music", "indoor", "mechanical"]
P8 = ["footway", "residential", "pedestrian", "track", "primary", "secondary", "tertiary", "construction"]
tf = Transformer.from_crs(4326, 27700, always_xy=True)
wx0, wy0 = tf.transform(-0.225, 51.452); wx1, wy1 = tf.transform(0.015, 51.548)
M = 100.0; ox, oy = wx0 - M, wy0 - M; S = 2.0
W, H = int((wx1 - wx0 + 2 * M) * S), int((wy1 - wy0 + 2 * M) * S)
seg = gpd.read_file("/tmp/segments_snapshot.gpkg", engine="pyogrio")
seg = seg[seg.highway.isin(P8)].cx[wx0:wx1, wy0:wy1].reset_index(drop=True)
N = len(seg)
A = pd.read_csv(os.path.join(HERE, "sound_2005_2015_pf_segments.csv.gz")).set_index("seg_id")
B = pd.read_csv(os.path.join(HERE, "sound_2016_2026_pf_segments.csv.gz")).set_index("seg_id")
def counts(D):
    c = D.reindex(seg.seg_id)[CATS].fillna(0).astype(np.uint16).values
    dom = D.reindex(seg.seg_id)
    d = np.full(N, 255, np.uint8)
    ok = (dom.n_tags.fillna(0).values >= 5)
    d[ok] = [CATS.index(x) for x in dom.dominant.values[ok]]
    return c, d
cA, dA = counts(A); cB, dB = counts(B)
off = np.zeros(N + 1, np.uint32); xy = []
for i, g in enumerate(seg.geometry.values):
    c = np.asarray(g.coords)
    q = np.clip(np.round((c - [ox, oy]) * S), 0, 65535).astype(np.uint16)
    xy.append(q.ravel()); off[i + 1] = off[i] + len(c)
xy = np.concatenate(xy)
typ = np.array([P8.index(h) for h in seg.highway], np.uint8)
ln = np.clip(np.round(seg.length_m.values), 0, 65535).astype(np.uint16)
arrs = [("off", off), ("xy", xy), ("typ", typ), ("len", ln), ("cA", cA.ravel()), ("cB", cB.ravel()), ("dA", dA), ("dB", dB)]
blob = bytearray(); layout = []
for name, a in arrs:
    while len(blob) % 4: blob.append(0)
    layout.append({"name": name, "dtype": str(a.dtype), "offset": len(blob), "length": int(a.size)})
    blob += a.tobytes()
gz = gzip.compress(bytes(blob), 9)
open(os.path.join(HERE, "interactive_blob.b64"), "w").write(base64.b64encode(gz).decode())
water = gpd.read_file(os.path.join(HERE, "water_london.gpkg"))
box = shapely.box(ox, oy, ox + W / S, oy + H / S)
polys = []
for g in water.geometry:
    g = g.intersection(box)
    if g.is_empty: continue
    g = g.simplify(3.0)
    for p in (g.geoms if hasattr(g, "geoms") else [g]):
        if p.geom_type != "Polygon" or p.is_empty: continue
        rings = [p.exterior] + list(p.interiors)
        polys.append([np.round((np.asarray(r.coords) - [ox, oy]) * S).astype(int).ravel().tolist() for r in rings])
meta = {"S": S, "W": W, "H": H, "N": N, "P": int(len(xy) // 2), "types": P8, "cats": CATS, "layout": layout, "water": polys,
        "nA": int((dA != 255).sum()), "nB": int((dB != 255).sum()), "common": int(((dA != 255) & (dB != 255)).sum())}
json.dump(meta, open(os.path.join(HERE, "interactive_meta.json"), "w"), separators=(",", ":"))
print("segments", N, "points", meta["P"], "raw MB", len(blob) / 1e6, "gz MB", len(gz) / 1e6, "b64 MB", len(gz) * 4 / 3e6)
print("meta KB", os.path.getsize(os.path.join(HERE, "interactive_meta.json")) / 1e3, "water polys", len(polys))
print({k: meta[k] for k in ("nA", "nB", "common")})
