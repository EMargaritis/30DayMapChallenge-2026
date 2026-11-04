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
