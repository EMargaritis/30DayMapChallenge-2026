#!/usr/bin/env python3
"""
Chatty Maps London replication, step 1: Flickr pull.

Retrieves public, geotagged Flickr photos inside the Greater London bounding box
whose tags match the English sound dictionary (Aiello et al. 2016, Dryad
doi:10.5061/dryad.tg735), for photos taken from 2005-01-01 to today.

Design
------
* Query: flickr.photos.search, tag_mode=any over all dictionary terms.
* Flickr returns at most 4000 unique photos per query, so the search area and
  date range are split adaptively (quadtree in space, halving in time) until each
  tile returns 4000 results or fewer.
* Everything is stored in SQLite (flickr_london.sqlite) and the run is resumable:
  stop with Ctrl+C or by creating a file named STOP, then run the same command again.
* Request rate is capped at about 0.95 requests per second, below Flickr's
  documented guideline of 3600 per hour for a non commercial key.

Usage (Anaconda Prompt, in this folder)
-----
    python flickr_pull.py --test      # check the key and one small query
    python flickr_pull.py             # start or resume the full pull
    python flickr_pull.py --status    # show progress
"""
import argparse
import csv
import datetime as dt
import json
import os
import re
import sqlite3
import sys
import threading
import time
from pathlib import Path

try:
    import requests
except ImportError:  # pragma: no cover
    sys.exit("The 'requests' package is missing. Run:  pip install requests")

HERE = Path(__file__).resolve().parent
API = "https://api.flickr.com/services/rest/"
DB_PATH = HERE / "flickr_london.sqlite"
DICT_PATH = HERE / "dictionary_clean.csv"
KEY_PATH = HERE / "flickr_key.txt"
STOP_PATH = HERE / "STOP"

# Greater London bounding box (min lon, min lat, max lon, max lat), approximate.
BBOX = (-0.5103, 51.2868, 0.3340, 51.6919)
START = dt.datetime(2005, 1, 1)
PER_PAGE = 250
CAP = 4000                     # Flickr: at most 4000 unique results per query
MAX_PAGES = CAP // PER_PAGE
MIN_INTERVAL = 1.6             # seconds between requests (starting value; adapts upwards after HTTP 429)
MAX_INTERVAL = 8.0
COOL_BASE = 60                 # seconds of pause after the first HTTP 429; doubles on repeats
COOL_MAX = 1800
MIN_CELL_DEG = 0.0004          # about 30 m; smallest spatial tile
MIN_SPAN = dt.timedelta(hours=6)
FALLBACK_BATCH = 60


def normalise_tag(term):
    """Flickr normalises tags: lower case, spaces and punctuation removed."""
    return re.sub(r"[^\w]", "", term.lower(), flags=re.UNICODE).replace("_", "")


