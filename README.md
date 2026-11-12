# CHENNAI FLOODGUARD

**Hybrid Urban Flood Simulation, Flood-Aware Evacuation & Emergency Decision Support Prototype (Python / Tkinter)**  
*Final-Year Engineering Project — Phase 7 Integrated Release (`v1.0.0-phase7`)*

> **Educational & Experimental Prototype Notice:**  
> CHENNAI FLOODGUARD is an academic engineering prototype designed for educational and experimental urban flood decision-support exploration, beginning with **Potheri, Chengalpattu district, Tamil Nadu, India**. It is **not** an official meteorological forecast, flood-warning broadcast, certified hydraulic model, or official emergency dispatch system. Simulated water depths, hypothetical rainfall scenarios, illustrative terrain/infiltration assumptions, assumed travel speeds, What-If hypothetical infrastructure, and unverified shelter/stock records must **never** be presented as verified real-world observations or official evacuation orders.

---

## 1. Project Overview

CHENNAI FLOODGUARD integrates geographical modelling, cellular urban flood water-balance simulation, interactive flood risk mapping, NetworkX evacuation routing, emergency relief resource management, What-If scenario experimentation, and automated PDF/CSV reporting into a single **offline-first** desktop application backed by SQLite (`PRAGMA user_version = 5`).

| Phase | Milestone | Key Capabilities Delivered |
| :--- | :--- | :--- |
| **Phase 1** | Foundation & Mapping | Nominatim geocoding, Overpass OSM import, interactive Canvas map & 10 × 10 grid editor, optional Open-Meteo weather snapshot, offline SQLite `v1` |
| **Phase 2** | Advanced GIS Builder | Road/building classification, geodesic lengths, Shapely spatial links, GeoTIFF DEM elevation import (`rasterio`/`pyproj`), 9-category land-use & audit history, manual drainage editor, Data Quality dashboard, GeoJSON/CSV import/export (`v2`) |
| **Phase 3** | Flood Simulation Engine | SI water-balance model (hypothetical rainfall schedules, soil infiltration, drainage removal, 4-neighbour head-driven flow, mass-conservation audit), background-threaded Simulation Lab GUI, SQLite run history (`v3`) |
| **Phase 4** | Flood Visualization & Risk | 6-tier configurable depth heatmap, non-blocking `after()` progression animation, prototype risk classifier, road/building exposure overlays, 6 Matplotlib charts, side-by-side comparison, GeoJSON/CSV/PNG/PDF exports |
| **Phase 5** | SafeRoute Evacuation | NetworkX street graph from OSM, segment flood-exposure classification (`Unknown` never treated as safe), Dijkstra Shortest / Flood-Aware / Alternative routes, manual closure manager, editable travel speeds, SQLite `v4` |
| **Phase 6** | Emergency Management | 10-tab emergency console backed strictly by SQLite `v5`: Shelters (`occupied <= total`), Rescue Teams, Vehicles, Volunteers (contact masking/redaction), Inventory + atomic transactions, Confirmed atomic allocations + rollback, Operations, Alerts, SafeRoute shelter links, 10 CSV/PDF reports |
| **Phase 7** | **Final Integration, What-If Lab, Reports & Packaging** | **10-screen integrated workspace**, enhanced **Home Dashboard**, **What-If Lab** (6 ready-made experiments + custom non-destructive overrides + multi-scenario comparator), **Reports & Analytics** (12 PDF & CSV reports), **DB Audit / Online Backup / Confirmed Restore**, SQLite-persisted **Settings**, end-to-end tests, documentation & PyInstaller `.exe` spec |

---

## 2. Problem Statement & Motivation

Rapidly urbanizing peri-urban corridors along Chennai's southern GST Roadbelt—such as **Potheri**—experience recurring monsoon waterlogging driven by intense cloudburst events, impervious surface expansion, and localized drainage bottlenecks. Municipal planners, disaster-management students, and local volunteers often lack an approachable, inspectable, offline-capable desktop tool that connects **geographical map layers**, **physically transparent runoff accumulation**, **passable evacuation street networks**, and **relief logistics** in one unified database.

---

## 3. Target Users & Scope

