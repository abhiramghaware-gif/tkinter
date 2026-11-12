# CHENNAI FLOODGUARD — 15-Slide Presentation Outline

Use this slide-by-slide blueprint for final-year project viva / defense slides. Suggested screenshots should come directly from running the application on the saved **Potheri** workspace.

---

### Slide 1 — Title Slide
- **Title:** CHENNAI FLOODGUARD — Hybrid Urban Flood Simulation & Emergency Decision-Support Prototype
- **Subtitle:** Pilot Study: Potheri, Chengalpattu District, Chennai | Python 3 + Tkinter + SQLite 3 (`v5`)
- **Note:** Educational & experimental engineering prototype (not an official warning/dispatch system)

### Slide 2 — Problem Statement & Local Context (Potheri, Chennai)
- Monsoon waterlogging hotspots along rapidly urbanizing corridors (paved surface growth + drainage bottlenecks).
- Operational gap: GIS tools, flood models, route planners, and relief inventories rarely work together offline in one transparent tool.

### Slide 3 — Project Objectives Across Phases 1–7
- Real OpenStreetMap neighbourhood import & `10 × 10` spatial grid modelling.
- SI cellular water-balance simulation & configurable risk mapping.
- Flood-aware NetworkX evacuation routing (**SafeRoute**) & SQLite emergency relief logistics.
- Non-destructive What-If experimentation, 12 automated PDF/CSV reports, DB reliability, and Windows packaging.

### Slide 4 — System Architecture & Modular Layering
- Diagram: `GUI (Tkinter)` -> `Services / Managers` -> `Core Physics & Routing Engines` -> `SQLite (v5, FK=ON)` + `Optional Online APIs (Nominatim / Overpass / Open-Meteo)`.
- Highlight clean separation: `core/` physics and `routing/` contain zero UI dependencies.

### Slide 5 — Home Dashboard & Integrated Navigation
- **Visual:** Screenshot of Phase 7 **Home Dashboard** (`phase7_dashboard.png`).
- **Key Points:** Strict SQLite-derived KPIs (no invented numbers), Live vs Cached weather age, active simulation summary badge, neighbourhood preview canvas, quick-launch actions.

### Slide 6 — Neighbourhood GIS Builder & Data Provenance
- **Visual:** Screenshot of **Neighbourhood Map** with 10 × 10 grid, OSM roads/buildings/waterbodies, and drainage markers.
- **Key Points:** Zoom/pan GeoViewport, spherical cell area (`m²`), GeoTIFF DEM import (`rasterio`), 9-category Land-Use + audit history, Data Quality completeness indicators (`imported` vs `user-entered` vs `missing`).

### Slide 7 — Flood Simulation Engine (SI Water-Balance Physics)
- Equations diagram: Rainfall ($\Delta h$) -> Water-limited Infiltration -> Operational Drainage ($Q_{\text{eff}}$) -> 4-Connected Downhill Head Flow ($E_i + d_i$).
- Explain `Elevation-based` vs `Illustrative Assumed Terrain` modes and mass-conservation audit ($\varepsilon \le 10^{-6}\text{ m}^3$).

### Slide 8 — Simulation Lab & Temporal Playback
- **Visual:** Screenshot of **Simulation Lab** showing progress/hydrograph or **Flood Map** heatmap animation.
- **Key Points:** Non-blocking background threading, 4 rainfall presets (`10/30/60/100 mm/hr`), temporal distributions, non-blocking `after()` heatmap animation, and exposed road/building layers.

### Slide 9 — SafeRoute: Flood-Aware Evacuation Planning
- **Visual:** Screenshot of **SafeRoute** showing Shortest (blue) vs Flood-Aware (green) vs Alternative (orange) routes and closed street (red).
- **Key Points:** NetworkX intersection-split road graph, Dijkstra exposure + closure avoidance, explicit penalization of `"Unknown"` exposure links, editable assumed speeds (`Walking` vs `Two-wheeler/Car`).

### Slide 10 — Emergency Resource & Relief Management
- **Visual:** Screenshot of **Emergency Management** dashboard + Shelter/Inventory views.
- **Key Points:** SQLite `v5` constraints (`occupied <= total`, `quantity >= 0`), `Registered (Unverified)` vs `Physically Verified`, masked volunteer contacts (`******XXXX`), atomic inventory ledger & allocation rollback, SafeRoute shelter links.

### Slide 11 — What-If Experiment Lab (Non-Destructive Testing)
- **Visual:** Screenshot of **What-If Lab** (`phase7_what_if.png`) displaying multi-scenario table & comparison bar chart.
- **Key Points:** Clones baseline configurations without mutating stored SQLite tables; 6 one-click experiments (Heavy Rain, Drain Failure, Hypothetical Relief Channel, Land-Use Shift, Road Closure, Combined Stress-Test) + compatibility warnings.

### Slide 12 — Multi-Scenario Comparison & Automated 12-Report Engine
- **Visual:** Screenshot of **Reports & Analytics** (`phase7_reports.png`) alongside a page of the generated Section 8 **Flood Simulation PDF Report**.
- **Key Points:** All 12 reports export cleanly in PDF (`PdfPages`) and CSV, clearly preserving missing/illustrative provenance & academic disclaimers.

### Slide 13 — Offline-First Reliability, Database Audit & Backup/Restore
- **Visual:** Screenshot of **Settings & Backup/Audit** screen (`phase7_settings.png`).
- **Key Points:** `PRAGMA foreign_keys = ON`, structural DB audit (`integrity_check`, `foreign_key_check`, duplicates, constraints), online SQLite backup with SHA-256 checksum, corrupt-file rejection, and automatic pre-restore safety snapshot.

### Slide 14 — Verification Suite & Standalone Windows Packaging
- **Verification Metric:** Highlight exact `pytest` pass counts across unit, integration workflows 1–5, and offline GUI smoke tests.
- **Deployment:** Reproducible `floodguard.spec` + `build_windows.py` PyInstaller packaging storing runtime DB/backups cleanly in `%LOCALAPPDATA%\ChennaiFloodGuard`.

### Slide 15 — Limitations, Future Scope & Q&A
- **Honest Limitations:** Simplified cellular physics vs 2D shallow-water Navier-Stokes; dependency on imported DEM & field drainage surveys; no live traffic/SCADA telemetry.
- **Future Scope:** LiDAR sub-grid coupling, SWMM pipe drainage integration, historical gauge calibration, multi-agency sync.
