# CHENNAI FLOODGUARD — 10-Minute Live Evaluation Demo Guide

This step-by-step guide walks examiners smoothly through Phases 1–7 in **10 minutes**, using the saved **Potheri** workspace offline (zero internet required during evaluation).

---

## Pre-Demo Checklist (30 Seconds Before Evaluation)
1. Confirm Python environment is ready:
   ```powershell
   cd d:\tkinter
   python -m pytest -v
   ```
2. Launch the desktop app:
   ```powershell
   python main.py
   ```
3. Verify header bar badges: **App**, **Version (`1.0.0-phase7`)**, **Neighbourhood (`POTHERI`)**, **Network Status**, **Database (`SQLite OK (v5, FK=ON)`)**, and **Active Sim**.

---

## Minute-by-Minute Live Walkthrough

### Minutes 0:00 – 1:30 | Home Dashboard & Settings (Integration Overview)
- Start on **Dashboard**: point out that every KPI card reads live from SQLite `data/floodguard.db`—notice real OSM road/building counts, saved weather status (`Live`/`Cached`/`Unavailable`), latest simulation stats, and honest zero/empty emergency counts if none are entered.
- Open **Settings**: toggle **Offline Mode** ON to prove the entire system functions cleanly without internet; inspect **Risk Thresholds** & **Speed Assumptions** persistence; click **Run DB Audit** to show `integrity_check = ok`, `foreign_key_check = clean`, and zero duplicate/constraint violations.

### Minutes 1:30 – 3:00 | Neighbourhood Map (GIS Model & Provenance)
- Open **Neighbourhood Map**: zoom in/out with mouse wheel and drag-pan across Potheri roads, buildings, and waterways.
- Click a road segment and a `10 × 10` grid cell to show the **Feature/Cell Inspector** displaying geodesic length (`m`), cell area (`m²`), land-use category, infiltration rate, and explicit data provenance (`imported` vs `user-entered` vs `missing`).
- Briefly open **Drainage Manager** to show manually entered drainage points & operational status (`Operational`, `Partially blocked`, `Blocked`, `Unknown`).

### Minutes 3:00 – 4:30 | Simulation Lab & Flood Map (SI Physics + Playback)
- Open **Simulation Lab**: select preset **Heavy rainfall (60 mm/hr)**, duration `30 min`, `5 min` step, and note **Simulation Mode** (`Elevation-based` vs `Illustrative Assumed Terrain` disclaimer).
- Click **Start Simulation**: highlight non-blocking background execution, progress updates, **Mass Conservation Error** (`<= 1e-6 m³` in metrics), and the live Matplotlib hydrograph.
- Switch to **Flood Map**: press **Start Animation** to watch water progression across time steps, toggle **Exposed Roads / Buildings**, and click a peak cell to show prototype risk classification (`No surface flooding`—never `"Safe"`).

### Minutes 4:30 – 6:00 | SafeRoute (Flood-Aware Evacuation)
- Open **SafeRoute**: pick an Origin and Destination (or candidate landmark) on the Potheri road graph.
- Click **Calculate Routes** (`Two-wheeler/Car`): contrast **Shortest Route** (Blue) against **Flood-Aware Route** (Green) and **Alternative Route** (Orange).
- Right-click or edit one road edge along the shortest path to **Closed**, click **Recalculate**, and show SafeRoute dynamically detouring around both flooded and closed segments (and warning about `"Unknown"` exposure links).

### Minutes 6:00 – 7:30 | Emergency Management Console
- Open **Emergency Management**: demonstrate **Shelters** (`occupied <= total` enforced), **Volunteers** (masked phone display `******XXXX` & redacted exports), and **Inventory** (`Registered (Unverified)` vs `Physically Verified` + atomic ledger transactions).
- Record an allocation or dispatch operation, then click **Open in SafeRoute** for a shelter to demonstrate module-to-module integration.

### Minutes 7:30 – 9:00 | What-If Lab (Non-Destructive Experiments)
- Open **What-If Lab**: select the baseline run you just executed.
- Run **Experiment 1 (30 vs 60 vs 100 mm/hr)** or **Experiment 3 (Existing vs +50% vs Hypothetical Relief Channel)**—show that baseline `grid_cells` and `drainage_features` in SQLite remain untouched while hypothetical drainage is explicitly flagged `what-if-hypothetical`.
- Point out the multi-scenario delta matrix, `N/A (baseline=0)` safe percentage handling, and dual comparison chart.

### Minutes 9:00 – 10:00 | Reports & Analytics + Safe Backup
- Open **Reports & Analytics**: select **4. Flood Simulation Report** (and/or **12. Complete Project Report**), click **Generate PDF**, preview the generated file path, and open the multi-page PDF showing cover metadata, summary tables, and 4 Matplotlib figures.
- Return briefly to **Settings -> Create Verified Backup** to demonstrate instant online SQLite backup creation with SHA-256 verification.

---

## Expected Examiner Q&A Talking Points
1. **"Why doesn't your simulator use Navier-Stokes / SWMM?"**  
   *Answer:* Our goal is an explainable, zero-black-box cellular water-balance engine coupling SI runoff, infiltration, operational drainage, and head-driven cell transfer so every litre/m³ of water is mass-balance audited (`error <= 1e-6 m³`). We explicitly document this simplification in `README.md`, `PROJECT_REPORT.md`, and PDF report disclaimers.
2. **"How do you prevent fake or misleading safety claims?"**  
   *Answer:* Missing elevations stay `NULL` and block `Elevation-based` runs; unknown drainage capacity equals `0`; unflooded cells read `"No surface flooding"` rather than `"Safe"`; road edges lacking verified depth/elevation carry `"Unknown"` exposure penalties; and What-If channels are tagged `what-if-hypothetical`.
3. **"Does changing scenarios corrupt saved Potheri data?"**  
   *Answer:* No. `ScenarioManager` clones `SimulationConfig` in memory and stores overrides inside `simulation_runs.config_json`, never mutating base `grid_cells` or `drainage_features`.
4. **"How are SQLite foreign keys and stock/shelter limits guaranteed?"**  
   *Answer:* Every connection sets `PRAGMA foreign_keys = ON;`, schema `CHECK` constraints enforce `0 <= occupied <= total` and `quantity >= 0`, stock allocations execute inside atomic `BEGIN ... COMMIT/ROLLBACK` transactions, and `DatabaseBackupManager` validates integrity before any confirmed restore (saving a pre-restore safety snapshot first).