- **Urban Planning & Civil Engineering Students / Researchers**: Explore how rainfall intensity, drainage blockages, hypothetical relief channels, and land-use permeability alter surface ponding.
- **Emergency Preparedness Coordinators (Prototype Training)**: Practice shelter capacity tracking, relief stock auditing, and flood-aware route comparison without live internet dependence.
- **Explicit Out-of-Scope**: Real-time municipal SCADA telemetry, 2D shallow-water Navier-Stokes pipe hydraulics, live traffic routing, automated SMS/dispatch, or public safety certification.

---

## 4. Key Features Across the 10 Integrated Modules

1. **Dashboard (`gui/dashboard.py`)**: Real SQLite KPIs (workspace & connectivity badge, weather snapshot with freshness/cached status, last/selected simulation peak depth & affected/high-risk cell counts, shelter capacity, teams/vehicles, low-stock alerts, GIS completeness), live neighbourhood preview canvas, quick-launch shortcuts, and recent simulation/operations/alerts lists.
2. **Neighbourhood Map (`gui/map_editor.py`)**: Multi-layer OpenStreetMap viewer with mouse-wheel zoom, drag-to-pan, feature selection, 10 × 10 grid editing, Drainage Manager, Elevation GeoTIFF importer, Land-Use bulk editor, Data Quality inspector, and GeoJSON/CSV export.
3. **Weather Monitor (`gui/components.py`, `services/weather_service.py`)**: Optional Open-Meteo current conditions & hourly table with offline cache fallback, age indicator, and explicit online/offline guards.
4. **Simulation Lab (`gui/simulation_lab.py`)**: Background-threaded SI water-balance simulator with presets (`10/30/60/100 mm/hr`), temporal profiles (`constant`, `increasing`, `decreasing`, `custom`), `Elevation-based` vs `Illustrative Assumed Terrain` mode, editable infiltration table, non-destructive drain disabling, progress bar, hydrograph, and SQLite run loader.
5. **Flood Map (`visualization/flood_map.py`)**: Interactive spatial heatmap with configurable `Light Grey` / `Green` zero-water tint, dynamic legend, time-step animation (`Start`, `Pause`, `Stop`, `0.5x–4x`), road/building/shelter exposure toggles, cell inspector with provenance tags, and editable threshold settings.
6. **SafeRoute (`gui/saferoute_screen.py`)**: Interactive evacuation route planner computing Shortest, Flood-Aware, and Alternative paths over OSM road graphs, manual street closure editing, shelter destination filtering, and route history storage.
7. **Emergency Management (`gui/emergency_dashboard.py`, `gui/shelter_screen.py`, `gui/rescue_team_screen.py`, `gui/inventory_screen.py`, `gui/operation_screen.py`)**: Complete relief logistics hub with strict SQLite validation, masked volunteer phone numbers, atomic stock movements, rollback-safe allocations, rule-driven alerts, and one-click routing to flood-aware shelter navigation.
8. **What-If Lab (`gui/what_if_lab.py`, `core/scenario_manager.py`, `core/scenario_comparator.py`)**: Non-destructive cloning of any saved simulation run + 6 structured experiments (`Heavy Rainfall`, `Drainage Failure`, `Improved Drainage & Hypothetical Channel`, `Land-Use / Infiltration Change`, `Road Closure & Alternative SafeRoute`, `Combined Extreme Stress-Test`), custom overrides, side-by-side heatmaps, Matplotlib comparison chart, and PDF/CSV comparison export.
9. **Reports & Analytics (`gui/reports_screen.py`, `services/report_generator.py`)**: Unified generator producing all **12 operational & analytical reports** in **PDF** (Matplotlib `PdfPages` with cover metadata, figures, tables & disclaimers) and **CSV**.
10. **Settings & System Health (`gui/components.py`, `database/backup_manager.py`)**: Offline-first toggle, persistent risk/exposure thresholds (`app_settings`), assumed speed defaults, drainage defaults, **Database Integrity Audit**, **Online SQLite Backup** (+ SHA-256 `.meta.json`), and **Confirmed Restore** (with automatic pre-restore safety backup).

---

## 5. System Architecture Overview

