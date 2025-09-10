"""Constants for the Solarmax Inverter integration."""

from homeassistant.helpers.entity import EntityCategory

DOMAIN = "solarmax"

# Configuration constants
CONF_HOST = "host"
CONF_PORT = "port"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_DEVICE_NAME = "device_name"

# Default values
DEFAULT_PORT = 12345
DEFAULT_UPDATE_INTERVAL = 30
DEFAULT_DEVICE_NAME = "Solarmax Inverter"

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
        "unit": "Wh",
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
        "icon": "mdi:alert-circle",
        "entity_category": EntityCategory.DIAGNOSTIC,  # Important diagnostic
        "enabled_by_default": True,  # Keep enabled - important for monitoring
    },
    "SYS": {
        "name": "Status Code",
        "translation_key": "sys",
        "icon": "mdi:information",
        "entity_category": EntityCategory.DIAGNOSTIC,  # Important diagnostic
        "enabled_by_default": True,  # Keep enabled - important for monitoring
    },
}
