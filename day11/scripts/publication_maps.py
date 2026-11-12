#!/usr/bin/env python3
"""Chatty Maps London: publication styled maps. Writes PNGs to ../maps"""
import os, tempfile, shutil
import numpy as np, pandas as pd, geopandas as gpd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from pyproj import Transformer

HERE = os.path.dirname(os.path.abspath(__file__))
MAPS = os.path.join(os.path.dirname(HERE), "maps")
CATS = ["transport", "nature", "human", "music", "indoor", "mechanical"]
COL = {"transport": "#d62728", "nature": "#2ca02c", "human": "#3f7fbf", "music": "#f2a229", "indoor": "#1a1a1a", "mechanical": "#9467bd"}
BG, WATER = "#fbfaf7", "#cfe3ee"
FOOT = ("Data: Flickr API photos geotagged in Greater London, tags matched to the Freesound derived sound dictionary of Aiello et al. (2016); "
        "street network © OpenStreetMap contributors (7 Nov 2026).\nMethod after Aiello, Schifanella, Quercia and Aletta (2016) Chatty Maps, R. Soc. open sci. 3:150690.\n"
        "Photos within segment bounding box plus 22.5 m; street types of paper Table 1; at least 5 sound tags; colour = highest z score; pale grey = fewer than 5 tags. #30DayMapChallenge Day 11: Sound")

def load(lbl):
    d = pd.read_csv(os.path.join(HERE, "sound_%s_segments.csv.gz" % lbl))
    return d[d.n_tags >= 5].set_index("seg_id")

tmp = os.path.join(tempfile.gettempdir(), "segments_snapshot.gpkg")
if not os.path.exists(tmp): shutil.copy(os.path.join(HERE, "segments_london.gpkg"), tmp)
segs = gpd.read_file(tmp, engine="pyogrio")[["seg_id", "highway", "geometry"]].set_index("seg_id")
water = gpd.read_file(os.path.join(HERE, "water_london.gpkg"))
tf = Transformer.from_crs(4326, 27700, always_xy=True)
x0, y0 = tf.transform(-0.225, 51.452); x1, y1 = tf.transform(0.015, 51.548)
water = water.cx[x0:x1, y0:y1]
segs = segs.cx[x0:x1, y0:y1]
PAPER8 = ["footway", "residential", "pedestrian", "track", "primary", "secondary", "tertiary", "construction"]
segs = segs[segs.highway.isin(PAPER8)]
PALE = "#dcd9d1"

def base(ax):
    ax.set_facecolor(BG)
    water.plot(ax=ax, color=WATER, linewidth=0)
    ax.set_xlim(x0, x1); ax.set_ylim(y0, y1); ax.set_aspect("equal"); ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values(): s.set_visible(False)

def draw(ax, D, lw=1.3):
    base(ax)
    segs.plot(ax=ax, color=PALE, linewidth=0.5)
    g = segs.loc[segs.index.intersection(D.index)].copy()
    g["dominant"] = D.loc[g.index, "dominant"].values
    for c in CATS:
        gg = g[g.dominant == c]
        if len(gg): gg.plot(ax=ax, color=COL[c], linewidth=lw)
    return len(g)

def legend(fig, y=0.075):
    fig.legend([Line2D([0], [0], color=COL[c], lw=5) for c in CATS], [c.capitalize() for c in CATS],
               loc="lower center", bbox_to_anchor=(0.5, y), ncol=6, frameon=False, fontsize=12)

def single(D, title, sub, fn):
    fig = plt.figure(figsize=(14, 10.4), facecolor=BG)
    ax = fig.add_axes([0.01, 0.17, 0.98, 0.72])
    n = draw(ax, D)
    fig.text(0.02, 0.955, title, fontsize=22, fontweight="bold", va="top")
    fig.text(0.02, 0.915, sub.format(n=n, nA=len(A), nB=len(B)), fontsize=13, va="top", color="#444")
    legend(fig, 0.11)
    fig.text(0.02, 0.045, FOOT, fontsize=8, va="top", color="#555")
    fig.savefig(os.path.join(MAPS, fn), dpi=200, facecolor=BG); plt.close(fig)
    return n

import sys
TAG = sys.argv[1] if len(sys.argv) > 1 else ""
A, B = load("2005_2015" + TAG), load("2016_2026" + TAG)
single(A, "Dominant sound by street, central London, 2005 to 2015", "Replication of Chatty Maps with 2026 data: {n} street segments in view ({nA:,} across London), 145,127 photos", "sound_london_2005_2015_publication%s.png" % TAG)
single(B, "Dominant sound by street, central London, 2016 to 2026", "Same method, later decade: {n} street segments in view ({nB:,} across London), 106,740 photos", "sound_london_2016_2026_publication%s.png" % TAG)

fig = plt.figure(figsize=(22, 10.6), facecolor=BG)
for i, (D, t) in enumerate(((A, "2005 to 2015"), (B, "2016 to 2026"))):
    ax = fig.add_axes([0.005 + i * 0.5, 0.17, 0.49, 0.70]); n = draw(ax, D, 1.1)
    ax.set_title("%s (%d segments in view)" % (t, n), fontsize=16, loc="left")
fig.text(0.01, 0.975, "How the sound of London streets changed: dominant sound by street segment", fontsize=24, fontweight="bold", va="top")
legend(fig, 0.105)
fig.text(0.01, 0.06, FOOT, fontsize=9, va="top", color="#555")
fig.savefig(os.path.join(MAPS, "sound_london_side_by_side_publication%s.png" % TAG), dpi=150, facecolor=BG); plt.close(fig)

ids = A.index.intersection(B.index); a, b = A.loc[ids], B.loc[ids]; flip = (a.dominant != b.dominant)
g = segs.loc[segs.index.intersection(ids)].copy()
g["new"] = b.loc[g.index, "dominant"].values; g["flip"] = flip.loc[g.index].values
fig = plt.figure(figsize=(14, 10.4), facecolor=BG); ax = fig.add_axes([0.01, 0.17, 0.98, 0.72]); base(ax)
segs.plot(ax=ax, color="#e8e5de", linewidth=0.5)
g[~g.flip].plot(ax=ax, color="#b3b3b3", linewidth=0.9)
for c in CATS:
    gg = g[g.flip & (g.new == c)]
    if len(gg): gg.plot(ax=ax, color=COL[c], linewidth=1.6)
fig.text(0.02, 0.955, "Where the dominant sound changed: 2005 to 2015 versus 2016 to 2026", fontsize=22, fontweight="bold", va="top")
fig.text(0.02, 0.915, "%d streets mapped in both periods: grey unchanged, colour = new dominant sound (%.0f%% changed; chance baseline 26%%)" % (len(ids), 100 * flip.mean()), fontsize=13, va="top", color="#444")
fig.legend([Line2D([0], [0], color="#b3b3b3", lw=5)] + [Line2D([0], [0], color=COL[c], lw=5) for c in CATS], ["Unchanged"] + ["Now " + c for c in CATS],
           loc="lower center", bbox_to_anchor=(0.5, 0.105), ncol=7, frameon=False, fontsize=11)
fig.text(0.02, 0.045, FOOT, fontsize=8, va="top", color="#555")
fig.savefig(os.path.join(MAPS, "sound_london_change_publication%s.png" % TAG), dpi=200, facecolor=BG); plt.close(fig)
print("done")