```
d:\tkinter\
├── main.py                      # Entry point, logging setup, frozen seed-DB init, uncaught UI guard
├── config.py                    # Constants, palette, frozen vs source paths, 12 report registry
├── floodguard.spec              # PyInstaller Windows build specification (--onedir)
├── build_windows.py             # Reproducible PyInstaller Windows packaging wrapper
├── requirements.txt             # Pinned core & optional GIS dependencies
├── core/                        # Pure domain models, SI water-balance engine, What-If & risk math
│   ├── models.py                # Neighbourhood, GridCell, OSMFeature, DrainageFeature, DashboardSummary
│   ├── workspace.py             # WorkspaceManager lifecycle & grid creation
│   ├── geo_utils.py             # Geodesic Haversine / Shapely polygon & line clipping helpers
│   ├── grid_manager.py          # 10x10 spherical grid generator & export helpers
│   ├── simulation_config.py     # SimulationConfig dataclass, presets, JSON serialization, What-If fields
│   ├── rainfall_model.py        # Temporal storm profiles & SI volume conversion
│   ├── infiltration_model.py    # Land-use infiltration rates & water-limited soil absorption
│   ├── runoff_model.py          # Excess runoff diagnostics
│   ├── drainage_model.py        # Operational status & unit conversions -> effective m3/s
│   ├── water_flow_model.py      # 4-connected hydraulic-head routing with sub-stepping & closed bounds
│   ├── simulation_engine.py     # validate_scenario, step engine, mass-balance audit (< 1e-6 m3)
│   ├── risk_classifier.py       # 6-tier HeatmapColorScale & prototype risk classification
│   ├── flood_statistics.py      # Timestep stats & two-run comparison compatibility guard
│   ├── scenario_manager.py      # Non-destructive scenario cloning & 6 structured What-If experiments
│   ├── scenario_comparator.py   # Multi-run comparison matrix, peak-depth time, SafeRoute impact, diffs
│   └── validation.py            # Coordinate, bbox, capacity, stock, & input validators
├── database/                    # SQLite persistence layer (v5, FK=ON)
│   ├── schema.sql               # Complete 27-table normalized schema + indexes
│   ├── db.py                    # DatabaseManager, non-destructive v1->v5 migrations, transactions
│   ├── repository.py            # FloodGuardRepository CRUD across workspaces, grids, OSM, runs, settings
│   └── backup_manager.py        # Audit (integrity/FK/dups), online SQLite backup + SHA-256, confirmed restore
├── services/                    # External APIs (offline-safe), GIS I/O & Report Generator
│   ├── geocoding_service.py     # Nominatim search & rate-limited requests
│   ├── osm_service.py           # Overpass road/building/water/green import & road categorization
│   ├── weather_service.py       # Optional Open-Meteo client + cache staleness evaluation
│   ├── elevation_service.py     # GeoTIFF raster DEM zonal stats (rasterio/pyproj optional)
│   ├── landuse_service.py       # Bulk land-use classification & audit history
│   ├── geo_exports.py           # Neighbourhood GeoJSON & CSV importers/exporters
│   ├── simulation_export.py     # Phase 4 CSV, Risk CSV, GeoJSON, PNG & summary PDF exports
│   ├── report_generator.py      # Phase 7 unified PDF/CSV ReportGenerator covering all 12 reports
├── routing/                     # Phase 5 SafeRoute NetworkX engine
│   ├── road_network.py          # OSM street -> NetworkX MultiGraph + intersection splitting
│   ├── flood_exposure.py        # Segment-to-grid flood exposure (Unknown never marked Safe)
│   ├── route_planner.py         # Dijkstra Shortest / Flood-Aware / Alternative routes + closures
│   ├── travel_time.py           # Editable assumed speeds (Walking vs Two-wheeler/Car)
│   └── route_comparison.py      # Multi-route metrics & trade-off summaries
├── emergency/                   # Phase 6 Relief Logistics & Privacy Engine
│   ├── shelter_manager.py       # Shelter CRUD & occupied <= total enforcement
│   ├── rescue_team_manager.py   # Team roster & assignments
│   ├── vehicle_manager.py       # Fleet registry & team linkage
│   ├── volunteer_manager.py     # Volunteer registry with phone masking/redaction
│   ├── inventory_manager.py     # Stock CRUD & verification status
│   ├── inventory_transactions.py# Atomic ledger audit trail
│   ├── resource_allocator.py    # Confirmed multi-resource allocation & rollback
│   ├── operation_manager.py     # Operations lifecycle & SQLite KPI aggregator
│   ├── alert_manager.py         # Rule-driven alert engine & acknowledgements
│   └── emergency_exports.py     # Operational CSV & PDF reports
├── visualization/               # Tkinter Canvas renderers, animation & Matplotlib charts
│   ├── map_renderer.py          # Pan/zoom GeoViewport & layered OSM/Drainage renderer
│   ├── grid_renderer.py         # Interactive 10x10 grid & land-use tint renderer
│   ├── heatmap_renderer.py      # 6-tier flood depth overlay & timestamp HUD
│   ├── map_layers.py            # Road/building exposure & OSM candidate landmark markers
│   ├── flood_animation.py       # Non-blocking after() animation loop
│   ├── flood_charts.py          # 6 synchronized Matplotlib progression charts
│   ├── flood_map.py             # Phase 4 Flood Map interactive workspace
│   └── route_renderer.py        # SafeRoute Canvas overlay
├── gui/                         # Tkinter views & application shell
│   ├── app.py                   # Root FloodGuardApp shell, sidebar navigation, header badges, threads
│   ├── dashboard.py             # Phase 7 Home Dashboard
│   ├── map_editor.py            # Phase 2 Advanced GIS Neighbourhood Map Editor
│   ├── dialogs.py               # Coordinate search, GeoTIFF import, Drainage & Bulk editors
│   ├── components.py            # StatCard, WeatherView, SettingsView (persisted + Backup/Audit UI)
│   ├── simulation_lab.py        # Phase 3 Simulation Lab screen
│   ├── scenario_comparison.py   # Phase 4 two-run side-by-side comparison screen
│   ├── saferoute_screen.py      # Phase 5 SafeRoute evacuation planner screen
│   ├── emergency_dashboard.py   # Phase 6 Overview KPIs & Matplotlib charts
│   ├── shelter_screen.py        # Shelter & Volunteer views
│   ├── rescue_team_screen.py    # Rescue Team & Vehicle views
│   ├── inventory_screen.py      # Inventory, Stock Ledger & Alerts views
│   ├── operation_screen.py      # Operations & Atomic Allocations views
│   ├── what_if_lab.py           # Phase 7 What-If Lab (6 experiments + custom + comparator)
│   └── reports_screen.py        # Phase 7 Reports & Analytics (12 PDF/CSV reports + preview)
├── docs/                        # Phase 7 academic documentation
│   ├── PROJECT_REPORT.md
│   ├── PRESENTATION_OUTLINE.md
│   └── DEMO_GUIDE.md
└── tests/                       # Complete offline pytest verification suite
    ├── test_database.py
    ├── test_geocoding.py
    ├── test_grid.py
    ├── test_validation.py
    ├── test_phase2.py
    ├── test_phase3.py
    ├── test_phase4.py
    ├── test_phase5.py
    ├── test_phase6.py
    └── test_phase7.py
```

