#!/usr/bin/env python3
"""Chatty Maps London: change between two periods, with a split half noise baseline.
Usage: python change_analysis.py
Inputs: sound_<label>_segments.csv.gz from build_sound_map.py (A=2005_2015, B=2016_2026, noise = odd/even halves of A)
"""
import os, json, tempfile, shutil, sys
import numpy as np, pandas as pd, geopandas as gpd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pyproj import Transformer

HERE = os.path.dirname(os.path.abspath(__file__))
MAPS = os.path.join(os.path.dirname(HERE), "maps")
TABLES = os.path.join(os.path.dirname(HERE), "tables")
CATS = ["transport", "nature", "human", "music", "indoor", "mechanical"]
COL = {"transport": "#d62728", "nature": "#2ca02c", "human": "#3f7fbf", "music": "#f2a229",
       "indoor": "#1a1a1a", "mechanical": "#9467bd"}
MIN = 5
TAG = sys.argv[1] if len(sys.argv) > 1 else ""   # e.g. _pf: use sound_<period><TAG>_segments.csv.gz and write *_<TAG> outputs
rng = np.random.default_rng(42)

def load(lbl):
    d = pd.read_csv(os.path.join(HERE, "sound_%s_segments.csv.gz" % lbl))
    return d[d.n_tags >= MIN].set_index("seg_id")

A, B = load("2005_2015" + TAG), load("2016_2026" + TAG)
Ao, Ae = load("2005_2015" + TAG + "odd"), load("2005_2015" + TAG + "even")

def compare(X, Y):
    ids = X.index.intersection(Y.index)
    x, y = X.loc[ids], Y.loc[ids]
    flip = (x.dominant != y.dominant)
    return ids, x, y, flip

ids, a, b, flip = compare(A, B)
_, ao, ae, flip_noise = compare(Ao, Ae)
res = {"mapped_A": len(A), "mapped_B": len(B), "common_AB": len(ids),
       "flip_rate_AB": float(flip.mean()),
       "common_noise_halves": int(len(flip_noise)), "flip_rate_noise_halves": float(flip_noise.mean())}

# transition matrix (row = A dominant, column = B dominant), row normalised
T = pd.crosstab(a.dominant, b.dominant).reindex(index=CATS, columns=CATS, fill_value=0)
T.to_csv(os.path.join(TABLES, "change_transition_counts%s.csv" % TAG))
(T.div(T.sum(1), axis=0).round(3)).to_csv(os.path.join(TABLES, "change_transition_rowshare%s.csv" % TAG))
Tn = pd.crosstab(ao.dominant, ae.dominant).reindex(index=CATS, columns=CATS, fill_value=0)

# city wide tag shares (segment level counts, all segments with >=1 tag) per period and mean fraction change on common segments
rows = []
for c in CATS:
    d = (b["f_" + c] - a["f_" + c]).values
    boot = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(300)]
    dn = (ae["f_" + c] - ao["f_" + c]).values
    rows.append({"category": c,
                 "dominant_share_A": float((A.dominant == c).mean()), "dominant_share_B": float((B.dominant == c).mean()),
                 "mean_fraction_A_common": float(a["f_" + c].mean()), "mean_fraction_B_common": float(b["f_" + c].mean()),
                 "mean_change": float(d.mean()), "ci_lo": float(np.percentile(boot, 2.5)), "ci_hi": float(np.percentile(boot, 97.5)),
                 "noise_mean_change_halves": float(dn.mean())})
S = pd.DataFrame(rows).round(4)
S.to_csv(os.path.join(TABLES, "change_category_summary%s.csv" % TAG), index=False)
json.dump(res, open(os.path.join(TABLES, "change_summary%s.json" % TAG), "w"), indent=2)
print(json.dumps(res, indent=2)); print(S.to_string(index=False)); print("transitions (counts):"); print(T.to_string())
print("transition row share:"); print(T.div(T.sum(1), axis=0).round(2).to_string())
print("noise halves flip rate by A-half dominant:"); print((Tn.div(Tn.sum(1), axis=0).round(2)).to_string())

# ---- maps
seg_tmp = os.path.join(tempfile.gettempdir(), "segments_snapshot.gpkg")
if not os.path.exists(seg_tmp):
    shutil.copy(os.path.join(HERE, "segments_london.gpkg"), seg_tmp)
segs = gpd.read_file(seg_tmp, engine="pyogrio")[["seg_id", "geometry"]].set_index("seg_id")
tf = Transformer.from_crs(4326, 27700, always_xy=True)
x0, y0 = tf.transform(-0.225, 51.452); x1, y1 = tf.transform(0.015, 51.548)

def style(ax):
    ax.set_xlim(x0, x1); ax.set_ylim(y0, y1); ax.set_aspect("equal"); ax.axis("off")

def draw(ax, D, title):
    g = segs.loc[segs.index.intersection(D.index)].copy()
    g["dominant"] = D.loc[g.index, "dominant"].values
    for c in CATS:
        gg = g[g.dominant == c]
        if len(gg): gg.plot(ax=ax, color=COL[c], linewidth=0.7)
    style(ax); ax.set_title(title, fontsize=13)

fig, axs = plt.subplots(1, 2, figsize=(22, 9.5))
draw(axs[0], A, "2005 to 2015 (%d segments)" % len(A)); draw(axs[1], B, "2016 to 2026 (%d segments)" % len(B))
from matplotlib.lines import Line2D
fig.legend([Line2D([0], [0], color=COL[c], lw=4) for c in CATS], CATS, loc="lower center", ncol=6, frameon=False, fontsize=13)
fig.subplots_adjust(bottom=0.07, wspace=0.02, left=0.01, right=0.99, top=0.95)
fig.savefig(os.path.join(MAPS, "drafts", "sound_london_side_by_side_2005_2015_vs_2016_2026%s.png" % TAG), dpi=130); plt.close(fig)

# change map: common segments; grey if unchanged, coloured by NEW dominant category if changed
g = segs.loc[ids].copy(); g["new"] = b.dominant.values; g["flip"] = flip.values
fig, ax = plt.subplots(figsize=(14, 9.8))
g[~g.flip].plot(ax=ax, color="#d0d0d0", linewidth=0.5)
for c in CATS:
    gg = g[g.flip & (g.new == c)]
    if len(gg): gg.plot(ax=ax, color=COL[c], linewidth=1.0)
style(ax)
ax.set_title("Segments mapped in both periods: grey = same dominant sound, colour = new dominant sound in 2016 to 2026\n(%d common segments, %.0f%% changed; noise baseline %.0f%%)"
             % (len(ids), 100 * flip.mean(), 100 * flip_noise.mean()), fontsize=12)
ax.legend([Line2D([0], [0], color="#d0d0d0", lw=4)] + [Line2D([0], [0], color=COL[c], lw=4) for c in CATS],
          ["unchanged"] + ["now " + c for c in CATS], loc="lower right", fontsize=10, frameon=True)
fig.savefig(os.path.join(MAPS, "drafts", "sound_london_change_map_2005_2015_to_2016_2026%s.png" % TAG), dpi=130, bbox_inches="tight"); plt.close(fig)
print("maps saved")
