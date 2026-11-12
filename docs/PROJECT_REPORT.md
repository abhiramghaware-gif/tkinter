# CHENNAI FLOODGUARD — Academic Final-Year Project Report Draft

**Project Title:** CHENNAI FLOODGUARD: A Hybrid Offline-First Urban Flood Simulation, Flood-Aware Evacuation Routing & Emergency Resource Decision-Support Prototype  
**Pilot Neighbourhood:** Potheri, Chengalpattu District, Chennai Metropolitan Corridor, Tamil Nadu, India  
**Platform & Stack:** Python 3, Tkinter Desktop GUI, SQLite 3 (`v5`), NumPy, Matplotlib, NetworkX, Pillow, Requests (with optional Shapely, Rasterio, PyProj)

---

## 1. Abstract

Urban flash waterlogging across rapidly urbanizing corridors in Chennai poses recurring hazards to commuters, students, and emergency responders. Existing flood-modelling tools are frequently either inaccessible black-box commercial suites or fragmented command-line utilities that do not link terrain runoff to passable evacuation corridors and relief logistics. **CHENNAI FLOODGUARD** addresses this gap by implementing a modular, offline-first Python Tkinter desktop prototype demonstrated on **Potheri**. Across seven incremental engineering phases, the system integrates dynamic OpenStreetMap geographical extraction, GeoTIFF terrain and land-use modelling on a `10 × 10` spherical grid, an SI-consistent cellular water-balance flood simulator (`mass error <= 1e-6 m³`), configurable depth heatmap and animation tools, a NetworkX Dijkstra evacuation router (**SafeRoute**), a transactional SQLite emergency relief resource console, a non-destructive **What-If Experiment Lab**, a **12-Report PDF/CSV Analytics Engine**, and automated SQLite integrity audit, backup, and confirmed restore tooling. Strict provenance separation ensures illustrative, hypothetical, cached, and user-entered values are never misrepresented as verified official measurements.

---

## 2. Introduction & Problem Statement

During northeast monsoon cloudbursts, neighbourhoods such as Potheri experience localized surface ponding driven by paved impervious expansion, intermittent drainage maintenance, and micro-topographical depressions. Field teams and engineering students studying disaster resilience face three connected challenges:
1. **Fragmented Data**: OpenStreetMap road networks, elevation grids, weather observations, and local relief inventories typically reside in incompatible formats.
2. **Opaque Risk Translation**: Raw rainfall figures (`mm/hr`) or single depth grids do not automatically identify which roads become risky or which emergency shelters remain reachable.
3. **Connectivity Fragility**: Severe weather degrades internet access, making cloud-only GIS dashboards unreliable during drills or localized outages.

CHENNAI FLOODGUARD solves these problems through a unified **SQLite-backed offline-first architecture** that couples physics, routing, and emergency logistics while maintaining transparent scientific assumptions.

---

## 3. Objectives

1. Construct an editable neighbourhood GIS workspace grounded in real OpenStreetMap geometry (`Potheri`) with a structured `10 × 10` spatial grid and data provenance tracking.
2. Formulate an SI-unit cellular water-balance model quantifying rainfall volume, land-use infiltration, operational drainage removal, and head-driven surface transfer with strict mass conservation.
3. Visualize flood depth evolution and configurable prototype risk levels overlaid onto streets, buildings, and candidate landmarks without altering source GIS geometry.
4. Compute and compare **Shortest**, **Flood-Aware**, and **Alternative** evacuation routes over a topological NetworkX road graph while respecting manual road closures and penalizing uncertain `"Unknown"` exposure segments.
5. Manage emergency shelters, rescue teams, vehicles, privacy-masked volunteers, inventory ledgers, atomic allocations, and rule-driven alerts strictly from SQLite records.
6. Enable non-destructive **What-If** scenario cloning, 6 pre-built stress/mitigation experiments, multi-scenario delta comparisons, 12 automated PDF/CSV reports, and Windows standalone `.exe` packaging readiness.