---

## 6. Installation Instructions

### Prerequisites
- **Python 3.11+** (tested on Python 3.14 on Windows 10/11) with **Tkinter** (`tkinter`) included.
- **Git** (optional, for cloning) and standard **MSVC / Windows desktop runtime** for Matplotlib/NumPy wheels.

### Virtual Environment Setup (Windows PowerShell)
```powershell
cd d:\tkinter
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
```

> **Note on Optional GIS Libraries (`shapely`, `rasterio`, `pyproj`)**: Core mapping, grid simulation, What-If Lab, SafeRoute, Emergency Management, and all 12 PDF/CSV reports work completely offline even if GeoTIFF raster libraries (`rasterio`/`pyproj`) cannot compile on a restricted host; GeoTIFF elevation raster import activates automatically when `rasterio` and `pyproj` are installed.

---

## 7. Running From Source

```powershell
cd d:\tkinter
python main.py
```
- The saved workspace database is stored at `data\floodguard.db` (override anytime via the `FLOODGUARD_DATA_DIR` environment variable).
- Runtime logs are written to `data\floodguard.log`.

---

## 8. Building Windows Executable (`PyInstaller`)

PyInstaller build files (`floodguard.spec` and `build_windows.py`) are ready in the project root:
1. Install PyInstaller in your active Python environment:
   ```powershell
   pip install "pyinstaller>=6.0"
   ```
