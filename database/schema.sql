-- CHENNAI FLOODGUARD SQLite Schema (Version 2)
-- Foreign keys must be enabled per connection via PRAGMA foreign_keys = ON.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS neighbourhoods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    district TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT '',
    country TEXT NOT NULL DEFAULT '',
    center_latitude REAL NOT NULL,
    center_longitude REAL NOT NULL,
    min_latitude REAL NOT NULL,
    max_latitude REAL NOT NULL,
    min_longitude REAL NOT NULL,
    max_longitude REAL NOT NULL,
    grid_rows INTEGER NOT NULL DEFAULT 10,
    grid_cols INTEGER NOT NULL DEFAULT 10,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS grid_cells (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    neighbourhood_id INTEGER NOT NULL,
    row_number INTEGER NOT NULL,
    column_number INTEGER NOT NULL,
    min_latitude REAL NOT NULL,
    max_latitude REAL NOT NULL,
    min_longitude REAL NOT NULL,
    max_longitude REAL NOT NULL,
    center_latitude REAL,
    center_longitude REAL,
    approx_width_m REAL,
    approx_height_m REAL,
    approx_area_m2 REAL,
    elevation_m REAL,
    elevation_source TEXT,
    min_elevation_m REAL,
    max_elevation_m REAL,
    mean_elevation_m REAL,
    land_use TEXT NOT NULL DEFAULT 'Unknown',
    land_use_source TEXT NOT NULL DEFAULT 'missing',
    infiltration_rate REAL NOT NULL DEFAULT 0.0,
    infiltration_source TEXT NOT NULL DEFAULT 'missing',
    drainage_capacity REAL NOT NULL DEFAULT 0.0,
    drainage_source TEXT NOT NULL DEFAULT 'missing',
    notes TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    FOREIGN KEY (neighbourhood_id) REFERENCES neighbourhoods(id) ON DELETE CASCADE,
    UNIQUE (neighbourhood_id, row_number, column_number)
);

CREATE TABLE IF NOT EXISTS osm_features (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    neighbourhood_id INTEGER NOT NULL,
    osm_id INTEGER NOT NULL,
    element_type TEXT NOT NULL,
    category TEXT NOT NULL,
    subcategory TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL DEFAULT '',
    geometry_json TEXT NOT NULL,
    tags_json TEXT NOT NULL DEFAULT '{}',
    source TEXT NOT NULL DEFAULT 'OpenStreetMap',
    imported_at TEXT NOT NULL,
    length_m REAL NOT NULL DEFAULT 0.0,
    road_category TEXT NOT NULL DEFAULT '',
    building_category TEXT NOT NULL DEFAULT '',
    user_notes TEXT NOT NULL DEFAULT '',
    is_user_edited INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (neighbourhood_id) REFERENCES neighbourhoods(id) ON DELETE CASCADE,
    UNIQUE (neighbourhood_id, element_type, osm_id)
);

CREATE TABLE IF NOT EXISTS weather_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    neighbourhood_id INTEGER NOT NULL,
    temperature REAL,
    humidity REAL,
    precipitation REAL,
    rainfall REAL,
    weather_code INTEGER,
    data_type TEXT NOT NULL,
    source TEXT NOT NULL,
    observed_at TEXT,
    retrieved_at TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    FOREIGN KEY (neighbourhood_id) REFERENCES neighbourhoods(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS scenarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    neighbourhood_id INTEGER NOT NULL,
    scenario_name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY (neighbourhood_id) REFERENCES neighbourhoods(id) ON DELETE CASCADE,
    UNIQUE (neighbourhood_id, scenario_name)
);

CREATE TABLE IF NOT EXISTS app_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    setting_key TEXT NOT NULL UNIQUE,
    setting_value TEXT
);

-- =============================================================================
-- Phase 2 Extensions: Drainage, Feature-to-Grid Links, Elevation & History
-- =============================================================================

