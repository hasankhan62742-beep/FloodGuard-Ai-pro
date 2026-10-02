# FloodGuard AI — Methodology (for PILDAT presentation)

## What the app predicts
For any location in Pakistan (given as latitude/longitude), FloodGuard AI
estimates the **probability that the area is flood-prone**, based on how similar
it is to places that have actually flooded before. The number is a
**susceptibility estimate** — it is not a weather forecast and not an
emergency warning.

## Data used (all real, all documented)
1. **79 historical flood events (2006–2025)** — 23 georeferenced records from
   the EM-DAT disaster database (via the public Dartmouth/EM-DAT merged
   archive), plus 56 documented major events: the 2010 Indus super-flood,
   2011 Sindh floods, 2012 monsoon floods, 2014 Punjab floods, 2015 Chitral,
   2020 Karachi urban floods, the 2022 super-flood, and the 2025 KP / GB /
   Punjab / Karachi floods (2025 locations cross-checked against NDMA, UNICEF
   and ReliefWeb reporting).
2. **28,916 villages/settlements** across Pakistan (OpenStreetMap-based
   populated-places dataset) — the geography the model learns on.
3. **Elevation** for every location (Open-Meteo elevation data).
4. **Distance to the nearest major river** — Indus, Jhelum, Chenab, Ravi,
   Sutlej and Kabul — traced as approximate waypoint routes.
5. **Monsoon rainfall history, 1991 → 2026** — 35 years of July–September
   rainfall per location (ERA5 climate reanalysis via Open-Meteo), summarised
   as the average monsoon total and whether monsoons are getting wetter or
   drier over time at that spot.

## How the model learns
Each village is labelled "flood-prone" if it lies within 15 km of any of the
79 historical flood events, otherwise "not flood-prone". A Random Forest
machine-learning model (400 decision trees, tuned by 3-fold cross-validation)
then learns which combinations of the 7 features — location, elevation,
population, river distance, monsoon rainfall and its trend — best separate the
two groups. Training used 20,972 villages; 20% were held back purely for
testing and never seen during training.

## Test results (honest numbers)
On the held-back test set: **accuracy 98.5%, precision 96.8%, recall 98.0%**.
A dedicated South Punjab check (166 test villages across Multan,
Muzaffargarh, D.G. Khan, Rajanpur, Rahim Yar Khan, Bahawalpur, Lodhran,
Vehari, Khanewal, Layyah, Bhakkar and Mianwali) scored perfectly — but on a
small sample, so treat it as indicative, not proof.

**Important honest caveat for analysts:** the labels come from *proximity to
past events*, not from observed flooding at each individual village, and the
model partly learns event geography. The scores therefore describe how well
the model reproduces historical flood geography — strong and useful as a
planning/awareness signal, but not a guarantee about any single future event.
River routes are approximate waypoint traces, and 2025 is the latest event
year in the training data.

## What the percentage means — and doesn't
- **High %** → this place looks like places that have flooded repeatedly
  (low, near a river, wet monsoon trend). Take local advisories seriously.
- **Low %** → no historical flood signal here. It does **not** mean flooding
  is impossible.
- Always follow official **PDMA / NDMA** alerts in an emergency. FloodGuard AI
  is a planning and awareness tool, not a warning system.
