"""
Event Mapping Configuration
Maps alert event IDs to webhook metadata based on the event catalog.
Uses event_id as the primary identifier to avoid spelling mistakes.
"""

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


# Event ID Constants - Import these in alert_checks.py
class EventIDs:
    """Event ID constants for type-safe alert creation."""
    
    # Gate Events (EVT-101 to EVT-102)
    GATE_IN_MANAWAR = "EVT-101"
    GATE_OUT_MANAWAR = "EVT-102"
    
    # Charging Events (EVT-103 to EVT-104)
    CHARGING_OVERRUN = "EVT-103"
    CHARGING_FULL_STUCK = "EVT-104"
    
    # Dwell Time Events (EVT-105 to EVT-110)
    TARE_WEIGHT_OVERRUN = "EVT-105"
    GROSS_WEIGHT_OVERRUN = "EVT-106"
    LOADING_OVERRUN = "EVT-107"
    TARPAULIN_OVERRUN = "EVT-108"
    MAHA_BORDER_DWELL = "EVT-109"
    UNLOADING_OVERRUN = "EVT-110"
    
    # Transit Events (EVT-111 to EVT-112)
    TRANSIT_BREACH_MANAWAR_JHULWANIA = "EVT-111"
    TRANSIT_BREACH_JHULWANIA_DHULE = "EVT-112"
    
    # Stop Events (EVT-113)
    UNPLANNED_STOP_OUTSIDE_GEOFENCE = "EVT-113"
    
    # Data Events (EVT-114)
    DATA_FEED_GAP = "EVT-114"
    
    # Route Deviation (EVT-115)
    ROUTE_DEVIATION = "EVT-115"
    
    # Arrival Events (EVT-201 to EVT-202)
    ARRIVAL_DABHASHI = "EVT-201"
    ARRIVAL_DHARAMPURI = "EVT-202"