CREATE TABLE IF NOT EXISTS drainage_features (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    neighbourhood_id INTEGER NOT NULL,
    grid_cell_id INTEGER,
    name TEXT NOT NULL,
    feature_type TEXT NOT NULL,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    capacity REAL,
    capacity_unit TEXT NOT NULL DEFAULT 'L/s',
    status TEXT NOT NULL DEFAULT 'Unknown',
    source TEXT NOT NULL DEFAULT 'user-entered',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (neighbourhood_id) REFERENCES neighbourhoods(id) ON DELETE CASCADE,
    FOREIGN KEY (grid_cell_id) REFERENCES grid_cells(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS grid_feature_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    grid_cell_id INTEGER NOT NULL,
    osm_feature_id INTEGER,
    drainage_feature_id INTEGER,
    relationship_type TEXT NOT NULL DEFAULT 'intersects',
    created_at TEXT NOT NULL,
    FOREIGN KEY (grid_cell_id) REFERENCES grid_cells(id) ON DELETE CASCADE,
    FOREIGN KEY (osm_feature_id) REFERENCES osm_features(id) ON DELETE CASCADE,
    FOREIGN KEY (drainage_feature_id) REFERENCES drainage_features(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS elevation_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    neighbourhood_id INTEGER NOT NULL,
    source_name TEXT NOT NULL,
    file_name TEXT NOT NULL,
    coordinate_reference_system TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    source_description TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (neighbourhood_id) REFERENCES neighbourhoods(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS land_use_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    grid_cell_id INTEGER NOT NULL,
    previous_category TEXT NOT NULL,
    new_category TEXT NOT NULL,
    source TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (grid_cell_id) REFERENCES grid_cells(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_grid_cells_neighbourhood
    ON grid_cells(neighbourhood_id);

CREATE INDEX IF NOT EXISTS idx_osm_features_neighbourhood_cat
    ON osm_features(neighbourhood_id, category);

CREATE INDEX IF NOT EXISTS idx_weather_neighbourhood_retrieved
    ON weather_observations(neighbourhood_id, retrieved_at DESC);

CREATE INDEX IF NOT EXISTS idx_drainage_neighbourhood
    ON drainage_features(neighbourhood_id);

CREATE INDEX IF NOT EXISTS idx_grid_links_cell
    ON grid_feature_links(grid_cell_id);

CREATE INDEX IF NOT EXISTS idx_grid_links_osm
    ON grid_feature_links(osm_feature_id);

CREATE INDEX IF NOT EXISTS idx_grid_links_drainage
    ON grid_feature_links(drainage_feature_id);

CREATE INDEX IF NOT EXISTS idx_elevation_sources_neighbourhood
    ON elevation_sources(neighbourhood_id);

CREATE INDEX IF NOT EXISTS idx_land_use_history_cell
    ON land_use_history(grid_cell_id, updated_at DESC);

-- =============================================================================
-- Phase 3 Extensions: Flood Simulation Runs, Step Results & Metrics
-- =============================================================================

CREATE TABLE IF NOT EXISTS simulation_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    neighbourhood_id INTEGER NOT NULL,
    scenario_name TEXT NOT NULL,
    rainfall_intensity REAL NOT NULL,
    rainfall_duration REAL NOT NULL,
    time_step REAL NOT NULL,
    simulation_mode TEXT NOT NULL,
    distribution_pattern TEXT NOT NULL DEFAULT 'constant',
    initial_water_depth REAL NOT NULL DEFAULT 0.0,
    config_json TEXT NOT NULL DEFAULT '{}',
    start_time TEXT NOT NULL,
    completion_time TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    model_version TEXT NOT NULL,
    FOREIGN KEY (neighbourhood_id) REFERENCES neighbourhoods(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS simulation_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    simulation_id INTEGER NOT NULL,
    timestep INTEGER NOT NULL,
    sim_time_minutes REAL NOT NULL DEFAULT 0.0,
    cell_id INTEGER NOT NULL,
    water_depth REAL NOT NULL,
    water_volume REAL NOT NULL,
    rainfall_input REAL NOT NULL,
    infiltration_loss REAL NOT NULL,
    drainage_loss REAL NOT NULL,
    flow_transferred REAL NOT NULL DEFAULT 0.0,
    FOREIGN KEY (simulation_id) REFERENCES simulation_runs(id) ON DELETE CASCADE,
    FOREIGN KEY (cell_id) REFERENCES grid_cells(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS simulation_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    simulation_id INTEGER NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value REAL NOT NULL,
    unit TEXT NOT NULL,
    FOREIGN KEY (simulation_id) REFERENCES simulation_runs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sim_runs_neighbourhood
    ON simulation_runs(neighbourhood_id, id DESC);

CREATE INDEX IF NOT EXISTS idx_sim_results_sim_step
    ON simulation_results(simulation_id, timestep, cell_id);

CREATE INDEX IF NOT EXISTS idx_sim_metrics_sim
    ON simulation_metrics(simulation_id);

-- =============================================================================
-- Phase 5 Extensions: SafeRoute Road Graph, Road Conditions & Route History
-- =============================================================================

CREATE TABLE IF NOT EXISTS road_network_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    neighbourhood_id INTEGER NOT NULL,
    osm_id INTEGER,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'OpenStreetMap',
    FOREIGN KEY (neighbourhood_id) REFERENCES neighbourhoods(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS road_network_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    neighbourhood_id INTEGER NOT NULL,
    osm_feature_id INTEGER,
    edge_key TEXT NOT NULL DEFAULT '',
    start_node_id INTEGER NOT NULL,
    end_node_id INTEGER NOT NULL,
    road_name TEXT NOT NULL DEFAULT '',
    road_type TEXT NOT NULL DEFAULT 'Residential',
    distance_m REAL NOT NULL,
    geometry TEXT NOT NULL,
    grid_cell_ids_json TEXT NOT NULL DEFAULT '[]',
    source TEXT NOT NULL DEFAULT 'OpenStreetMap',
    FOREIGN KEY (neighbourhood_id) REFERENCES neighbourhoods(id) ON DELETE CASCADE,
    FOREIGN KEY (osm_feature_id) REFERENCES osm_features(id) ON DELETE SET NULL,
    FOREIGN KEY (start_node_id) REFERENCES road_network_nodes(id) ON DELETE CASCADE,
    FOREIGN KEY (end_node_id) REFERENCES road_network_nodes(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS road_conditions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    neighbourhood_id INTEGER NOT NULL,
    road_edge_id INTEGER NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'Normal',
    exposure_category TEXT NOT NULL DEFAULT 'Unknown',
    maximum_water_depth REAL,
    simulation_id INTEGER,
    time_step INTEGER,
    status_source TEXT NOT NULL DEFAULT 'unknown',
    notes TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    FOREIGN KEY (neighbourhood_id) REFERENCES neighbourhoods(id) ON DELETE CASCADE,
    FOREIGN KEY (road_edge_id) REFERENCES road_network_edges(id) ON DELETE CASCADE,
    FOREIGN KEY (simulation_id) REFERENCES simulation_runs(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS route_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    neighbourhood_id INTEGER NOT NULL,
    origin TEXT NOT NULL,
    destination TEXT NOT NULL,
    origin_node_id INTEGER,
    dest_node_id INTEGER,
    travel_mode TEXT NOT NULL,
    route_type TEXT NOT NULL,
    total_distance REAL NOT NULL,
    estimated_time REAL NOT NULL,
    simulation_id INTEGER,
    time_step INTEGER,
    summary_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (neighbourhood_id) REFERENCES neighbourhoods(id) ON DELETE CASCADE,
    FOREIGN KEY (simulation_id) REFERENCES simulation_runs(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_road_nodes_neighbourhood
    ON road_network_nodes(neighbourhood_id);

CREATE INDEX IF NOT EXISTS idx_road_edges_neighbourhood
    ON road_network_edges(neighbourhood_id);

CREATE INDEX IF NOT EXISTS idx_road_conditions_neighbourhood
    ON road_conditions(neighbourhood_id);

CREATE INDEX IF NOT EXISTS idx_route_history_neighbourhood
    ON route_history(neighbourhood_id, id DESC);

-- =============================================================================
-- Phase 6 Extensions: Emergency Resource & Relief Management System
-- =============================================================================

CREATE TABLE IF NOT EXISTS shelters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    neighbourhood_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    address TEXT NOT NULL DEFAULT '',
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    total_capacity INTEGER NOT NULL CHECK (total_capacity >= 0),
    occupied_capacity INTEGER NOT NULL DEFAULT 0 CHECK (occupied_capacity >= 0 AND occupied_capacity <= total_capacity),
    contact_info TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'Active',
    facilities TEXT NOT NULL DEFAULT '[]',
    accessibility TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'user-entered',
    is_verified INTEGER NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (neighbourhood_id) REFERENCES neighbourhoods(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS rescue_teams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    neighbourhood_id INTEGER NOT NULL,
    team_name TEXT NOT NULL,
    leader TEXT NOT NULL DEFAULT '',
    members_json TEXT NOT NULL DEFAULT '[]',
    contact TEXT NOT NULL DEFAULT '',
    skills TEXT NOT NULL DEFAULT '',
    equipment TEXT NOT NULL DEFAULT '',
    current_location TEXT NOT NULL DEFAULT '',
    availability TEXT NOT NULL DEFAULT 'Available',
    current_assignment TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (neighbourhood_id) REFERENCES neighbourhoods(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS vehicles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    neighbourhood_id INTEGER NOT NULL,
    registration_number TEXT NOT NULL,
    vehicle_type TEXT NOT NULL,
    capacity INTEGER NOT NULL DEFAULT 0 CHECK (capacity >= 0),
    fuel_status TEXT NOT NULL DEFAULT 'Unknown',
    operational_status TEXT NOT NULL DEFAULT 'Available',
    assigned_team_id INTEGER,
    location TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (neighbourhood_id) REFERENCES neighbourhoods(id) ON DELETE CASCADE,
    FOREIGN KEY (assigned_team_id) REFERENCES rescue_teams(id) ON DELETE SET NULL,
    UNIQUE (neighbourhood_id, registration_number)
);

CREATE TABLE IF NOT EXISTS emergency_operations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    neighbourhood_id INTEGER NOT NULL,
    operation_name TEXT NOT NULL,
    operation_type TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'Medium',
    start_location TEXT NOT NULL DEFAULT '',
    destination TEXT NOT NULL DEFAULT '',
    destination_shelter_id INTEGER,
    assigned_team_id INTEGER,
    assigned_vehicle_id INTEGER,
    status TEXT NOT NULL DEFAULT 'Planned',
    start_time TEXT NOT NULL DEFAULT '',
    completion_time TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (neighbourhood_id) REFERENCES neighbourhoods(id) ON DELETE CASCADE,
    FOREIGN KEY (destination_shelter_id) REFERENCES shelters(id) ON DELETE SET NULL,
    FOREIGN KEY (assigned_team_id) REFERENCES rescue_teams(id) ON DELETE SET NULL,
    FOREIGN KEY (assigned_vehicle_id) REFERENCES vehicles(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS volunteers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    neighbourhood_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    contact TEXT NOT NULL DEFAULT '',
    emergency_contact TEXT NOT NULL DEFAULT '',
    skills TEXT NOT NULL DEFAULT '',
    availability TEXT NOT NULL DEFAULT 'Available',
    preferred_area TEXT NOT NULL DEFAULT '',
    assigned_operation_id INTEGER,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (neighbourhood_id) REFERENCES neighbourhoods(id) ON DELETE CASCADE,
    FOREIGN KEY (assigned_operation_id) REFERENCES emergency_operations(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS inventory_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    neighbourhood_id INTEGER NOT NULL,
    item_name TEXT NOT NULL,
    category TEXT NOT NULL,
    quantity REAL NOT NULL DEFAULT 0.0 CHECK (quantity >= 0.0),
    unit TEXT NOT NULL,
    minimum_stock REAL NOT NULL DEFAULT 0.0 CHECK (minimum_stock >= 0.0),
    storage_location TEXT NOT NULL DEFAULT '',
    expiry_date TEXT NOT NULL DEFAULT '',
    supplier TEXT NOT NULL DEFAULT '',
    verification_status TEXT NOT NULL DEFAULT 'Registered (Unverified)',
    last_verified_at TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    FOREIGN KEY (neighbourhood_id) REFERENCES neighbourhoods(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS inventory_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    neighbourhood_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    transaction_type TEXT NOT NULL,
    quantity REAL NOT NULL CHECK (quantity >= 0.0),
    source_location TEXT NOT NULL DEFAULT '',
    destination_location TEXT NOT NULL DEFAULT '',
    operator TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    related_operation_id INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY (neighbourhood_id) REFERENCES neighbourhoods(id) ON DELETE CASCADE,
    FOREIGN KEY (item_id) REFERENCES inventory_items(id) ON DELETE CASCADE,
    FOREIGN KEY (related_operation_id) REFERENCES emergency_operations(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS resource_allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    neighbourhood_id INTEGER NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id INTEGER NOT NULL,
    destination_type TEXT NOT NULL DEFAULT '',
    destination_id INTEGER,
    destination_label TEXT NOT NULL DEFAULT '',
    quantity REAL NOT NULL DEFAULT 1.0 CHECK (quantity > 0.0),
    operation_id INTEGER,
    status TEXT NOT NULL DEFAULT 'Allocated',
    reason TEXT NOT NULL DEFAULT '',
    operator TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (neighbourhood_id) REFERENCES neighbourhoods(id) ON DELETE CASCADE,
    FOREIGN KEY (operation_id) REFERENCES emergency_operations(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS emergency_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    neighbourhood_id INTEGER NOT NULL,
    alert_key TEXT NOT NULL DEFAULT '',
    alert_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    related_resource TEXT NOT NULL DEFAULT '',
    acknowledged INTEGER NOT NULL DEFAULT 0,
    acknowledged_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY (neighbourhood_id) REFERENCES neighbourhoods(id) ON DELETE CASCADE,
    UNIQUE (neighbourhood_id, alert_key)
);

CREATE INDEX IF NOT EXISTS idx_shelters_neighbourhood
    ON shelters(neighbourhood_id, status);

CREATE INDEX IF NOT EXISTS idx_rescue_teams_neighbourhood
    ON rescue_teams(neighbourhood_id, availability);

CREATE INDEX IF NOT EXISTS idx_vehicles_neighbourhood
    ON vehicles(neighbourhood_id, operational_status);

CREATE INDEX IF NOT EXISTS idx_volunteers_neighbourhood
    ON volunteers(neighbourhood_id, availability);

CREATE INDEX IF NOT EXISTS idx_inventory_items_neighbourhood
    ON inventory_items(neighbourhood_id, category);

CREATE INDEX IF NOT EXISTS idx_inventory_tx_item
    ON inventory_transactions(item_id, id DESC);

CREATE INDEX IF NOT EXISTS idx_inventory_tx_neighbourhood
    ON inventory_transactions(neighbourhood_id, id DESC);

CREATE INDEX IF NOT EXISTS idx_allocations_neighbourhood
    ON resource_allocations(neighbourhood_id, id DESC);

CREATE INDEX IF NOT EXISTS idx_operations_neighbourhood
    ON emergency_operations(neighbourhood_id, status);

CREATE INDEX IF NOT EXISTS idx_alerts_neighbourhood
    ON emergency_alerts(neighbourhood_id, acknowledged, severity);
