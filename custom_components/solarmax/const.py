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

# =============================================================================
# Device Type Map (TYP key) - per MaxComm Protocol Section 2.3
# Maps the TYP register value (decimal) to the device model name.
# =============================================================================
DEVICE_TYPE_MAP: dict[int, str] = {
    # TS-SV MT series
    20812: "SolarMax 1440TS-SV MT",
    20809: "SolarMax 1080TS-SV MT",
    20806: "SolarMax 720TS-SV MT",
    20803: "SolarMax 360TS-SV MT",
    # TS-SV ST series
    20712: "SolarMax 1440TS-SV ST",
    20709: "SolarMax 1080TS-SV ST",
    20706: "SolarMax 720TS-SV ST",
    20703: "SolarMax 360TS-SV ST",
    20700: "SolarMax 360TS-SV",
    # TP series
    20653: "SolarMax 4TP",
    20652: "SolarMax 5TP2",
    20651: "SolarMax 6TP2",
    20650: "SolarMax 7TP2",
    # P series
    20640: "SolarMax 5000P",
    20635: "SolarMax 4600P",
    20630: "SolarMax 4000P",
    20620: "SolarMax 3000P",
    20610: "SolarMax 2000P",
    # TS-SV MT (1320 series)
    20512: "SolarMax 1320TS-SV MT",
    20509: "SolarMax 990TS-SV MT",
    20506: "SolarMax 660TS-SV MT",
    20503: "SolarMax 330TS-SV MT",
    # TS-SV ST (1320 series)
    20412: "SolarMax 1320TS-SV ST",
    20409: "SolarMax 990TS-SV ST",
    20406: "SolarMax 660TS-SV ST",
    20403: "SolarMax 330TS-SV ST",
    # TS series
    20318: "SolarMax 300TS MT",
    20316: "SolarMax 300TS ST",
    20314: "SolarMax 100TS",
    20312: "SolarMax 80TS",
    20310: "SolarMax 50TS",
    # HT series
    20266: "SolarMax 32HT2",
    20262: "SolarMax 32HT4",
    20260: "SolarMax 30HT4",
    20258: "SolarMax 25HT4",
    20257: "SolarMax 25HT2",
    20256: "SolarMax 20HT4",
    20255: "SolarMax 20HT2",
    # MT series A
    20254: "SolarMax 18MT3 A",
    20252: "SolarMax 15MT3 A",
    20250: "SolarMax 12MT2 A",
    # MT series SV
    20240: "SolarMax 18MT3 SV",
    # MT series
    20215: "SolarMax 8MT2",
    20213: "SolarMax 15MT2",
    20211: "SolarMax 13MT2",
    20210: "SolarMax 10MT2",
    20208: "SolarMax 15MT3",
    20206: "SolarMax 13MT3",
    20202: "SolarMax 10MT",
    # S series
    20110: "SolarMax 35S",
    20100: "SolarMax 20S",
    20040: "SolarMax 6000S",
    20030: "SolarMax 4200S",
    20020: "SolarMax 3000S",
    20010: "SolarMax 2000S",
    # SXT series
    12060: "SolarMax 110SXT",
    12055: "SolarMax 255SXT",
    12054: "SolarMax 250SXT",
    # SHT-S series
    11130: "SolarMax 60SHT-S",
    11125: "SolarMax 50SHT-S",
    11120: "SolarMax 60SHT-S2",
    11115: "SolarMax 50SHT-S2",
    # SHT series
    11110: "SolarMax 60SHT",
    11105: "SolarMax 50SHT",
    11100: "SolarMax 30SHT",
    11095: "SolarMax 28SHT",
    11090: "SolarMax 25SHT",
    11085: "SolarMax 22SHT",
    11080: "SolarMax 20SHT",
    11075: "SolarMax 17SHT",
    # SMT series
    11070: "SolarMax 15SMT",
    11065: "SolarMax 13SMT",
    11060: "SolarMax 10SMT",
    11055: "SolarMax 8SMT",
    11050: "SolarMax 6SMT",
    # SP series
    11045: "SolarMax 6000SP",
    11040: "SolarMax 5000SP",
    11035: "SolarMax 4600SP",
    11030: "SolarMax 4000SP",
    11025: "SolarMax 3600SP",
    11020: "SolarMax 3000SP",
    11015: "SolarMax 2500SP",
    11010: "SolarMax 2000SP",
    11005: "SolarMax 1500SP",
    11000: "SolarMax 1000SP",
    # MaxCount / MaxMeteo
    10300: "MaxCount",
    10210: "MaxMeteo plus2T",
    10200: "MaxMeteo",
    # C/E series (6000)
    6010: "SolarMax 6000C",
    6000: "SolarMax 6000E",
    # C/E series (4000)
    4200: "SolarMax 4200C",
    4010: "SolarMax 4000C",
    4001: "SolarMax 4000",
    4000: "SolarMax 4000E",
    # C/E series (3000)
    3010: "SolarMax 3000C",
    3001: "SolarMax 3000E",
    3000: "SolarMax 3000",
    # C/E series (2000)
    2010: "SolarMax 2000C",
    2001: "SolarMax 2000E",
    2000: "SolarMax 2000",
    # Smaller models
    330: "SolarMax 330C-SV",
    300: "SolarMax 300C",
    126: "SolarMax 125",
    101: "SolarMax 100",
    100: "SolarMax 100C",
    80: "SolarMax 80C",
    61: "SolarMax 60",
    50: "SolarMax 50C",
    46: "SolarMax 45",
    41: "SolarMax 40",
    35: "SolarMax 35C",
    31: "SolarMax 30",
    30: "SolarMax 30C",
    25: "SolarMax 25C",
    21: "SolarMax 20",
    20: "SolarMax 20C",
}

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
    20009: "dc_current_limited",
    20010: "ac_current_limited",
    20011: "test_mode",
    20012: "remote_controlled",
    20013: "start_delay",
    20110: "dc_link_overvoltage",
    20111: "overvoltage",
    20112: "overload",
    20114: "leakage_current_high",
    20115: "no_grid",
    20116: "grid_frequency_high",
    20117: "grid_frequency_low",
    20118: "island_operation",
    20119: "poor_grid_quality",
    20122: "grid_voltage_high",
    20123: "grid_voltage_low",
    20124: "temperature_too_high",
    20125: "grid_current_asymmetric",
    20126: "external_input_error_1",
    20127: "external_input_error_2",
    20129: "incorrect_rotation",
    20130: "wrong_device_type",
    20131: "main_switch_off",
    20132: "diode_overtemperature",
    20134: "fan_defective",
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
    "UDC": {
        "name": "DC Voltage",
        "translation_key": "udc",
        "unit": "V",
        "device_class": "voltage",
        "state_class": "measurement",
        "icon": "mdi:flash",
        "entity_category": EntityCategory.DIAGNOSTIC,  # Detailed diagnostic
        "enabled_by_default": False,  # Disable by default - advanced users only
    },
    "UD01": {
        "name": "DC Voltage String 1",
        "translation_key": "ud01",
        "unit": "V",
        "device_class": "voltage",
        "state_class": "measurement",
        "icon": "mdi:flash",
        "entity_category": EntityCategory.DIAGNOSTIC,  # Detailed diagnostic
        "enabled_by_default": False,  # Disable by default - advanced users only
    },
    "UD02": {
        "name": "DC Voltage String 2",
        "translation_key": "ud02",
        "unit": "V",
        "device_class": "voltage",
        "state_class": "measurement",
        "icon": "mdi:flash",
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
