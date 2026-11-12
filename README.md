# 30DayMapChallenge 2026

Maps for the #30DayMapChallenge, November 2026, made with UK open data.

## Day 1: Points

Pedestrian and cyclist casualties in Southampton, Portsmouth, the Isle of Wight and Hampshire, 2024 and 2025.

Open the map: https://emargaritis.github.io/30DayMapChallenge-2026/day01/

What you can do on the map:

- switch between 2024, 2025 and a side by side comparison
- show points, a heatmap, or both
- filter by casualty type (pedestrian or cyclist) and by severity (fatal, serious, slight)
- change dot sizes and opacity
- choose an Esri or OpenStreetMap basemap

### Data

Source: Department for Transport, Road safety data (STATS19).

- Download page: https://www.gov.uk/government/statistical-data-sets/road-safety-open-data
- Files used, for each of 2024 and 2025:
  - `dft-road-casualty-statistics-collision-<year>.csv`
  - `dft-road-casualty-statistics-casualty-<year>.csv`
- Licence: Open Government Licence v3.0, https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/

The raw files are large (about 58 MB for the four) and are not stored in this repository. Download them from the DfT page above.

### How the data was prepared

1. Keep collisions whose `local_authority_ons_district` is one of: E06000044 (Portsmouth), E06000045 (Southampton), E06000046 (Isle of Wight), E07000084 to E07000094 (the eleven Hampshire districts: Basingstoke and Deane, East Hampshire, Eastleigh, Fareham, Gosport, Hart, Havant, New Forest, Rushmoor, Test Valley, Winchester). Drop collisions with no coordinates.
2. From the casualty file keep casualties with `casualty_type` 0 (pedestrian) or 1 (cyclist) and join them to collisions on `collision_index`.
3. Each dot is one collision. Its severity is the most serious injury among the pedestrian and cyclist casualties in that collision (`casualty_severity`: 1 fatal, 2 serious, 3 slight).
4. Collisions with both a pedestrian and a cyclist casualty are drawn in purple (two in total across the two years).
5. The result is embedded in the HTML file, so the map needs no other files.

Counts on the map are collisions, not casualties.

### Credits

- Basemap tiles: Esri, and OpenStreetMap contributors. Credits are shown on the map.
- Map and code: Efstathios Margaritis, released under the MIT licence (see `LICENSE`). The data keeps its own licence, the Open Government Licence v3.0 (see above).

## Day 11: Sound

What changed in London's soundscape? A replication of the Chatty Maps method (Aiello, Schifanella, Quercia and Aletta, 2016) for London, built twice with identical rules: once for Flickr photos taken in 2005-2015 and once for 2016-2026. Each street segment is coloured by its dominant sound source: transport, nature, human, music, indoor or mechanical.

Open the map: https://emargaritis.github.io/30DayMapChallenge-2026/day11/

What you can do on the map:

- explore the 2016-2026 map and hover over a street to see how its sound profile changed since 2005-2015
- read the change in percentage points for each sound category, for streets that are mapped in both periods
- hover over a category name in the key to see the dictionary keywords it contains
- dim the low confidence streets with the switch

Streets shown in pale grey have too few sound tags in one or both periods to be compared.

### Data

- Photo tags and locations: Flickr API (`flickr.photos.search`), geotagged photos inside a London bounding box, matched to the sound dictionary. The photo database is not stored in this repository. The Flickr key is also kept out of the repository.
- Sound dictionary: Aiello et al. (2016), Dryad, doi:10.5061/dryad.tg735 (English terms, version 2). The file used is `day11/scripts/dictionary_clean.csv`.
- Streets: OpenStreetMap extract for London from BBBike (https://download.bbbike.org/osm/bbbike/London/London.osm.pbf, downloaded Wednesday 11th of November 2026). Licence: ODbL, OpenStreetMap contributors. The extract is not stored here (about 200 MB).
- Paper: https://doi.org/10.1098/rsos.150690

### How the data was prepared

1. Download the London OpenStreetMap extract and split the eight street types used in the paper into segments (`make_segments.py`).
2. Pull geotagged Flickr photos for the London bounding box and keep tags that match the dictionary exactly, after lower casing and removing punctuation (`flickr_pull.py`). Plurals are not counted in the baseline.
3. Assign each tag to the nearest street segment within a 22.5 m buffer and count tags per sound category (`build_sound_map.py`).
4. Convert counts to a share per category, standardise each category with a z score and colour the segment by its highest z score. Segments need at least 5 sound tags to be mapped.
5. Compare the two periods on segments mapped in both (`change_analysis.py`) and draw the static maps (`publication_maps.py`).
6. Embed the 2016-2026 map and the change values in one HTML file (`make_interactive_data.py`), so the map needs no other files.

Main results (baseline): 61,810 segments mapped for 2005-2015 and 52,745 for 2016-2026, with 35,382 mapped in both. The dominant sound source changed on 44.6% of common segments, against 26.2% expected from noise alone. Human sounds gained the most (mean share +5.8 points) and music lost the most (-4.1 points).

Full list of assumptions and departures from the paper: `day11/reports/Chatty_Maps_London_assumptions_register.docx`. Tables are in `day11/tables`, static maps in `day11/static_maps`, scripts and the two baseline segment files in `day11/scripts`.

### Credits

- Method: Aiello, Schifanella, Quercia and Aletta (2016), Chatty Maps: constructing sound maps of urban areas from social media data, Royal Society Open Science 3:150690.
- Map and code: Efstathios Margaritis, released under the MIT licence (see `LICENSE`). The data keeps its own licences (ODbL for OpenStreetMap, Flickr and Dryad terms as above).
