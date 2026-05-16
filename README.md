# Solarmax Inverter Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![GitHub release](https://img.shields.io/github/release/oschick/solarmax-ha-integration.svg)](https://github.com/oschick/solarmax-ha-integration/releases/)
[![GitHub license](https://img.shields.io/github/license/oschick/solarmax-ha-integration.svg)](https://github.com/oschick/solarmax-ha-integration/blob/main/LICENSE)

A Home Assistant custom integration for Solarmax solar inverters. This integration allows you to monitor your Solarmax inverter's performance directly within Home Assistant.

> **⚠️ Compatibility Notice:** This integration has been tested specifically on a **Solarmax 7TP2 Inverter** and should work with most Solarmax inverters built before 2015. Compatibility with newer models is not guaranteed. Please test and report your results!

## Features

- **Real-time monitoring** of solar inverter data
- **Automatic discovery** via config flow
- **Multiple sensor types** including:
  - AC Power (PAC)
  - DC Power (PDC)
  - Energy production metrics
  - Inverter status and diagnostics
- **Configurable update intervals**
- **Local polling** - no cloud dependency required
- **UI reconfiguration support** - modify settings without removing the integration
- **Advanced diagnostics** with comprehensive device information
- **Smart sensor management** - important sensors enabled, diagnostic sensors optional

## Supported Devices

### Tested Models
- **Solarmax 7TP2 Inverter** ✅ Fully tested and confirmed working

### Likely Compatible Models
- Solarmax inverters manufactured **before 2015**
- Models using the legacy Solarmax protocol over TCP/IP
- Single-phase and three-phase models from the following series:
  - TP series
  - P series
  - C series (older models)

### Known Incompatible Models
- Newer Solarmax models (2015+) that use different communication protocols
- Models that only support Modbus RTU/TCP
- Cloud-only models without local network access

> **Note:** If you're unsure about compatibility, try the integration in test mode. It will fail gracefully if your model isn't supported.

## Supported Functions

### Sensors
The integration provides multiple sensor entities organized by importance:

#### Core Monitoring (Enabled by Default)
- **AC Power (PAC)** - Current AC power output in Watts
- **DC Power (PDC)** - Current DC power input in Watts  
- **Energy Day (KDY)** - Daily energy production in Wh
- **Energy Month (KMT)** - Monthly energy production in kWh
- **Energy Year (KYR)** - Yearly energy production in kWh
- **Energy Total (KT0)** - Total lifetime energy production in kWh
- **Status Code (SYS)** - Current inverter operational status
- **Alarm Codes (SAL)** - Current alarm/error codes

#### Diagnostic Sensors (Disabled by Default)
- **DC Power Strings (PD01, PD02)** - Individual string power outputs
- **AC Voltage Phases (UL1, UL2, UL3)** - Voltage per phase
- **DC Voltage Strings (UD01, UD02)** - Individual string voltages
- **AC Current Phases (IL1, IL2, IL3)** - Current per phase
- **DC Current (IDC, ID01, ID02)** - Total and individual string currents
- **Inverter Temperature (TKK)** - Internal operating temperature
- **Power On Hours (KHR)** - Total operational hours
- **Startups (CAC)** - Number of startup cycles

### Platforms
- **Sensor Platform** - All monitoring data
- **Diagnostics Platform** - System diagnostic information
- **Config Flow** - Easy setup and reconfiguration
- **Options Flow** - Modify settings without re-adding

## Installation

### HACS (Recommended)

1. Open HACS in your Home Assistant instance
2. Go to "Integrations"
3. Click the three dots in the top right corner
4. Select "Custom repositories"
5. Add this repository URL: `https://github.com/oschick/solarmax-ha-integration`
6. Select "Integration" as the category
7. Click "Add"
8. Search for "Solarmax Inverter" and install it
9. Restart Home Assistant

### Manual Installation

1. Download the latest release from the [releases page](https://github.com/oschick/solarmax-ha-integration/releases)
2. Extract the contents
3. Copy the `custom_components/solarmax` folder to your Home Assistant `custom_components` directory
4. Restart Home Assistant

## Configuration

The integration can be configured through the Home Assistant UI:

1. Go to **Settings** → **Devices & Services**
2. Click **Add Integration**
3. Search for "Solarmax Inverter"
4. Enter your inverter details:
   - **Host**: IP address of your inverter
   - **Port**: Communication port (default: 12345)
   - **Update Interval**: How often to poll data (default: 30 seconds)
   - **Device Name**: Friendly name for your inverter

### Reconfiguration

You can modify the integration settings without removing and re-adding:

1. Go to **Settings** → **Devices & Services**
2. Find your Solarmax Inverter integration
3. Click **Configure**
4. Update any settings and click **Submit**
5. The integration will automatically reload with new settings

## Data Update Information

The integration uses **local polling** to retrieve data from your inverter:

- **Update Method**: Direct TCP/IP connection to inverter
- **Update Frequency**: Configurable (default: 30 seconds)
- **Night Mode**: Automatically detects when inverter is offline at night
- **Retry Logic**: Smart retry with exponential backoff for connection failures
- **Connection Health**: Tracks consecutive failures and connection statistics

### Update Process
1. Integration connects to inverter via TCP socket
2. Sends protocol-specific query for all available data points
3. Parses response and updates sensor values
4. Handles errors gracefully (temporary network issues, night mode, etc.)
5. Logs diagnostic information for troubleshooting

## Use Cases

### 1. Energy Production Monitoring
Monitor your solar production in real-time and track daily, monthly, and yearly totals:

```yaml
# Dashboard card example
type: entities
title: Solar Production
entities:
  - entity: sensor.solarmax_inverter_ac_power
    name: Current Power
  - entity: sensor.solarmax_inverter_energy_day
    name: Today's Production
  - entity: sensor.solarmax_inverter_energy_total
    name: Total Production
```

### 2. System Health Monitoring
Keep track of your inverter's operational status and detect issues early:

```yaml
# Automation to alert on inverter alarms
automation:
  - alias: "Solar Inverter Alarm"
    trigger:
      - platform: state
        entity_id: sensor.solarmax_inverter_alarm_codes
        to: '!0'  # Any non-zero alarm code
    action:
      - service: notify.mobile_app
        data:
          message: "Solar inverter alarm: {{ states('sensor.solarmax_inverter_alarm_codes') }}"
```

### 3. Performance Analysis
Analyze inverter performance with detailed diagnostic data:

```yaml
# Track inverter efficiency
sensor:
  - platform: template
    sensors:
      solar_efficiency:
        friendly_name: "Solar Efficiency"
        unit_of_measurement: "%"
        value_template: >
          {% set ac_power = states('sensor.solarmax_inverter_ac_power') | float %}
          {% set dc_power = states('sensor.solarmax_inverter_dc_power') | float %}
          {% if dc_power > 0 %}
            {{ ((ac_power / dc_power) * 100) | round(1) }}
          {% else %}
            0
          {% endif %}
```

### 4. Energy Management
Integrate with Home Assistant energy dashboard and automation:

```yaml
# Energy dashboard configuration
sensor:
  - platform: integration
    source: sensor.solarmax_inverter_ac_power
    name: solar_energy_kwh
    unit_prefix: k
    round: 2
    method: left
```

## Automation Examples

### Daily Production Summary
```yaml
automation:
  - alias: "Daily Solar Summary"
    trigger:
      - platform: time
        at: "20:00:00"
    action:
      - service: notify.family
        data:
          title: "Daily Solar Production"
          message: >
            Today's solar production: {{ states('sensor.solarmax_inverter_energy_day') }} Wh
            Total production: {{ states('sensor.solarmax_inverter_energy_total') }} kWh
```

### Peak Power Alert
```yaml
automation:
  - alias: "Peak Solar Power"
    trigger:
      - platform: numeric_state
        entity_id: sensor.solarmax_inverter_ac_power
        above: 5000  # Adjust threshold as needed
    action:
      - service: notify.mobile_app
        data:
          message: "Solar inverter producing {{ states('sensor.solarmax_inverter_ac_power') }}W!"
```

### Maintenance Reminder
```yaml
automation:
  - alias: "Solar Maintenance Reminder"
    trigger:
      - platform: numeric_state
        entity_id: sensor.solarmax_inverter_power_on_hours
        above: 8760  # One year of hours
    action:
      - service: notify.maintenance
        data:
          message: "Solar inverter has {{ states('sensor.solarmax_inverter_power_on_hours') }} operating hours. Consider maintenance check."
```

## Known Limitations

### Protocol Limitations
- **Single Device**: Integration designed for one inverter per instance
- **Legacy Protocol**: Only supports pre-2015 Solarmax protocol
- **TCP/IP Only**: Requires network connection (no RS485/serial support)
- **Polling Only**: No push notifications from inverter

### Network Requirements
- **Direct Access**: Inverter must be accessible on local network
- **Port Availability**: Default port 12345 must be open
- **Static IP Recommended**: DHCP changes may require reconfiguration

### Functional Limitations
- **No Control**: Read-only integration (monitoring only, no inverter control)
- **No String Detection**: Cannot auto-detect number of DC strings
- **Basic Diagnostics**: Limited to data provided by inverter protocol
- **Night Mode**: All sensors unavailable when inverter is offline at night

### Performance Considerations
- **Update Frequency**: Minimum recommended interval is 10 seconds
- **Network Impact**: Each update requires TCP connection establishment
- **Memory Usage**: Minimal, but stores recent connection history

## Troubleshooting

### Connection Issues

#### Problem: "Failed to connect to inverter"
**Possible Causes:**
- Incorrect IP address or port
- Network connectivity issues
- Inverter is offline or in standby mode
- Firewall blocking connection

**Solutions:**
1. Verify inverter IP address and port in router/network settings
2. Test network connectivity: `ping <inverter_ip>`
3. Check if inverter is powered on and operational
4. Temporarily disable firewall to test connection
5. Try connecting from command line: `telnet <inverter_ip> 12345`

#### Problem: "Connection timeout"
**Possible Causes:**
- Network latency or congestion
- Inverter is busy or overloaded
- Update interval too aggressive

**Solutions:**
1. Increase update interval to 60+ seconds
2. Check network quality and stability
3. Ensure no other applications are polling the inverter
4. Restart inverter if possible

### Data Issues

#### Problem: "Sensors showing 'unavailable'"
**Possible Causes:**
- Inverter is in night mode (expected behavior)
- Temporary connection failure
- Protocol communication error

**Solutions:**
1. Check if it's nighttime (sensors automatically become unavailable)
2. Review logs for connection errors
3. Wait for sunrise if inverter is in night mode
4. Restart integration if issue persists during day

#### Problem: "Incorrect sensor values"
**Possible Causes:**
- Inverter reporting wrong data
- Unit conversion issues
- Protocol misinterpretation

**Solutions:**
1. Compare values with inverter display/app
2. Enable diagnostic sensors for detailed analysis
3. Check inverter firmware version
4. Report issue with diagnostic data

### Configuration Issues

#### Problem: "Integration won't start"
**Possible Causes:**
- Invalid configuration
- Network not ready during startup
- Dependency conflicts

**Solutions:**
1. Check Home Assistant logs for specific errors
2. Verify all configuration values are valid
3. Restart Home Assistant completely
4. Remove and re-add integration

#### Problem: "Reconfiguration fails"
**Possible Causes:**
- New settings are invalid
- Integration is busy updating
- Connection test failed

**Solutions:**
1. Verify new host/port settings are correct
2. Wait for current update cycle to complete
3. Test connection manually before applying changes

### Getting Help

If you encounter issues not covered here:

1. **Enable Debug Logging**: Add to `configuration.yaml`:
   ```yaml
   logger:
     logs:
       custom_components.solarmax: debug
   ```

2. **Collect Diagnostic Data**: 
   - Go to Settings → Devices & Services
   - Find Solarmax Inverter integration
   - Click device name → Download Diagnostics

3. **Report Issues**: Create a GitHub issue with:
   - Integration version
   - Home Assistant version
   - Inverter model
   - Error logs
   - Diagnostic data (remove sensitive information)

## Translations

The integration is fully localized using Home Assistant's built-in translation system. All UI strings, entity names, sensor states, and error messages are translated.

### Available Languages

| Language | Code | Status |
|----------|------|--------|
| English | `en` | ✅ Complete |
| German | `de` | ✅ Complete |
| French | `fr` | ✅ Complete |

### What is Translated

- **Config & options flow** — All setup and reconfiguration labels, descriptions, and error messages
- **Entity names** — All sensor names displayed in the Home Assistant UI
- **Status codes (SYS)** — Human-readable inverter operating states, e.g. "MPP operation", "Low irradiation"
- **Alarm codes (SAL)** — Human-readable alarm descriptions, e.g. "Insulation fault DC side"
- **Error & repair messages** — Connection errors, timeout messages, and repair issue descriptions

### Status & Alarm Code Translations

The **Status Code** and **Alarm Status** sensors use Home Assistant's enum sensor translation, meaning their values are automatically displayed in the user's configured language.

**Status code states:**

| Key | English | German | French |
|-----|---------|--------|--------|
| `no_communication` | No communication | Keine Kommunikation | Pas de communication |
| `in_operation` | In operation | In Betrieb | En fonctionnement |
| `low_irradiation` | Low irradiation | Zu wenig Einstrahlung | Faible irradiation |
| `starting_up` | Starting up | Anfahren | Démarrage |
| `mpp_operation` | MPP operation | Betrieb auf MPP | Fonctionnement MPP |
| `fan_running` | Fan running | Ventilator läuft | Ventilateur en marche |
| `max_power_operation` | Maximum power operation | Betrieb auf Maximalleistung | Fonctionnement à puissance maximale |
| `temperature_limitation` | Temperature limitation | Temperaturbegrenzung | Limitation de température |
| `grid_operation` | Grid operation | Netzbetrieb | Fonctionnement réseau |

**Alarm code states** (bitmask — multiple alarms are detected, and the individual active alarms are listed in the `active_alarms` attribute):

| Key | English | German | French |
|-----|---------|--------|--------|
| `no_error` | No error | Kein Fehler | Aucune erreur |
| `external_fault_1` | External fault 1 | Externer Fehler 1 | Défaut externe 1 |
| `insulation_fault_dc` | Insulation fault DC side | Isolationsfehler DC-Seite | Défaut d'isolation côté DC |
| `earth_fault_current` | Earth fault current too high | Fehlerstrom Erde zu groß | Courant de défaut à la terre trop élevé |
| `fuse_break_center_earth` | Fuse break center earth | Sicherungsbruch Mittelpunkterde | Rupture de fusible terre centrale |
| `external_alarm_2` | External alarm 2 | Externer Alarm 2 | Alarme externe 2 |
| `long_term_temp_limit` | Long-term temperature limitation | Langzeit-Temperaturbegrenzung | Limitation de température à long terme |
| `ac_feed_in_error` | AC feed-in error | Fehler AC-Einspeisung | Erreur d'injection AC |
| `external_alarm_4` | External alarm 4 | Externer Alarm 4 | Alarme externe 4 |
| `fan_defect` | Fan defect | Ventilator defekt | Ventilateur défectueux |
| `fuse_break` | Fuse break | Sicherungsbruch | Rupture de fusible |
| `temp_sensor_failure` | Temperature sensor failure | Ausfall Temperatursensor | Défaillance du capteur de température |
| `multiple_alarms` | Multiple alarms | Mehrere Alarme | Alarmes multiples |

### Adding a New Language

To contribute a new language translation:

1. Copy `custom_components/solarmax/translations/en.json` to a new file named with the [BCP 47 language code](https://en.wikipedia.org/wiki/IETF_language_tag) (e.g. `es.json` for Spanish, `nl.json` for Dutch).
2. Translate all string values — **do not change any keys**.
3. Keep all placeholder variables intact (e.g. `{host}`, `{port}`, `{failures}`).
4. Submit a pull request.

Example for a new file `es.json`:
```json
{
  "config": {
    "step": {
      "user": {
        "title": "Inversor Solarmax",
        ...
      }
    }
  },
  "entity": {
    "sensor": {
      "sys": {
        "name": "Código de estado",
        "state": {
          "grid_operation": "Operación en red",
          ...
        }
      }
    }
  }
}
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
