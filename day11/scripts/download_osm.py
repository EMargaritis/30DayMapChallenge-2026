#!/usr/bin/env python3
"""
Chatty Maps London replication, step 2: download an OpenStreetMap extract for London.

Tries these sources in order and uses the first that exists:
  1. Geofabrik Greater London extract
  2. BBBike London extract
You can also pass your own address:  python download_osm.py --url https://.../something.osm.pbf

Saves london.osm.pbf and osm_download_meta.json (source, timestamp, size, SHA256)
in this folder, so the OSM snapshot date and source can be stated in the methods.
OpenStreetMap contributors, ODbL.
"""
import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

try:
    import requests
except ImportError:  # pragma: no cover
    sys.exit("The 'requests' package is missing. Run:  pip install requests")

HERE = Path(__file__).resolve().parent
URLS = [
    "https://download.geofabrik.de/europe/great-britain/england/greater-london-latest.osm.pbf",
    "https://download.bbbike.org/osm/bbbike/London/London.osm.pbf",
]
OUT = HERE / "london.osm.pbf"
HEADERS = {"User-Agent": "chatty-maps-london-replication/1.0 (academic research)"}


def pick_source(urls):
    for u in urls:
        try:
            r = requests.head(u, headers=HEADERS, allow_redirects=True, timeout=60)
        except requests.RequestException as e:
            print("  cannot reach %s (%s)" % (u, e.__class__.__name__))
            continue
        print("  %s -> HTTP %d" % (u, r.status_code))
        if r.status_code == 200:
            return u, int(r.headers.get("Content-Length", 0)), r.headers.get("Last-Modified", "unknown")
    return None, 0, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=None)
    a = ap.parse_args()
    url, total, last_modified = pick_source([a.url] if a.url else URLS)
    if not url:
        sys.exit("No source worked. Download a London .osm.pbf in your browser, save it here as london.osm.pbf and tell me where it came from.")
    print("Using", url)
    done = OUT.stat().st_size if OUT.exists() else 0
    if total and done == total:
        print("File already complete (%d bytes)." % total)
    else:
        headers = dict(HEADERS)
        if done and done < total:
            headers["Range"] = "bytes=%d-" % done
            print("Resuming at %d bytes" % done)
        with requests.get(url, headers=headers, stream=True, timeout=120) as r:
            r.raise_for_status()
            mode = "ab" if "Range" in headers and r.status_code == 206 else "wb"
            got = done if mode == "ab" else 0
            with open(OUT, mode) as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
                    got += len(chunk)
                    print("\r%.0f MB of %.0f MB" % (got / 1e6, total / 1e6), end="", flush=True)
        print()
    h = hashlib.sha256()
    with open(OUT, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    meta = {"url": url, "downloaded": dt.datetime.now().isoformat(timespec="seconds"),
            "server_last_modified": last_modified, "bytes": OUT.stat().st_size, "sha256": h.hexdigest()}
    (HERE / "osm_download_meta.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
