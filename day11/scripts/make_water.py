#!/usr/bin/env python3
"""Extract water polygons (Thames, docks, lakes) from the London OSM extract for map backgrounds."""
import os, tempfile, shutil, time
import osmium, shapely.wkb, geopandas as gpd
HERE = os.path.dirname(os.path.abspath(__file__))
t0 = time.time()
fab = osmium.geom.WKBFactory()
rows = []
fp = osmium.FileProcessor(os.path.join(HERE, "london.osm.pbf")).with_areas()
for o in fp:
    if o.is_area():
        t = o.tags
        if t.get("natural") == "water" or t.get("waterway") == "riverbank" or t.get("landuse") == "reservoir":
            try:
                rows.append((t.get("name", ""), shapely.wkb.loads(fab.create_multipolygon(o), hex=True)))
            except Exception:
                pass
print("water areas:", len(rows), "%.0fs" % (time.time() - t0), flush=True)
g = gpd.GeoDataFrame(rows, columns=["name", "geometry"], geometry="geometry", crs="EPSG:4326").to_crs(27700)
tmp = os.path.join(tempfile.gettempdir(), "water_london.gpkg")
g.to_file(tmp, driver="GPKG")
shutil.copy(tmp, os.path.join(HERE, "water_london.gpkg"))
print("saved", flush=True)
