#!/usr/bin/env python3
"""
Chatty Maps London replication, step 4: sound profiles, z scores and map (paper Figure 6a).

Method (Aiello et al. 2016):
  * each Flickr photo tag that matches a dictionary term counts as one tag of that term's top level category
  * a photo is assigned to EVERY segment whose polyline lies within 22.5 m of the photo point
  * sound_{j,c} = tags_{j,c} / tags_j                      (eq. 3.1, tags_j = matched sound tags, assumption A-prof-1)
  * z_{j,c} = (sound_{j,c} - mean_c) / sd_c                 (eq. 3.2)
  * each segment is coloured by the category with the highest z score
  * only segments with at least MIN_TAGS sound tags are mapped (Figure 6 caption: 5)

Usage:  python build_sound_map.py --start 2005-01-01 --end 2015-12-31 --label 2005_2015
"""
import argparse, csv, os, sqlite3, sys, time, json, tempfile, shutil
import numpy as np, pandas as pd
import geopandas as gpd
import shapely
from shapely import STRtree
from pyproj import Transformer
from scipy import sparse
from scipy.stats import spearmanr

HERE = os.path.dirname(os.path.abspath(__file__))
CATS = ["transport", "nature", "human", "music", "indoor", "mechanical"]
COLOURS = {"transport": "#d62728", "nature": "#2ca02c", "human": "#3f7fbf", "music": "#f2a229",
           "indoor": "#1a1a1a", "mechanical": "#9467bd"}
BUFFER_M = 22.5

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.path.join(HERE, "flickr_london.sqlite"))
ap.add_argument("--start", default="2005-01-01")
ap.add_argument("--end", default="2015-12-31")
ap.add_argument("--label", default="2005_2015")
ap.add_argument("--min-tags", type=int, default=5)
ap.add_argument("--z-population", choices=["mapped", "all"], default="mapped",
                help="segments used for the z score mean and SD: those with >= min tags (default) or all with >= 1")
ap.add_argument("--dedup-users", action="store_true", help="sensitivity: count each user at most once per segment")
ap.add_argument("--no-plot", action="store_true")
ap.add_argument("--plural", action="store_true", help="sensitivity: also match tags that equal a dictionary term plus s or es")
ap.add_argument("--buffer-mode", choices=["polyline", "bbox"], default="polyline",
                help="polyline: photos within 22.5 m of the line (paper section 2.2); bbox: photos inside the segment bounding box plus 22.5 m (paper section 5)")
ap.add_argument("--types", choices=["all", "paper8"], default="all",
                help="paper8: only the eight street types listed in the paper Table 1")
ap.add_argument("--cc-only", action="store_true", help="sensitivity: Creative Commons licensed photos only (Flickr licence ids 1-6, 9, 10)")
ap.add_argument("--half", choices=["all", "odd", "even"], default="all",
                help="noise baseline: use only photos whose id is odd or even")
a = ap.parse_args()
t0 = time.time()
def log(m): print("[%4.0fs] %s" % (time.time() - t0, m), flush=True)

# ---- dictionary: English terms -> category index
term2cat = {}
import re
with open(os.path.join(HERE, "dictionary_clean.csv"), encoding="utf-8") as f:
    for r in csv.DictReader(f):
        if r["language"] == "en":
            t = re.sub(r"[^\w]", "", r["term"].lower()).replace("_", "")
            term2cat[t] = int(r["code"][0]) - 1
log("dictionary: %d English terms" % len(term2cat))

# ---- photos
tmpdb = os.path.join(tempfile.gettempdir(), "photos_snapshot.sqlite")
shutil.copy(a.db, tmpdb)
db = sqlite3.connect(tmpdb)
ph = pd.read_sql_query(
    "SELECT id, owner, lat, lon, accuracy, datetaken, license, tags FROM photos "
    "WHERE datetaken >= ? AND datetaken <= ?", db, params=(a.start + " 00:00:00", a.end + " 23:59:59"))
if a.cc_only:
    ph = ph[ph["license"].astype(str).isin(["1","2","3","4","5","6","9","10"])].reset_index(drop=True)
if a.half != "all":
    par = ph["id"].astype("int64") % 2
    ph = ph[par == (1 if a.half == "odd" else 0)].reset_index(drop=True)
log("photos in period %s to %s: %d" % (a.start, a.end, len(ph)))
P = np.zeros((len(ph), len(CATS)), dtype=np.int32)
for i, tg in enumerate(ph["tags"].fillna("").values):
    for w in tg.split():
        c = term2cat.get(w)
        if c is None and a.plural:
            if w.endswith("s"):
                c = term2cat.get(w[:-1])
            if c is None and w.endswith("es"):
                c = term2cat.get(w[:-2])
        if c is not None:
            P[i, c] += 1
keep = P.sum(1) > 0
ph, P = ph[keep].reset_index(drop=True), P[keep]
log("photos with at least one dictionary tag: %d | matched tags (photo level): %d" % (len(ph), P.sum()))
tf = Transformer.from_crs(4326, 27700, always_xy=True)
x, y = tf.transform(ph["lon"].values, ph["lat"].values)
pts = shapely.points(x, y)