class EventMapping:
    """Centralized event mapping for webhook integration."""

    # Event catalog mapping: event_id -> event details
    EVENT_CATALOG = {
        EventIDs.GATE_IN_MANAWAR: {
            "event_name": "Gate In – Manawar",
            "event_description": "Gate In (Manawar)",
            "severity": "normal",
            "alert_type": "gate_in_manawar",  # For backward compatibility
        },
        EventIDs.GATE_OUT_MANAWAR: {
            "event_name": "Gate Out – Manawar",
            "event_description": "Gate Out (Manawar)",
            "severity": "normal",
            "alert_type": "gate_out_manawar",
        },
        EventIDs.CHARGING_OVERRUN: {
            "event_name": "Charging Overrun",
            "event_description": "Charging Overrun",
            "severity": "high",
            "alert_type": "charging_overrun",
        },
        EventIDs.CHARGING_FULL_STUCK: {
            "event_name": "Charging Stuck at 100%",
            "event_description": "Charging Full Stuck (SOC=100)",
            "severity": "high",
            "alert_type": "charging_full_stuck",
        },
        EventIDs.TARE_WEIGHT_OVERRUN: {
            "event_name": "Tare Weight Dwell Overrun",
            "event_description": "Tare Weight Dwell Overrun",
            "severity": "high",
            "alert_type": "tare_weight_overrun",
        },
        EventIDs.GROSS_WEIGHT_OVERRUN: {
            "event_name": "Gross Weight Dwell Overrun",
            "event_description": "Gross Weight Dwell Overrun",
            "severity": "medium",
            "alert_type": "gross_weight_overrun",
        },
        EventIDs.LOADING_OVERRUN: {
            "event_name": "Loading Dwell Overrun",
            "event_description": "Loading Dwell Overrun",
            "severity": "high",
            "alert_type": "loading_overrun",
        },
        EventIDs.TARPAULIN_OVERRUN: {
            "event_name": "Tarpaulin Dwell Overrun",
            "event_description": "Tarpaulin Dwell Overrun",
            "severity": "high",
            "alert_type": "tarpaulin_overrun",
        },
        EventIDs.MAHA_BORDER_DWELL: {
            "event_name": "Maharastra Border Dwell Overrun",
            "event_description": "Maharastra Border Dwell Overrun",
            "severity": "high",
            "alert_type": "maha_border_dwell",
        },
        EventIDs.UNLOADING_OVERRUN: {
            "event_name": "Unloading Dwell Overrun",
            "event_description": "Unloading Dwell Overrun",
            "severity": "high",
            "alert_type": "unloading_overrun",
        },
        EventIDs.TRANSIT_BREACH_MANAWAR_JHULWANIA: {
            "event_name": "Transit Breach: Manawar → Jhulwania",
            "event_description": "Transit Breach Manawar → Jhulwania",
            "severity": "high",
            "alert_type": "transit_breach_manawar_jhulwania",
        },
        EventIDs.TRANSIT_BREACH_JHULWANIA_DHULE: {
            "event_name": "Transit Breach: Jhulwania → Dhule",
            "event_description": "Transit Breach Jhulwania → Dhule",
            "severity": "high",
            "alert_type": "transit_breach_jhulwania_dhule",
        },
        EventIDs.UNPLANNED_STOP_OUTSIDE_GEOFENCE: {
            "event_name": "Unplanned Stop Outside Geofence",
            "event_description": "Unplanned Stop Outside Geofence",
            "severity": "high",
            "alert_type": "unplanned_stop_outside_geofence",
        },
        EventIDs.DATA_FEED_GAP: {
            "event_name": "Data Feed Gap",
            "event_description": "Data Feed Gap",
            "severity": "medium",
            "alert_type": "data_feed_gap",
        },
        EventIDs.ROUTE_DEVIATION: {
            "event_name": "Route Deviation",
            "event_description": "Vehicle deviated from ideal corridor",
            "severity": "high",
            "alert_type": "route_deviation",
        },
        EventIDs.ARRIVAL_DABHASHI: {
            "event_name": "Arrival – Dabhashi",
            "event_description": "Arrival at Dabhashi",
            "severity": "normal",
            "alert_type": "arrival_dabhashi",
        },
        EventIDs.ARRIVAL_DHARAMPURI: {
            "event_name": "Arrival – Dharampuri",
            "event_description": "Arrival at Dharampuri",
            "severity": "normal",
            "alert_type": "arrival_dharampuri",
        },
    }

    # Fallback for unmapped event IDs - uses DATA_FEED_GAP as default
    # This indicates a data/system issue if an unmapped event occurs
    DEFAULT_EVENT_ID = "EVT-114"  # DATA_FEED_GAP

    @classmethod
    def get_event_metadata(cls, event_id: str) -> Dict[str, str]:
        """
        Get event metadata for a given event ID.

        Args:
            event_id: The event ID string (e.g., "EVT-101")

        Returns:
            Dictionary containing event_name, event_description, severity, alert_type
        """
        if event_id in cls.EVENT_CATALOG:
            # Known event - return its metadata with original event_id
            event_data = cls.EVENT_CATALOG[event_id].copy()
            return {**event_data, "event_id": event_id}
        else:
            # Unmapped event - return DATA_FEED_GAP (EVT-114) as fallback
            # This indicates a data/system issue
            logger.error(
                f"CRITICAL: Unmapped event_id '{event_id}' detected! "
                f"Falling back to DATA_FEED_GAP (EVT-114). "
                f"Please add this event to EVENT_CATALOG immediately."
            )
            # Return DATA_FEED_GAP metadata
            fallback_data = cls.EVENT_CATALOG[cls.DEFAULT_EVENT_ID].copy()
            return {**fallback_data, "event_id": cls.DEFAULT_EVENT_ID}

    @classmethod
    def is_mapped(cls, event_id: str) -> bool:
        """Check if an event ID is mapped."""
        return event_id in cls.EVENT_CATALOG

    @classmethod
    def get_all_event_ids(cls) -> list:
        """Get list of all event IDs."""
        return list(cls.EVENT_CATALOG.keys())

    @classmethod
    def get_alert_type_from_event_id(cls, event_id: str) -> str:
        """
        Get alert_type string from event_id (for backward compatibility).
        
        Args:
            event_id: The event ID (e.g., "EVT-101")
            
        Returns:
            Alert type string (e.g., "gate_in_manawar")
        """
        if event_id in cls.EVENT_CATALOG:
            return cls.EVENT_CATALOG[event_id].get("alert_type", "data_feed_gap")
        else:
            logger.warning(f"get_alert_type_from_event_id: Unmapped event_id '{event_id}', returning 'data_feed_gap'")
            return "data_feed_gap"
    
    @classmethod
    def get_event_id_from_alert_type(cls, alert_type: str) -> str:
        """
        Get event_id from alert_type string (for backward compatibility).
        
        Args:
            alert_type: The alert type string (e.g., "gate_in_manawar")
            
        Returns:
            Event ID string (e.g., "EVT-101")
        """
        for event_id, event_data in cls.EVENT_CATALOG.items():
            if event_data.get("alert_type") == alert_type:
                return event_id
        # Unmapped alert_type - return DATA_FEED_GAP as fallback
        logger.warning(f"get_event_id_from_alert_type: Unmapped alert_type '{alert_type}', returning EVT-114 (DATA_FEED_GAP)")
        return cls.DEFAULT_EVENT_ID