def load_terms():
    terms = []
    with open(DICT_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["language"] == "en":
                t = normalise_tag(row["term"])
                if t and t not in terms:
                    terms.append(t)
    return terms


def fmt(t):
    return t.strftime("%Y-%m-%d %H:%M:%S")


def parse(s):
    return dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")


class FlickrError(RuntimeError):
    def __init__(self, code, payload):
        super().__init__("Flickr error: %s" % (payload,))
        self.code = code
        self.payload = payload


class Flickr:
    def __init__(self, key):
        self.key = key
        self.local = threading.local()
        self.rl = threading.Lock()
        self.next_slot = 0.0
        self.requests = 0
        self.interval = MIN_INTERVAL
        self.cooldown_until = 0.0
        self.cool = COOL_BASE / 2.0
        self.last_429 = 0.0
        self.ok_streak = 0

    def _session(self):
        s = getattr(self.local, "s", None)
        if s is None:
            s = requests.Session()
            s.headers["User-Agent"] = "chatty-maps-london-replication/1.0 (academic research)"
            self.local.s = s
        return s

    def _throttle(self):
        """Global limit shared by all threads: one request slot every self.interval seconds,
        and no requests at all while a rate limit cool down is active."""
        with self.rl:
            now = time.time()
            slot = max(now, self.next_slot, self.cooldown_until)
            self.next_slot = slot + self.interval
            self.requests += 1
        while True:
            d = max(slot, self.cooldown_until) - time.time()
            if d <= 0:
                break
            time.sleep(min(d, 5.0))

    def _on_429(self, r):
        """Pause every thread, honour Retry-After if given, then resume more slowly."""
        with self.rl:
            now = time.time()
            if now - self.last_429 > 15:          # escalate once per burst of 429 responses
                self.cool = COOL_BASE if now - self.last_429 > 3600 else min(COOL_MAX, self.cool * 2)
                self.interval = min(MAX_INTERVAL, self.interval * 1.5)
                ra = r.headers.get("Retry-After", "")
                wait = float(ra) if ra.replace(".", "", 1).isdigit() else self.cool
                self.cooldown_until = max(self.cooldown_until, now + wait)
                self.last_429 = now
                print("  HTTP 429 rate limit: all workers pause for %.0f s; request interval is now %.1f s"
                      % (wait, self.interval), flush=True)
        self.ok_streak = 0

    def _on_ok(self):
        self.ok_streak += 1
        if self.ok_streak >= 300 and self.interval > MIN_INTERVAL:
            self.interval = max(MIN_INTERVAL, self.interval * 0.9)
            self.ok_streak = 0

    def call(self, params):
        params = dict(params, api_key=self.key, format="json", nojsoncallback=1)
        attempt = 0
        n429 = 0
        while attempt < 8:
            attempt += 1
            self._throttle()
            try:
                r = self._session().post(API, data=params, timeout=90)
            except requests.RequestException as e:
                print("  network error (%s); retry %d" % (e.__class__.__name__, attempt))
                time.sleep(min(300, 20 * attempt))
                continue
            if r.status_code == 429:
                n429 += 1
                attempt -= 1                      # rate limiting is not a failure of this request
                if n429 > 400:
                    raise RuntimeError("Flickr keeps returning HTTP 429; stop and try again later")
                self._on_429(r)
                continue
            if r.status_code in (500, 502, 503, 504):
                print("  HTTP %d; backing off" % r.status_code)
                time.sleep(min(600, 45 * attempt))
                continue
            if r.status_code != 200:
                raise RuntimeError("HTTP %d: %s" % (r.status_code, r.text[:200]))
            try:
                j = r.json()
            except ValueError:
                time.sleep(20 * attempt)
                continue
            if j.get("stat") == "ok":
                self._on_ok()
                return j
            code = j.get("code")
            if code in (100, 101, 102, 95, 96, 97, 98, 99):
                raise RuntimeError("Flickr rejected the key or request: %s" % j)
            if code in (0, 105, 106, 10):
                time.sleep(min(300, 30 * attempt))
                continue
            raise FlickrError(code, j)
        raise RuntimeError("Too many failed attempts")

    def search(self, tags, tile, page):
        x0, y0, x1, y1, t0, t1 = tile
        return self.call({
            "method": "flickr.photos.search",
            "tags": ",".join(tags),
            "tag_mode": "any",
            "bbox": "%.6f,%.6f,%.6f,%.6f" % (x0, y0, x1, y1),
            "has_geo": 1,
            "min_taken_date": fmt(t0),
            "max_taken_date": fmt(t1),
            "extras": "geo,tags,date_taken,license",
            "media": "photos",
            "sort": "date-taken-asc",
            "per_page": PER_PAGE,
            "page": page,
        })


SCHEMA = """
CREATE TABLE IF NOT EXISTS photos(
  id TEXT PRIMARY KEY, owner TEXT, lat REAL, lon REAL, accuracy INTEGER,
  datetaken TEXT, license TEXT, tags TEXT);
CREATE TABLE IF NOT EXISTS tiles(
  id INTEGER PRIMARY KEY AUTOINCREMENT, batch INTEGER,
  x0 REAL, y0 REAL, x1 REAL, y1 REAL, t0 TEXT, t1 TEXT,
  status TEXT, total INTEGER, fetched INTEGER);
CREATE INDEX IF NOT EXISTS tiles_status ON tiles(status, t0);
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
"""


class Puller:
    def __init__(self, client, db):
        self.c = client
        self.db = db
        self.batches = json.loads(self.meta("batches"))

    def meta(self, k, v=None):
        if v is None:
            row = self.db.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
            return row[0] if row else None
        self.db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (k, v))
        self.db.commit()

    def store(self, photos):
        rows = []
        for p in photos:
            try:
                rows.append((p["id"], p.get("owner"), float(p["latitude"]), float(p["longitude"]),
                             int(p.get("accuracy", 0) or 0), p.get("datetaken"),
                             str(p.get("license", "")), p.get("tags", "")))
            except (KeyError, ValueError):
                continue
        self.db.executemany("INSERT OR IGNORE INTO photos VALUES(?,?,?,?,?,?,?,?)", rows)

    def add_tiles(self, batch, boxes_times):
        self.db.executemany(
            "INSERT INTO tiles(batch,x0,y0,x1,y1,t0,t1,status) VALUES(?,?,?,?,?,?,?,'pending')",
            [(batch, *b, fmt(t0), fmt(t1)) for b, t0, t1 in boxes_times])

    @staticmethod
    def children(tile):
        x0, y0, x1, y1, t0, t1 = tile
        w = x1 - x0
        days = (t1 - t0).total_seconds() / 86400.0
        can_space = w > MIN_CELL_DEG
        can_time = (t1 - t0) > MIN_SPAN
        if not can_space and not can_time:
            return None
        if can_space and (not can_time or w / 0.0025 >= days / 30.0):
            xm, ym = (x0 + x1) / 2, (y0 + y1) / 2
            return [((a, b, c, d), t0, t1) for a, b, c, d in
                    [(x0, y0, xm, ym), (xm, y0, x1, ym), (x0, ym, xm, y1), (xm, ym, x1, y1)]]
        tm = (t0 + (t1 - t0) / 2).replace(microsecond=0)
        return [((x0, y0, x1, y1), t0, tm - dt.timedelta(seconds=1)),
                ((x0, y0, x1, y1), tm, t1)]

    def next_pending(self, claimed):
        q = "SELECT id,batch,x0,y0,x1,y1,t0,t1 FROM tiles WHERE status='pending'"
        if claimed:
            q += " AND id NOT IN (%s)" % ",".join(str(int(i)) for i in claimed)
        q += " ORDER BY t0, id LIMIT 1"
        return self.db.execute(q).fetchone()

    def fetch_tile(self, row):
        """Network only (runs in a worker thread); the database is written by the main thread."""
        tid, batch, x0, y0, x1, y1, s0, s1 = row
        tile = (x0, y0, x1, y1, parse(s0), parse(s1))
        tags = self.batches[batch]
        j = self.c.search(tags, tile, 1)
        ph = j["photos"]
        total = int(ph["total"])
        photos = list(ph["photo"])
        kids, status = None, "done"
        if total > CAP:
            kids = self.children(tile)
            status = "split" if kids else "truncated"
        if status in ("done", "truncated"):
            for page in range(2, min(int(ph["pages"]), MAX_PAGES) + 1):
                photos.extend(self.c.search(tags, tile, page)["photos"]["photo"])
        return {"tid": tid, "batch": batch, "total": total, "photos": photos, "status": status, "kids": kids}

    def apply(self, r):
        self.store(r["photos"])
        if r["kids"]:
            self.add_tiles(r["batch"], r["kids"])
        self.db.execute("UPDATE tiles SET status=?, total=?, fetched=? WHERE id=?",
                        (r["status"], r["total"], len(r["photos"]), r["tid"]))
        self.db.commit()

    def run(self, workers=4):
        from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
        start = time.time()
        n0 = self.c.requests
        done = 0
        inflight = {}
        with ThreadPoolExecutor(max_workers=workers) as ex:
            while True:
                stopping = STOP_PATH.exists()
                while not stopping and len(inflight) < workers:
                    row = self.next_pending(set(inflight.values()))
                    if row is None:
                        break
                    inflight[ex.submit(self.fetch_tile, row)] = row[0]
                if not inflight:
                    print("STOP file found; stopped cleanly. Delete it to resume later." if stopping
                          else "All tiles complete.")
                    break
                finished, _ = wait(list(inflight), timeout=30, return_when=FIRST_COMPLETED)
                for f in finished:
                    inflight.pop(f)
                    self.apply(f.result())
                    done += 1
                    if done % 20 == 0:
                        self.report(start, n0)
        self.report(start, n0)

    def report(self, start, n0):
        pend = self.db.execute("SELECT COUNT(*) FROM tiles WHERE status='pending'").fetchone()[0]
        photos = self.db.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
        trunc = self.db.execute("SELECT COUNT(*) FROM tiles WHERE status='truncated'").fetchone()[0]
        el = max(1, time.time() - start)
        cur = self.db.execute("SELECT t0 FROM tiles WHERE status='pending' ORDER BY t0 LIMIT 1").fetchone()
        print("[%s] requests this session %d (%.2f/s) | photos %d | pending tiles %d | truncated %d | working on date %s"
              % (time.strftime("%H:%M:%S"), self.c.requests - n0, (self.c.requests - n0) / el,
                 photos, pend, trunc, cur[0][:10] if cur else "-"))


