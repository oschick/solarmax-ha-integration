"""Constants for the Solarmax Inverter integration."""

from homeassistant.helpers.entity import EntityCategory

DOMAIN = "solarmax"

# Configuration constants
CONF_HOST = "host"
CONF_PORT = "port"
CONF_ADDRESS = "address"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_DEVICE_NAME = "device_name"

# Default values
DEFAULT_PORT = 12345
DEFAULT_ADDRESS = 1
DEFAULT_UPDATE_INTERVAL = 30
DEFAULT_DEVICE_NAME = "Solarmax Inverter"

# Status code mappings (SYS) - maps raw integer code to option key
SYS_STATUS_MAP: dict[int, str] = {
    20000: "no_communication",
    20001: "in_operation",
    20002: "low_irradiation",
    20003: "starting_up",
    20004: "mpp_operation",
    20005: "fan_running",
    20006: "max_power_operation",
    20007: "temperature_limitation",
    20008: "grid_operation",
}

# Special SYS states (not from inverter data)
SYS_STATE_OFFLINE_NIGHT = "offline_night"
SYS_STATE_CONNECTION_FAILED = "connection_failed"
SYS_STATE_UNKNOWN = "unknown"

# All possible SYS options for the enum sensor
SYS_OPTIONS: list[str] = list(SYS_STATUS_MAP.values()) + [
    SYS_STATE_OFFLINE_NIGHT,
    SYS_STATE_CONNECTION_FAILED,
    SYS_STATE_UNKNOWN,
]

# Alarm code mappings (SAL) - bitmask values, can be combined
SAL_ALARM_MAP: dict[int, str] = {
    0: "no_error",
    1: "external_fault_1",
    2: "insulation_fault_dc",
    4: "earth_fault_current",
    8: "fuse_break_center_earth",
    16: "external_alarm_2",
    32: "long_term_temp_limit",
    64: "ac_feed_in_error",
    128: "external_alarm_4",
    256: "fan_defect",
    512: "fuse_break",
    1024: "temp_sensor_failure",
    2048: "alarm_12",
    4096: "alarm_13",
    8192: "alarm_14",
    16384: "alarm_15",
    32768: "alarm_16",
    65536: "alarm_17",
}

SAL_STATE_MULTIPLE = "multiple_alarms"
SAL_STATE_UNKNOWN = "unknown_alarm"

# All possible SAL options for the enum sensor
SAL_OPTIONS: list[str] = list(SAL_ALARM_MAP.values()) + [
    SAL_STATE_MULTIPLE,
    SAL_STATE_UNKNOWN,
]