---

## 4. Literature & Existing System Context

| System Category | Representative Approach | Gaps Addressed by CHENNAI FLOODGUARD |
| :--- | :--- | :--- |
| Commercial 1D/2D Hydraulic Suites | Full shallow-water solvers (HEC-RAS, MIKE, SWMM) | Steep learning curve; rarely bundled with interactive local shelter inventory or Tkinter what-if labs |
| Consumer Map Navigation | Live traffic shortest-path web apps | Cloud-dependent; unaware of hypothetical neighbourhood drainage failures or unverified depth exposure |
| Academic Spreadsheet Calculators | Static rational-method runoff tables | No spatial `10 × 10` cell redistribution, road-network Dijkstra coupling, or visual playback |

CHENNAI FLOODGUARD occupies an **educational and pre-event planning niche**: transparent cellular water-balance equations paired directly with graph routing and relief inventory accounting in an inspectable open Python codebase.

---

## 5. System Architecture & Modular Package Design

The codebase follows strict separation of concerns (`MVC` / service-repository layering):
- **`core/` (Pure Domain & Physics Engine)**: Stateless physics calculators (`rainfall_model`, `infiltration_model`, `runoff_model`, `drainage_model`, `water_flow_model`), orchestration (`simulation_engine`), risk/statistics (`risk_classifier`, `flood_statistics`), and What-If analytics (`scenario_manager`, `scenario_comparator`). Contains **zero Tkinter imports**.
- **`database/` (Persistence & Reliability Layer)**: `DatabaseManager` enforces `PRAGMA foreign_keys = ON` and executes idempotent schema migrations `v1 -> v5`. `FloodGuardRepository` encapsulates structured queries, while `DatabaseBackupManager` executes `PRAGMA integrity_check`, `PRAGMA foreign_key_check`, online `sqlite3.Connection.backup()`, SHA-256 verification, and confirmed pre-backup restores.
- **`routing/` (SafeRoute Graph Engine)**: Splits OSM ways at shared geometric vertices into `NetworkX MultiGraph` edges, evaluates cell-intersecting depth exposure, and executes Dijkstra shortest-cost searches with configurable penalties and travel-speed models.
- **`emergency/` (Transactional Logistics Layer)**: Managers for shelters, teams, vehicles, volunteers, inventory + atomic ledger transactions, multi-resource allocations with rollback, operations lifecycle, and rule-based alert evaluation.
- **`services/` (External I/O, GIS & Reports)**: Nominatim, Overpass, optional Open-Meteo, GeoTIFF DEM zonal statistics, GeoJSON/CSV interchange, `WorkspaceManager`, and unified 12-type PDF/CSV `ReportGenerator`.
- **`visualization/` & `gui/` (Tkinter Presentation Layer)**: DPI-aware dark-navy/teal interface featuring non-blocking `threading` + `after()` execution for network requests, simulations, route computation, What-If batches, and PDF exports so the UI never freezes.

---

## 6. Database Schema Design (`SQLite v5`)

The schema (`database/schema.sql`) comprises **27 normalized tables** with cascading foreign keys and covering indexes:
- **Workspace & GIS (11 tables)**: `schema_migrations`, `neighbourhoods`, `grid_cells` (unique `(neighbourhood_id, row_number, column_number)`), `osm_features`, `weather_observations`, `scenarios`, `app_settings`, `drainage_features`, `grid_feature_links`, `elevation_sources`, `land_use_history`.
- **Simulation (3 tables)**: `simulation_runs` (storing full `config_json` for reproducibility), `simulation_results` (per-step per-cell depth, volume, rainfall, infiltration, drainage, transfer), `simulation_metrics` (mass balance & headline KPIs).
- **SafeRoute (4 tables)**: `road_network_nodes`, `road_network_edges`, `road_conditions` (`Normal`, `Closed`, `Blocked`, `Under inspection`), `route_history`.
- **Emergency Operations (9 tables)**: `shelters` (`CHECK (occupied_capacity >= 0 AND occupied_capacity <= total_capacity)`), `rescue_teams`, `vehicles`, `emergency_operations`, `volunteers`, `inventory_items` (`CHECK (quantity >= 0.0)`), `inventory_transactions`, `resource_allocations`, `emergency_alerts` (deduplicated `(neighbourhood_id, alert_key)`).