2. Run the automated build helper:
   ```powershell
   python build_windows.py
   ```
   *(Or run `python -m PyInstaller --clean --noconfirm floodguard.spec` directly.)*
3. Locate the packaged bundle at `dist\ChennaiFloodGuard\ChennaiFloodGuard.exe`.
4. **Writable User Data Behavior**: When running as a frozen PyInstaller executable (`sys.frozen == True`), `config.py` keeps bundled code/schema/seed assets inside the read-only bundle and automatically stores writable runtime data (`floodguard.db`, `backups/`, `exports/`, `cache/`, `floodguard.log`) in `%LOCALAPPDATA%\ChennaiFloodGuard` (or `FLOODGUARD_DATA_DIR` if set). If `%LOCALAPPDATA%\ChennaiFloodGuard\floodguard.db` does not exist yet on first launch, `main.py` seeds it from the bundled `data/floodguard.db` if included.

---

## 9. Offline Operation Guide

- Toggle **Offline Mode (Block external Nominatim / Overpass / Open-Meteo)** in **Settings** (`app_settings` key `force_offline`) to force zero external HTTP calls.
- All map geometry (`osm_features`), grid attributes (`grid_cells`), weather snapshots (`weather_observations`), simulation runs (`simulation_runs` / `simulation_results`), road graphs (`road_network_nodes` / `road_network_edges`), road conditions, emergency tables, PDF/CSV exports, and SQLite backups work 100% locally with zero internet access.

---

## 10. Database Schema & Backup System

- **Database Engine**: SQLite 3 with `PRAGMA foreign_keys = ON;` enforced on every connection and `PRAGMA user_version = 5`.
- **27 Normalized Tables** grouped by domain:
  - *GIS & Config*: `schema_migrations`, `neighbourhoods`, `grid_cells`, `osm_features`, `weather_observations`, `scenarios`, `app_settings`, `drainage_features`, `grid_feature_links`, `elevation_sources`, `land_use_history`.
  - *Simulation*: `simulation_runs`, `simulation_results`, `simulation_metrics`.
  - *SafeRoute*: `road_network_nodes`, `road_network_edges`, `road_conditions`, `route_history`.
  - *Emergency Management*: `shelters`, `rescue_teams`, `vehicles`, `volunteers`, `inventory_items`, `inventory_transactions`, `resource_allocations`, `emergency_operations`, `emergency_alerts`.
- **Database Integrity, Backup & Safe Restore (`database/backup_manager.py`)**:
  - **Audit**: Runs `PRAGMA integrity_check`, `PRAGMA foreign_key_check`, duplicate-grid checks, `occupied <= total` capacity invariant checks, negative-stock checks, required-table checks, and index counts.
  - **Online Backup**: Uses SQLite's `Connection.backup()` API into `data/backups/floodguard_<label>_<timestamp>.db` alongside a SHA-256 checksum & table-count `.meta.json` sidecar.
  - **Safe Restore**: Rejects missing/corrupt files or missing tables before overwriting; mandates explicit user confirmation (`user_confirmed=True`); automatically saves a timestamped `pre_restore_safety_*.db` backup before applying the restore; and executes non-destructive migrations if restoring an older backup.

---

## 11. Flood Simulation Mathematical Model

All physics operate in **SI units** (`m`, `m²`, `m³`, `s`):

| Process | Equation | Implementation Safeguards |
| :--- | :--- | :--- |
| **Rainfall Input** | $\Delta h_k = \frac{I_k \cdot (\Delta t / 3600)}{1000}$, $V_{\text{rain},i,k} = \Delta h_k \cdot A_i$ | Supports `constant`, `increasing`, `decreasing`, `custom` distributions |
| **Infiltration Loss** | $V_{\text{inf},i,k} = \min\!\left(V_i,\; \frac{f_i \cdot (\Delta t / 3600)}{1000} \cdot A_i\right)$ | Uses cell rate or editable category default; strictly water-limited |
| **Drainage Removal** | $V_{\text{dr},i,k} = \min\!\left(V_i,\; Q_{\text{eff},i} \cdot \Delta t\right)$ | Status factors (`Operational=1.0`, `Partially blocked=0.5`, `Blocked/Unknown=0.0`); `NULL` capacity = `0` |
| **Surface Routing** | Hydraulic head $H_i = E_i + d_i$, flow strictly downhill ($H_i > H_j$) | Outgoing fluxes scaled so $\sum_j \text{flux}_{i\to j} \le V_i$; closed boundaries; sub-stepping stability |
| **Mass Conservation** | $\left|(V_0 + \sum V_{\text{rain}}) - (V_{\text{final}} + \sum V_{\text{infil}} + \sum V_{\text{drain}})\right| \le 10^{-6}\text{ m}^3$ | Audited and stored per run in `simulation_metrics` |