def open_db():
    db = sqlite3.connect(str(DB_PATH), timeout=60)
    db.executescript(SCHEMA)
    return db


def read_key():
    key = os.environ.get("FLICKR_API_KEY") or (KEY_PATH.read_text().strip() if KEY_PATH.exists() else "")
    if not re.fullmatch(r"[0-9a-f]{32}", key):
        sys.exit("No valid 32 character API key found in flickr_key.txt")
    return key


def cmd_test(client, terms):
    print("Dictionary: %d English terms after normalisation" % len(terms))
    j = client.call({"method": "flickr.test.echo"})
    print("Key accepted:", j.get("stat"))
    n = tag_limit(client, terms)
    print("Maximum tags per query accepted by Flickr: %d (batches needed: %d)" % (n, -(-len(terms) // n)))
    x0, y0, x1, y1 = BBOX
    bb = "%.6f,%.6f,%.6f,%.6f" % (x0, y0, x1, y1)

    def total(label, **kw):
        params = {"method": "flickr.photos.search", "per_page": 1, "page": 1, "media": "photos"}
        params.update(kw)
        try:
            j = client.call(params)
            print("  %-62s total = %s" % (label, j["photos"]["total"]))
        except RuntimeError as e:
            print("  %-62s ERROR %s" % (label, e))
    print("Diagnostics (totals):")
    total("street, London bbox, has_geo, taken 2010 (dates as text)", tags="street", bbox=bb, has_geo=1,
          min_taken_date="2010-01-01 00:00:00", max_taken_date="2010-12-31 23:59:59")
    total("street, London bbox, has_geo, taken 2010 (unix timestamps)", tags="street", bbox=bb, has_geo=1,
          min_taken_date=1262304000, max_taken_date=1293839999)
    total("street, London bbox, has_geo, no dates", tags="street", bbox=bb, has_geo=1)
    total("birdsong, London bbox, has_geo, taken 2010", tags="birdsong", bbox=bb, has_geo=1,
          min_taken_date="2010-01-01 00:00:00", max_taken_date="2010-12-31 23:59:59")
    total("birdsong, London bbox, has_geo, no dates", tags="birdsong", bbox=bb, has_geo=1)
    total("birdsong, worldwide, no bbox, no dates", tags="birdsong")
    total("bird,birdsong,birds (any), London bbox, no dates", tags="bird,birdsong,birds", tag_mode="any", bbox=bb, has_geo=1)
    print("Test finished. Please paste all of the output above.")


def tag_limit(client, terms):
    """Largest number of tags Flickr accepts in one tag_mode=any query (found by binary search)."""
    probe = (BBOX[0], BBOX[1], BBOX[0] + 0.05, BBOX[1] + 0.05, dt.datetime(2010, 1, 1), dt.datetime(2010, 1, 31))

    def ok(n):
        try:
            client.search(terms[:n], probe, 1)
            return True
        except FlickrError as e:
            if e.code == 1:
                return False
            raise
    if ok(len(terms)):
        return len(terms)
    lo, hi = 1, len(terms)          # lo accepted, hi rejected
    if not ok(1):
        raise RuntimeError("Flickr rejected even a single tag query")
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if ok(mid):
            lo = mid
        else:
            hi = mid
    return lo


def init_run(client, db, terms, end, batch_size):
    if db.execute("SELECT v FROM meta WHERE k='batches'").fetchone():
        return
    n = batch_size or tag_limit(client, terms)
    print("Flickr accepts up to %d tags per query; using %d batch(es)." % (n, -(-len(terms) // n)))
    batches = [terms[i:i + n] for i in range(0, len(terms), n)]
    p = Puller.__new__(Puller)
    p.c, p.db = client, db
    db.execute("INSERT OR REPLACE INTO meta VALUES('batches',?)", (json.dumps(batches),))
    for b in range(len(batches)):
        windows = []
        y = START.year
        while dt.datetime(y, 1, 1) <= end:
            t0 = dt.datetime(y, 1, 1)
            t1 = min(dt.datetime(y, 12, 31, 23, 59, 59), end)
            windows.append((BBOX, t0, t1))
            y += 1
        p.add_tiles(b, windows)
    meta = {"started": dt.datetime.now().isoformat(timespec="seconds"), "bbox": BBOX,
            "start": fmt(START), "end": fmt(end), "n_terms": len(terms), "n_batches": len(batches),
            "tag_limit": n, "terms": terms, "per_page": PER_PAGE, "cap": CAP, "min_interval_s": MIN_INTERVAL,
            "extras": "geo,tags,date_taken,license", "tag_mode": "any", "media": "photos",
            "note": "Unauthenticated calls return safe content only (Flickr documentation)."}
    for k, v in meta.items():
        db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (k, json.dumps(v)))
    db.commit()


def cmd_status(db):
    for st, n, tot in db.execute("SELECT status, COUNT(*), COALESCE(SUM(fetched),0) FROM tiles GROUP BY status"):
        print("tiles %-10s %6d  (photos retrieved in them: %d)" % (st, n, tot))
    print("unique photos stored:", db.execute("SELECT COUNT(*) FROM photos").fetchone()[0])
    print("photos by year:")
    for y, n in db.execute("SELECT substr(datetaken,1,4), COUNT(*) FROM photos GROUP BY 1 ORDER BY 1"):
        print("  ", y, n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--batch-size", type=int, default=0, help="split dictionary into batches of N terms (default: one query)")
    ap.add_argument("--workers", type=int, default=3, help="parallel requests (default 3; global rate still capped)")
    ap.add_argument("--interval", type=float, default=None, help="seconds between requests (default %.1f; adapts upwards after HTTP 429)" % MIN_INTERVAL)
    ap.add_argument("--end", default=None, help="end date YYYY-MM-DD (default: today)")
    a = ap.parse_args()
    if a.interval:
        globals()["MIN_INTERVAL"] = a.interval
    db = open_db()
    if a.status:
        return cmd_status(db)
    terms = load_terms()
    client = Flickr(read_key())
    if a.test:
        return cmd_test(client, terms)
    end = dt.datetime.strptime(a.end, "%Y-%m-%d").replace(hour=23, minute=59, second=59) if a.end \
        else dt.datetime.now().replace(microsecond=0)
    init_run(client, db, terms, end, a.batch_size)
    puller = Puller(client, db)
    try:
        puller.run(workers=max(1, a.workers))
    except KeyboardInterrupt:
        db.rollback()
        print("\nInterrupted; progress is saved. Run the same command to resume.")
        os._exit(0)


if __name__ == "__main__":
    main()