# ---- segments
segpath = os.path.join(HERE, "segments_london.gpkg")
tmpseg = os.path.join(tempfile.gettempdir(), "segments_snapshot.gpkg")
if not os.path.exists(tmpseg):
    shutil.copy(segpath, tmpseg)
segs = gpd.read_file(tmpseg, engine="pyogrio")
if a.types == "paper8":
    segs = segs[segs["highway"].isin(["footway", "residential", "pedestrian", "track", "primary", "secondary", "tertiary", "construction"])].reset_index(drop=True)
log("segments: %d" % len(segs))
if a.buffer_mode == "bbox":
    bb = shapely.bounds(segs.geometry.values)
    tree = STRtree(shapely.box(bb[:, 0] - BUFFER_M, bb[:, 1] - BUFFER_M, bb[:, 2] + BUFFER_M, bb[:, 3] + BUFFER_M))
else:
    tree = STRtree(segs.geometry.values)

# ---- assign photos to segments (every segment within 22.5 m), accumulate category counts
n_seg = len(segs)
counts = np.zeros((n_seg, len(CATS)), dtype=np.int64)
n_assign = 0
owners = ph["owner"].values
seen = set()
CH = 50000
for s in range(0, len(pts), CH):
    e = min(len(pts), s + CH)
    if a.buffer_mode == "bbox":
        qi, ti = tree.query(pts[s:e], predicate="intersects")
    else:
        qi, ti = tree.query(pts[s:e], predicate="dwithin", distance=BUFFER_M)
    qi = qi + s
    if a.dedup_users:
        keepmask = np.zeros(len(qi), dtype=bool)
        for k, (pi, si) in enumerate(zip(qi, ti)):
            key = (owners[pi], si)
            if key not in seen:
                seen.add(key); keepmask[k] = True
        qi, ti = qi[keepmask], ti[keepmask]
    A = sparse.csr_matrix((np.ones(len(qi), dtype=np.int32), (ti, qi)), shape=(n_seg, len(pts)))
    counts += (A @ P).astype(np.int64)
    n_assign += len(qi)
    log("assigned photos %d / %d" % (e, len(pts)))

tot = counts.sum(1)
segs[CATS] = counts
segs["n_tags"] = tot
has = tot > 0
log("segments with >=1 sound tag: %d | segment level tag total: %d | mean tags per such segment: %.1f"
    % (has.sum(), tot.sum(), tot[has].mean() if has.any() else 0))
mapped = tot >= a.min_tags
log("segments with >= %d sound tags (mapped): %d" % (a.min_tags, mapped.sum()))

# ---- profile and z scores
frac = np.zeros_like(counts, dtype=float)
frac[has] = counts[has] / tot[has][:, None]
pop = mapped if a.z_population == "mapped" else has
mu, sd = frac[pop].mean(0), frac[pop].std(0)
sd[sd == 0] = 1
z = (frac - mu) / sd
dom = np.array(CATS)[np.argmax(z, axis=1)]
segs["dominant"] = np.where(has, dom, "")
for k, c in enumerate(CATS):
    segs["z_" + c] = z[:, k]
    segs["f_" + c] = frac[:, k]
share = pd.Series(dom[mapped]).value_counts(normalize=True).round(3)
log("share of mapped segments by dominant category:\n" + share.to_string())

# ---- Figure 5 check: pairwise Spearman between category fractions
for label, m in (("segments with >=1 tag", has), ("mapped segments", mapped)):
    if m.sum() > 100:
        rho = spearmanr(frac[m]).statistic
        print("Spearman rho between category fractions, %s:" % label)
        print(pd.DataFrame(rho, index=CATS, columns=CATS).round(2).to_string(), flush=True)

# ---- save outputs
out = segs[has].copy()
base = os.path.join(HERE, "sound_%s" % a.label)
out.drop(columns="geometry").to_csv(base + "_segments.csv.gz", index=False)
meta = dict(vars(a)); meta.update(photos_used=int(len(ph)), segments_with_tags=int(has.sum()), mapped=int(mapped.sum()),
                                  mean_tags_per_segment=float(tot[has].mean()), assignments=int(n_assign))
json.dump(meta, open(base + "_meta.json", "w"), indent=2)

if not a.no_plot:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    m = segs[mapped].copy()
    tf2 = Transformer.from_crs(4326, 27700, always_xy=True)
    bx0, by0 = tf2.transform(-0.225, 51.452); bx1, by1 = tf2.transform(0.015, 51.548)
    view = m.cx[bx0:bx1, by0:by1]
    fig, ax = plt.subplots(figsize=(14, 8.4), dpi=170)
    for c in CATS:
        sub = view[view.dominant == c]
        if len(sub):
            sub.plot(ax=ax, color=COLOURS[c], linewidth=0.55)
    ax.set_xlim(bx0, bx1); ax.set_ylim(by0, by1); ax.set_aspect("equal"); ax.axis("off")
    ax.legend(handles=[Line2D([0], [0], color=COLOURS[c], lw=3, label=c) for c in CATS], loc="lower right", frameon=True)
    fig.savefig(base + "_central_draft.png", bbox_inches="tight", facecolor="white")
    log("saved " + base + "_central_draft.png")
log("done")