# Sensor types and their properties
SENSOR_TYPES = {
    "PAC": {
        "name": "AC Power",
        "translation_key": "pac",
        "unit": "W",
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:solar-power",
        "entity_category": None,  # Main measurement
        "enabled_by_default": True,
    },
    "PDC": {
        "name": "DC Power",
        "translation_key": "pdc",
        "unit": "W",
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:solar-power",
        "entity_category": None,  # Main measurement
        "enabled_by_default": True,
    },
    "PD01": {
        "name": "DC Power String 1",
        "translation_key": "pd01",
        "unit": "W",
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:solar-power",
        "entity_category": EntityCategory.DIAGNOSTIC,  # Detailed diagnostic
        "enabled_by_default": False,  # Disable by default - advanced users only
    },
    "PD02": {
        "name": "DC Power String 2",
        "translation_key": "pd02",
        "unit": "W",
        "device_class": "power",
        "state_class": "measurement",
        "icon": "mdi:solar-power",
        "entity_category": EntityCategory.DIAGNOSTIC,  # Detailed diagnostic
        "enabled_by_default": False,  # Disable by default - advanced users only
    },
    "UL1": {
        "name": "AC Voltage Phase 1",
        "translation_key": "ul1",
        "unit": "V",
        "device_class": "voltage",
        "state_class": "measurement",
        "icon": "mdi:sine-wave",
        "entity_category": EntityCategory.DIAGNOSTIC,  # Detailed diagnostic
        "enabled_by_default": False,  # Disable by default - most users don't need this
    },
    "UL2": {
        "name": "AC Voltage Phase 2",
        "translation_key": "ul2",
        "unit": "V",
        "device_class": "voltage",
        "state_class": "measurement",
        "icon": "mdi:sine-wave",
        "entity_category": EntityCategory.DIAGNOSTIC,  # Detailed diagnostic
        "enabled_by_default": False,  # Disable by default - most users don't need this
    },
    "UL3": {
        "name": "AC Voltage Phase 3",
        "translation_key": "ul3",
        "unit": "V",
        "device_class": "voltage",
        "state_class": "measurement",
        "icon": "mdi:sine-wave",
        "entity_category": EntityCategory.DIAGNOSTIC,  # Detailed diagnostic
        "enabled_by_default": False,  # Disable by default - most users don't need this
    },
    "UD01": {
        "name": "DC Voltage String 1",
        "translation_key": "ud01",
        "unit": "V",
        "device_class": "voltage",
        "state_class": "measurement",
        "icon": "mdi:sine-wave",
        "entity_category": EntityCategory.DIAGNOSTIC,  # Detailed diagnostic
        "enabled_by_default": False,  # Disable by default - advanced users only
    },
    "UD02": {
        "name": "DC Voltage String 2",
        "translation_key": "ud02",
        "unit": "V",
        "device_class": "voltage",
        "state_class": "measurement",
        "icon": "mdi:sine-wave",
        "entity_category": EntityCategory.DIAGNOSTIC,  # Detailed diagnostic
        "enabled_by_default": False,  # Disable by default - advanced users only
    },
    "IL1": {
        "name": "AC Current Phase 1",
        "translation_key": "il1",
        "unit": "A",
        "device_class": "current",
        "state_class": "measurement",
        "icon": "mdi:current-ac",
        "entity_category": EntityCategory.DIAGNOSTIC,  # Detailed diagnostic
        "enabled_by_default": False,  # Disable by default - most users don't need this
    },
    "IL2": {
        "name": "AC Current Phase 2",
        "translation_key": "il2",
        "unit": "A",
        "device_class": "current",
        "state_class": "measurement",
        "icon": "mdi:current-ac",
        "entity_category": EntityCategory.DIAGNOSTIC,  # Detailed diagnostic
        "enabled_by_default": False,  # Disable by default - most users don't need this
    },
    "IL3": {
        "name": "AC Current Phase 3",
        "translation_key": "il3",
        "unit": "A",
        "device_class": "current",
        "state_class": "measurement",
        "icon": "mdi:current-ac",
        "entity_category": EntityCategory.DIAGNOSTIC,  # Detailed diagnostic
        "enabled_by_default": False,  # Disable by default - most users don't need this
    },
    "IDC": {
        "name": "DC Current",
        "translation_key": "idc",
        "unit": "A",
        "device_class": "current",
        "state_class": "measurement",
        "icon": "mdi:current-dc",
        "entity_category": EntityCategory.DIAGNOSTIC,  # Detailed diagnostic
        "enabled_by_default": False,  # Disable by default - advanced users only
    },
    "ID01": {
        "name": "DC Current String 1",
        "translation_key": "id01",
        "unit": "A",
        "device_class": "current",
        "state_class": "measurement",
        "icon": "mdi:current-dc",
        "entity_category": EntityCategory.DIAGNOSTIC,  # Detailed diagnostic
        "enabled_by_default": False,  # Disable by default - advanced users only
    },
    "ID02": {
        "name": "DC Current String 2",
        "translation_key": "id02",
        "unit": "A",
        "device_class": "current",
        "state_class": "measurement",
        "icon": "mdi:current-dc",
        "entity_category": EntityCategory.DIAGNOSTIC,  # Detailed diagnostic
        "enabled_by_default": False,  # Disable by default - advanced users only
    },
    "KDY": {
        "name": "Energy Day",
        "translation_key": "kdy",
        "unit": "kWh",
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:solar-power",
        "entity_category": None,  # Main measurement
        "enabled_by_default": True,
    },
    "KMT": {
        "name": "Energy Month",
        "translation_key": "kmt",
        "unit": "kWh",
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:solar-power",
        "entity_category": None,  # Main measurement
        "enabled_by_default": True,
    },
    "KYR": {
        "name": "Energy Year",
        "translation_key": "kyr",
        "unit": "kWh",
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:solar-power",
        "entity_category": None,  # Main measurement
        "enabled_by_default": True,
    },
    "KT0": {
        "name": "Energy Total",
        "translation_key": "kt0",
        "unit": "kWh",
        "device_class": "energy",
        "state_class": "total_increasing",
        "icon": "mdi:solar-power",
        "entity_category": None,  # Main measurement
        "enabled_by_default": True,
    },
    "TKK": {
        "name": "Inverter Temperature",
        "translation_key": "tkk",
        "unit": "°C",
        "device_class": "temperature",
        "state_class": "measurement",
        "icon": "mdi:thermometer",
        "entity_category": EntityCategory.DIAGNOSTIC,  # Diagnostic
        "enabled_by_default": False,  # Disable by default - not critical for most users
    },
    "KHR": {
        "name": "Power On Hours",
        "translation_key": "khr",
        "unit": "h",
        "state_class": "total_increasing",
        "icon": "mdi:clock-outline",
        "entity_category": EntityCategory.DIAGNOSTIC,  # Diagnostic
        "enabled_by_default": False,  # Disable by default - diagnostic info
    },
    "CAC": {
        "name": "Startups",
        "translation_key": "cac",
        "state_class": "total_increasing",
        "icon": "mdi:restart",
        "entity_category": EntityCategory.DIAGNOSTIC,  # Diagnostic
        "enabled_by_default": False,  # Disable by default - diagnostic info
    },
    "SAL": {
        "name": "Alarm Codes",
        "translation_key": "sal",
        "device_class": "enum",
        "options": SAL_OPTIONS,
        "icon": "mdi:alert-circle",
        "entity_category": EntityCategory.DIAGNOSTIC,  # Important diagnostic
        "enabled_by_default": True,  # Keep enabled - important for monitoring
    },
    "SYS": {
        "name": "Status Code",
        "translation_key": "sys",
        "device_class": "enum",
        "options": SYS_OPTIONS,
        "icon": "mdi:information",
        "entity_category": EntityCategory.DIAGNOSTIC,  # Important diagnostic
        "enabled_by_default": True,  # Keep enabled - important for monitoring
    },
}
