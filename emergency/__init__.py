"""Phase 6 Emergency Resource and Relief Management package."""

from emergency.alert_manager import AlertManager, EmergencyAlertRecord
from emergency.emergency_exports import (
    EMERGENCY_REPORT_ASSUMPTIONS,
    REPORT_REGISTRY,
    export_inventory_report,
    export_inventory_transactions_report,
    export_low_stock_report,
    export_operations_report,
    export_rescue_teams_report,
    export_resource_allocations_report,
    export_shelter_directory_report,
    export_shelter_occupancy_report,
    export_vehicles_report,
    export_volunteers_report,
)
from emergency.inventory_manager import InventoryItemRecord, InventoryManager
from emergency.inventory_transactions import InventoryTransactionRecord, InventoryTransactionService
from emergency.operation_manager import (
    DashboardOverviewStats,
    EmergencyOperationRecord,
    OperationManager,
)
from emergency.rescue_team_manager import RescueTeamManager, RescueTeamRecord
from emergency.resource_allocator import ResourceAllocationRecord, ResourceAllocator
from emergency.shelter_manager import ShelterManager, ShelterRecord
from emergency.vehicle_manager import VehicleManager, VehicleRecord
from emergency.volunteer_manager import VolunteerManager, VolunteerRecord, mask_contact_value

__all__ = [
    "AlertManager",
    "DashboardOverviewStats",
    "EMERGENCY_REPORT_ASSUMPTIONS",
    "EmergencyAlertRecord",
    "EmergencyOperationRecord",
    "InventoryItemRecord",
    "InventoryManager",
    "InventoryTransactionRecord",
    "InventoryTransactionService",
    "OperationManager",
    "REPORT_REGISTRY",
    "RescueTeamManager",
    "RescueTeamRecord",
    "ResourceAllocationRecord",
    "ResourceAllocator",
    "ShelterManager",
    "ShelterRecord",
    "VehicleManager",
    "VehicleRecord",
    "VolunteerManager",
    "VolunteerRecord",
    "export_inventory_report",
    "export_inventory_transactions_report",
    "export_low_stock_report",
    "export_operations_report",
    "export_rescue_teams_report",
    "export_resource_allocations_report",
    "export_shelter_directory_report",
    "export_shelter_occupancy_report",
    "export_vehicles_report",
    "export_volunteers_report",
    "mask_contact_value",
]