---

## 7. Flood Simulation Methodology (SI Water Balance)

Each simulation executes over discrete time steps $\Delta t$ (`s`) across $N$ spherical grid cells of area $A_i$ (`m²`):
1. **Rainfall Addition**: Intensity $I_k$ (`mm/hr`) yields step volume $V_{\text{rain},i,k} = \frac{I_k \cdot (\Delta t/3600)}{1000} A_i$.
2. **Water-Limited Infiltration**: Potential soil absorption from cell infiltration rate $f_i$ (`mm/hr`) is capped by available surface storage $V_i$: $V_{\text{inf},i,k} = \min(V_i, V_{\text{inf,pot},i,k})$.
3. **Drainage Extraction**: Operational capacity $Q_{\text{eff},i}$ (`m³/s`) sums active point features scaled by operational factor (`Operational=1.0`, `Partially blocked=0.5`, `Blocked/Unknown=0.0`, `NULL capacity = 0`) and What-If scaling/disabling overrides: $V_{\text{dr},i,k} = \min(V_i, Q_{\text{eff},i}\Delta t)$.
4. **4-Connected Downhill Surface Transfer**: Hydraulic head $H_i = E_i + d_i$ drives conservative sub-stepped flux strictly toward lower-head orthogonal neighbours, scaling cell outflows proportionally when demand exceeds $V_i$ and enforcing closed domain boundaries.
5. **Mass Balance Verification**: At completion, residual error $\varepsilon = |(V_{\text{init}} + \sum V_{\text{rain}}) - (V_{\text{final}} + \sum V_{\text{infil}} + \sum V_{\text{drain}})|$ is checked against `1e-6 m³` and persisted.

---

## 8. Evacuation Routing & Emergency Logistics

- **Exposure-Weighted Dijkstra**: Flood exposure along each road edge takes the worst intersecting grid-cell depth at the chosen timestep (`Low <=10 cm`, `Moderate <=30 cm`, `High <=60 cm`, `Very high >60 cm`, or `Unknown` when unlinked/lacking elevation). **Shortest** minimizes geodesic distance over open roads; **Flood-Aware** minimizes $\text{distance} + \text{exposure\_penalty} + \text{unknown\_penalty}$; **Alternative** penalizes edges already used by the Shortest path to surface genuinely distinct detours.
- **Transactional Emergency Logistics**: Shelter edits enforce `occupied <= total`; stock deductions run inside SQLite `BEGIN ... COMMIT/ROLLBACK` transactions logging every delta in `inventory_transactions`; multi-resource allocations cleanly reverse deducted quantities/assignments if cancelled or returned; and volunteer contact fields are masked (`******XXXX`) in tables and redacted from map overlays and public CSV/PDF exports.

---

## 9. What-If Experiment Lab & 12-Report Engine

- **What-If Lab (`core/scenario_manager.py`, `core/scenario_comparator.py`)**: Clones saved simulation configurations non-destructively in memory (preserving saved grid/drainage tables), runs single custom variants or 6 structured batch experiments (Heavy Rainfall, Drainage Failure, Hypothetical Relief Channel, Land-Use Change, Road Closure Impact, Combined Stress-Test), computes percentage changes safely (reporting `"N/A (baseline=0)"` rather than dividing by zero), flags incompatible run durations/modes, and visualizes dual heatmaps alongside multi-run comparison bar charts.
- **Automated Report Engine (`services/report_generator.py`)**: Generates all **12 reports** (`neighbourhood_profile`, `geographical_data`, `weather_data`, `flood_simulation`, `flood_risk_analysis`, `scenario_comparison`, `saferoute_analysis`, `shelter_capacity`, `emergency_resource`, `inventory`, `emergency_operations`, `complete_project`) in both **PDF** (Matplotlib `PdfPages` with Section 8 4-figure technical simulation layouts) and **CSV**.