---

## 12. What-If Experiments Guide (`gui/what_if_lab.py`)

`ScenarioManager` clones any baseline `SimulationConfig` without altering saved SQLite tables or baseline results, and offers **6 one-click experiments** plus a **Custom Parameter Override Lab**:

1. **Experiment 1 — Heavy Rainfall Sensitivity**: Compares `30` vs `60` vs `100 mm/hr` under identical drainage and infiltration.
2. **Experiment 2 — Drainage Failure Analysis**: Compares `Normal Drainage` vs `1 Drain Failed` vs `Multi-Drain Failure` (or scaled capacity fallback if no operational drains exist).
3. **Experiment 3 — Improved Drainage & Hypothetical Channel**: Compares `Existing` vs `+50% Upgraded` vs `Hypothetical Relief Channel (450 L/s)` explicitly tagged `what-if-hypothetical`.
4. **Experiment 4 — Land-Use / Soil Permeability Impact**: Compares `Baseline` vs `+50% Paved / Concrete` (reduced infiltration) vs `+40% Permeable Green Area` (increased infiltration).
5. **Experiment 5 — Road Closure & Alternative SafeRoute**: Evaluates Shortest vs Flood-Aware vs Alternative evacuation distance, travel time & blockage count with selected road closures applied.
6. **Experiment 6 — Combined Extreme Stress-Test**: Evaluates `100 mm/hr` rainfall + `50%` drainage capacity + `40%` reduced infiltration (clearly flagged as hypothetical stress test).

---

## 13. SafeRoute Guide

- Builds a `NetworkX MultiGraph` from imported OSM ways split at shared topological intersections (`geodesic` distance in metres).
- Evaluates each edge's maximum flood depth across intersecting grid cells at the selected simulation timestep (`0–10 cm Low`, `>10–30 cm Moderate`, `>30–60 cm High`, `>60 cm Very high`; unlinked/unverified terrain edges become `Unknown` and are **penalized rather than treated as safe**).
- Computes **Shortest Route**, **Flood-Aware Route** (`distance + depth penalty + inspection/unknown penalty`), and **Alternative Route**, avoiding user-marked `Closed` or `Blocked` segments.

---

## 14. Emergency Resource Management Guide

- **Shelters**: Register shelters, edit capacity (`0 <= occupied <= total`), facilities, and `Verified Shelter` vs `Registered (Unverified)` tags, and jump straight to Flood-Aware routing toward any shelter.
- **Rescue Teams & Vehicles**: Track manual team rosters, operational status, boats/ambulances/vans, and manual team-vehicle assignments.
- **Volunteers**: Store responder skills and availability while masking contact numbers (`******XXXX`) in tables and redacting sensitive numbers in default exports and map tooltips.
- **Inventory & Atomic Allocations**: Record stock receipts/adjustments with immutable ledger rows (`inventory_transactions`), prevent negative stock, track expiry alerts, and perform rollback-safe allocations (`resource_allocations`).

---

## 15. Reports & Analytics Guide (`services/report_generator.py`)

All **12 Reports** export natively to **PDF** (`PdfPages` multi-page reports with project metadata, timestamps, charts/tables & academic disclaimers) and **CSV**:

| # | Report Key | Report Title | Contents |
| :---: | :--- | :--- | :--- |
| 1 | `neighbourhood_profile` | Neighbourhood Profile Report | Bounding box, grid size, elevation/land-use/drainage completeness & provenance counts |
| 2 | `geographical_data` | Geographical Data Report | OSM roads, buildings, waterways/wetlands, green areas, and drainage features inventory |
| 3 | `weather_data` | Weather Data Report | Saved Open-Meteo observation history (live/cached distinction, rainfall, temp, humidity) |
| 4 | `flood_simulation` | **Flood Simulation Report** | Cover page, scenario config & water-balance summary, step progression table, cell depth & risk breakdown, 4 Matplotlib charts (hydrograph, cumulative rain/infil/drain, cell distribution, max depth progression), & assumptions |
| 5 | `flood_risk_analysis` | Flood-Risk Analysis Report | Cell-by-cell classification across configurable risk bands + exposed roads & buildings summary |
| 6 | `scenario_comparison` | Scenario Comparison Report | Side-by-side multi-scenario matrix, peak depth timing, delta/% changes, config diffs, compatibility warnings & bar chart |
| 7 | `saferoute_analysis` | SafeRoute Analysis Report | Road condition breakdown, exposure levels, shortest vs flood-aware route history & speed assumptions |
| 8 | `shelter_capacity` | Shelter Capacity Report | Shelter registry, occupied/available beds, utilization ratios, & verification tags |
| 9 | `emergency_resource` | Emergency Resource Report | Rescue teams, vehicle fleet, availability counts, & masked volunteer summary |
| 10 | `inventory` | Inventory Report | Relief stock quantities, verification status, low-stock flags, expiry alerts, & transaction counts |
| 11 | `emergency_operations` | Emergency Operations Report | Operations log, priority/status breakdown, resource allocations, & active SQLite alerts |
| 12 | `complete_project` | Complete Project Report | Executive integrated synthesis across GIS, weather, simulations, SafeRoute, What-If, & emergency readiness |

---

## 16. Testing Guide

Run the complete offline test suite from the project root:
```powershell
python -m pytest -v
```
Tests across `tests/test_database.py`, `test_geocoding.py`, `test_grid.py`, `test_validation.py`, `test_phase2.py` through `test_phase7.py` cover database migrations `v1->v5`, Overpass/Nominatim/Open-Meteo fixture parsing, spherical geometry, GeoTIFF DEM import, simulation SI water balance & mass conservation, flood heatmap & animation lifecycle, Dijkstra SafeRoute avoidance, emergency resource atomicity & contact redaction, What-If 6 experiments, all 12 PDF/CSV reports, DB audit/backup/restore, and end-to-end GUI smoke tests.

---

## 17. Known Limitations

1. **Grid & Hydraulic Simplification**: Uses a `10 × 10` cellular water-balance model with head-difference diffusive flow (`elevation_m + depth`), not 2D Saint-Venant momentum equations, pressurized storm-drain hydraulics, or groundwater seepage.
2. **DEM & Drainage Completeness**: Unless the user imports a verified GeoTIFF DEM for Potheri and enters surveyed drain capacities, runs must explicitly select *Illustrative Assumed Terrain* mode and are tagged accordingly.
3. **OpenStreetMap & Speed Assumptions**: OSM road connectivity may miss private/new lanes or turn restrictions; assumed walking/vehicle speeds omit live traffic, signals, and police barricades.
4. **No Live Telemetry or Dispatch**: Weather refresh uses optional public forecast snapshots; relief shelters and inventory rely on manual operator entries and verification flags.

---

## 18. Future Work

- Higher-resolution sub-catchment meshes (`25 m` / LiDAR DEM integration) and 1D–2D linked pipe-channel coupling (e.g., SWMM interoperability).
- Historical Chennai monsoon rainfall hyetograph archive comparison and calibration against gauge records.
- Multi-user Role-Based Access Control (RBAC) and field synchronization for municipal relief camps.
- Bilingual Tamil / English operator UI localization.

---

## 19. License & Third-Party Attributions

- **Map & Feature Geometry**: `© OpenStreetMap contributors` (ODbL) via Nominatim and Overpass API.
- **Optional Weather Forecast Feed**: `Weather data by Open-Meteo.com`.
- **Core Python Ecosystem**: Tkinter (`Python PSF License`), NumPy, Matplotlib, NetworkX, Pillow, Requests, pytest, Shapely, Rasterio, PyProj.

---

## 20. Team & Academic Usage Notes

Developed as a modular final-year engineering capstone project by a 3-student team. For evaluation scripts, report structure, and 10-minute live demo guidance, see:
- [docs/PROJECT_REPORT.md](docs/PROJECT_REPORT.md)
- [docs/PRESENTATION_OUTLINE.md](docs/PRESENTATION_OUTLINE.md)
- [docs/DEMO_GUIDE.md](docs/DEMO_GUIDE.md)