---

## 10. Verification & Testing Results

Automated verification in `tests/` runs completely offline using temporary SQLite databases, GeoJSON/GeoTIFF/Overpass/Nominatim/Open-Meteo fixtures, and headless/live Tkinter smoke instantiations:
- **Unit & Module Suites (Phases 1–6)**: Schema migrations `v1->v5`, coordinate/bbox bounds, spherical areas, DEM GeoTIFF parsing, water-balance SI math & zero-rain edge case, mass-conservation invariant, exposure/closure routing, capacity/stock invariants, volunteer redaction, atomic allocation rollback, and view smoke tests.
- **Phase 7 Integration Suite (`tests/test_phase7.py`)**: Verifies all 6 What-If experiments & non-destruction, comparator division-by-zero & compatibility warnings, DB audit + backup + corrupt-file rejection + unconfirmed restore rejection + confirmed restore with safety backup, all 12 PDF (`%PDF-`) & CSV outputs, and full offline `FloodGuardApp` navigation across every screen.

---

## 11. Ethical Guardrails & Known Limitations

- **Zero Fabricated Observations**: Unset elevations stay `NULL`, unknown drainage capacities contribute `0 m³/s`, `"No surface flooding"` never says `"Safe"`, `"Unknown"` exposure roads are penalized rather than assumed clear, unverified shelters/stock carry explicit tags, and hypothetical channels are labelled `what-if-hypothetical`.
- **Scientific Limitations**: Cellular head-difference routing across a `10 × 10` grid omits momentum terms, pressurized storm sewers, infiltration soil-moisture saturation curves, and evapotranspiration; SafeRoute omits real-time traffic or one-way turn restrictions.
- **Implemented vs Planned Future Scope**: Phases 1–7 desktop prototype, SQLite `v5` schema, What-If Lab, 12 reports, DB backup/audit, and PyInstaller `.spec` packaging are implemented; 2D GPU shallow-water PDE coupling, municipal SCADA telemetry feeds, mobile/Android companion apps, and multi-user authentication remain future research scope.

---

## 12. Team Division Template (3-Member Capstone Team)

| Team Role | Primary Code Modules Owned | Key Verification Deliverables |
| :--- | :--- | :--- |
| **Member 1 — GIS, Database & Packaging Architect** | `database/`, `services/geocoding_service.py`, `services/osm_service.py`, `services/elevation_service.py`, `gui/map_editor.py`, `floodguard.spec`, `build_windows.py` | `test_database.py`, `test_geocoding.py`, `test_phase2.py`, DB Audit/Backup/Restore |
| **Member 2 — Simulation, Visualization & What-If Lead** | `core/simulation_*`, `core/*_model.py`, `core/scenario_*`, `visualization/flood_*`, `gui/simulation_lab.py`, `gui/what_if_lab.py` | `test_phase3.py`, `test_phase4.py`, Mass Conservation, 6 What-If Experiments |
| **Member 3 — SafeRoute, Emergency, Dashboard & Reports Lead** | `routing/`, `emergency/`, `services/report_generator.py`, `gui/dashboard.py`, `gui/saferoute_screen.py`, `gui/reports_screen.py` | `test_phase5.py`, `test_phase6.py`, `test_phase7.py`, All 12 PDF/CSV Reports |

---

## 13. Conclusion

CHENNAI FLOODGUARD demonstrates that a disciplined, modular Python/Tkinter architecture can unify GIS preparation, physically grounded cellular flood simulation, flood-aware evacuation routing, transactional relief inventory management, What-If planning experiments, and structured PDF/CSV reporting in a single offline-resilient desktop prototype suitable for academic demonstration and urban resilience training in Potheri, Chennai.
