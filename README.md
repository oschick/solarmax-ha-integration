# Solarmax Inverter for Home Assistant

[![Validate](https://github.com/oschick/solarmax-ha-integration/actions/workflows/validate.yml/badge.svg)](https://github.com/oschick/solarmax-ha-integration/actions/workflows/validate.yml)
[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![GitHub release](https://img.shields.io/github/release/oschick/solarmax-ha-integration.svg)](https://github.com/oschick/solarmax-ha-integration/releases/)
[![GitHub license](https://img.shields.io/github/license/oschick/solarmax-ha-integration.svg)](LICENSE)

Solarmax Inverter connects Home Assistant directly to a SolarMax inverter over
the local MaxComm TCP protocol. It reads live production, energy counters,
operating status, alarms, and diagnostic measurements without a cloud service.

## Highlights

- Local, read-only communication with no cloud account
- One persistent connection instead of a new socket for every poll
- Faster retries after daytime failures and slower polling while the inverter sleeps
- Separate states for an expected shutdown and an unexpected connection fault
- Optional synthetic night values for useful dashboards and energy statistics
- English, German, and French entity, status, alarm, and repair translations
- A built-in repair issue when an unexplained daytime outage persists

## Contents

- [Requirements and compatibility](#requirements-and-compatibility)
- [Installation](#installation)
- [Configuration](#configuration)
- [Connection and recovery](#connection-and-recovery)
- [Night-time sensor behavior](#night-time-sensor-behavior)
- [Sensor catalog](#sensor-catalog)
- [Troubleshooting and support](#troubleshooting-and-support)
- [Development](#development)

## Requirements and compatibility

You need:

- Home Assistant 2024.12.0 or newer
- A SolarMax inverter that exposes the MaxComm protocol over TCP
- Network access from Home Assistant to the inverter, normally on port `12345`

### Inverter models

| Compatibility | Models or protocol |
| --- | --- |
| Confirmed by users | SolarMax 7TP2, 4200S, and 3000S |
| Likely to work | Other pre-2015 SolarMax inverters with MaxComm TCP support |
| Not supported | Models that provide only Modbus, serial, or cloud access |

Support is determined by the protocol, not only by the model name. Some
inverters omit individual MaxComm fields. The integration still works, but the
entities for those fields remain unavailable.

> [!IMPORTANT]
> A SolarMax inverter accepts only one TCP client at a time. Stop MaxTalk,
> vendor software, test scripts, or another Home Assistant instance before
> setting up the integration.

Giving the inverter a fixed DHCP lease is recommended so its address does not
change after setup.

## Installation

### HACS

1. Open HACS and select **Integrations**.
2. Open the menu and select **Custom repositories**.
3. Add `https://github.com/oschick/solarmax-ha-integration` as an
   **Integration** repository.
4. Search for **Solarmax Inverter** and install it.
5. Restart Home Assistant.

HACS handles updates after the custom repository has been added.

### Manual installation

1. Download `solarmax.zip` from the latest
   [GitHub release](https://github.com/oschick/solarmax-ha-integration/releases/).
2. Extract it into Home Assistant's `custom_components` directory.
3. Confirm that the final path is `custom_components/solarmax` and contains
   `manifest.json`.
4. Restart Home Assistant.

## Configuration

After installation:

1. Open **Settings → Devices & services**.
2. Select **Add integration**.
3. Search for **Solarmax Inverter**.
4. Enter the inverter connection and polling settings.

The initial setup opens a short connection and validates a `PAC` response. A
successful probe creates one device and its sensor entities.

### Settings

| Setting | Default | Description |
| --- | ---: | --- |
| Host | `192.168.1.100` | Inverter IP address or host name |
| Port | `12345` | MaxComm TCP port |
| Inverter address | `1` | MaxComm address from 1 to 249 |
| Update interval | `30 s` | Normal online interval from 5 to 3600 seconds |
| Device name | `Solarmax Inverter` | Device name shown in Home Assistant |
| Verify response checksum | On | Reject responses with an invalid MaxComm checksum |
| Keep sensor values overnight | Off | Apply the synthetic night policies described below |
| Twilight elevation threshold | `5°` | Sun elevation below which an offline inverter is expected |

### Checksum verification

Checksum verification protects against damaged or malformed responses and
should normally remain enabled. Some firmware returns otherwise valid frames
with a non-standard checksum. If logs repeatedly show checksum errors for such
an inverter, clear **Verify response checksum**. The setting applies both to
the setup probe and to normal polling, so the checkbox can explicitly tell the
integration to ignore response checksums.

### Changing settings

Select **Configure** on the integration entry to change any setting. Saving
reloads the entry and closes the old connection before opening a new one.
Unlike initial setup, the options form does not start an extra validation
connection, which avoids competing for the inverter's single client slot. An
invalid host or port is reported by the connection state after the reload.

## Connection and recovery

The integration owns one persistent TCP connection and reuses it across polls.
Static device information and live telemetry are requested separately. This
keeps normal polls small and allows an inverter to omit unsupported registers
without losing all sensor updates.

### Connection states

The **Status Code** entity shows the inverter's translated `SYS` state while it
is online. If the inverter cannot be reached, it reports one of these
integration states:

| State | Meaning |
| --- | --- |
| `unknown` | No successful connection yet; daytime startup is still within its reconnect window |
| `offline_expected` | Darkness or inverter shutdown evidence explains the disconnect |
| `offline_fault` | The inverter failed during daytime without shutdown evidence |

The normal online condition is represented by the live inverter status rather
than a synthetic `online` value.

### How an offline state is classified

The integration combines inverter data with Home Assistant's sun position:

1. A successful poll arms an expected shutdown when `SYS` reports `20002` or
   DC power (`PDC`) falls below 25 W.
2. The next disconnect is classified as `offline_expected` when that evidence
   exists or the sun is below the configured twilight threshold.
3. An unexplained daytime disconnect is classified as `offline_fault`.
4. A shutdown that starts unusually early is allowed one hour and at least ten
   failed probes before it escalates to a fault.

At daytime startup, the integration keeps the state `unknown` during a
150-second reconnect window. This avoids raising a fault while the inverter or
network is still becoming available.

### Polling cadence and retries

| Condition | Poll interval |
| --- | --- |
| Online | Configured update interval |
| Startup reconnect | Configured interval or 60 seconds, whichever is shorter |
| Daytime fault | Configured interval or 60 seconds, whichever is shorter |
| Expected offline below twilight | 15 minutes |
| Expected offline above twilight | 60 seconds |

The faster daytime cadence detects the inverter's return promptly. Each poll
has a 15-second budget. A lost response or corrupt frame gets one retry within
that budget. Reloading or unloading the integration closes the socket so the
inverter does not retain the client slot.

If a daytime fault lasts five minutes, Home Assistant creates a repair issue.
The issue clears automatically after communication recovers.

### Diagnostic state attributes

When relevant, the Status Code entity exposes:

| Attribute | Purpose |
| --- | --- |
| `last_successful_update` | Time of the last valid inverter response |
| `fault_since` | Start of the current unexplained fault |
| `reconnecting` | Whether startup recovery is still in progress |
| `expected_outside_twilight` | Whether shutdown evidence occurred above the twilight threshold |
| `code` and `raw_value` | Raw status or offline details for diagnostics |

Automations created with an older release must replace `offline_night` with
`offline_expected` and `connection_failed` with `offline_fault`.

## Night-time sensor behavior

Many SolarMax inverters turn off their network interface when production ends.
That is normal, but it leaves Home Assistant without a live value until the
next successful poll.

With **Keep sensor values overnight** disabled, measurement entities become
unavailable while the inverter is offline. Enable the option if dashboards or
automations need predictable night values. The integration then applies a
policy suited to each register:

| Policy | Sensors | Value while expected offline |
| --- | --- | --- |
| Zero | `PAC`, `PDC`, `PD01`–`PD03`, `PRL`, `IDC`, `ID01`–`ID03`, `IL1`–`IL3`, `UDC`, `UD01`–`UD03` | `0` |
| Hold | `KMT`, `KYR`, `KT0`, `KHR`, `CAC`, `KLD`, `KLM`, `KLY`, `PIN`, `ULH`, `ULL`, `TNH`, `TNL`, `SAL` | Last successful value |
| Hold until midnight | `KDY` | Last value, then `0` after local midnight |
| Unavailable | `UL1`–`UL3`, `TNF`, `TKK`, `TK2`, `TK3`, and unlisted sensors | Unavailable |

Synthetic states include a `night_value_source` attribute such as `zero`,
`hold`, or `unavailable`, so automations can distinguish them from live data.

An early disconnect above the twilight threshold is treated cautiously. Zero
policy sensors stay unavailable until darkness because the integration cannot
yet assume production has stopped. Hold policy sensors may retain their last
value.

After a Home Assistant restart at night, zero-policy sensors can report `0`
immediately. Hold-policy sensors need at least one successful poll after
startup before the integration has a value to retain.

## Sensor catalog

Entity names are translated in Home Assistant. The MaxComm register is shown
in parentheses to make protocol logs and diagnostics easier to interpret.

### Enabled by default

| Entity | Register | Unit or value |
| --- | --- | --- |
| AC power | `PAC` | W |
| DC power | `PDC` | W |
| Energy today | `KDY` | kWh |
| Energy this month | `KMT` | kWh |
| Energy this year | `KYR` | kWh |
| Total energy | `KT0` | kWh |
| Alarm | `SAL` | Translated alarm state and active alarm details |
| Status Code | `SYS` | Translated inverter or connection state |

### Optional production and history entities

| Entity | Register | Unit |
| --- | --- | --- |
| Energy yesterday | `KLD` | kWh |
| Energy last month | `KLM` | kWh |
| Energy last year | `KLY` | kWh |
| Relative power | `PRL` | % |

### Optional diagnostic entities

| Group | Registers | Unit |
| --- | --- | --- |
| DC string power | `PD01`–`PD03` | W |
| AC phase voltage | `UL1`–`UL3` | V |
| DC and string voltage | `UDC`, `UD01`–`UD03` | V |
| AC phase current | `IL1`–`IL3` | A |
| DC and string current | `IDC`, `ID01`–`ID03` | A |
| Temperature | `TKK`, `TK2`, `TK3` | °C |
| Operating hours | `KHR` | h |
| Start count | `CAC` | count |
| Installed power | `PIN` | W |
| Grid frequency | `TNF` | Hz |
| Grid voltage limits | `ULH`, `ULL` | V |
| Grid frequency limits | `TNH`, `TNL` | Hz |

Optional entities can be enabled from the SolarMax device page. An unavailable
optional entity usually means the inverter does not return that register; it
does not necessarily indicate a connection failure.

The Alarm entity exposes its numeric `code` and, for a bitmask containing
multiple alarms, an `active_alarms` attribute. The Status Code entity also
retains its raw code for diagnostics while displaying a translated state.

## Troubleshooting and support

| Symptom | First check |
| --- | --- |
| Setup cannot connect | Confirm the IP and port, then stop every other MaxComm client |
| Repeated checksum errors | Verify the inverter response, then try the checksum checkbox for known non-standard firmware |
| `offline_fault` during daylight | Check power, Ethernet, IP address, and whether another client took the connection |
| `offline_expected` at the wrong time | Check Home Assistant's location, time zone, sun entity, and twilight threshold |
| Only some entities are unavailable | The inverter may not implement those MaxComm registers |
| Held values are missing after a night restart | Wait for the first successful daytime poll |

The [troubleshooting guide](docs/troubleshooting.md) explains these checks,
logging, connection states, and diagnostic downloads in more detail.

If the problem remains, use the matching
[GitHub issue form](https://github.com/oschick/solarmax-ha-integration/issues/new/choose).
Include the Home Assistant and integration versions, inverter model, connection
state, relevant settings, diagnostics, and logs. Remove credentials or network
details that you do not want to publish.

## Development

[CONTRIBUTING.md](CONTRIBUTING.md) covers local setup, checks, translations,
pull requests, and releases. [docs/architecture.md](docs/architecture.md)
describes the protocol, connection engine, coordinator, entities, and test
emulator.

Run the same validation used by CI with:

```bash
script/check
```

## License

This project is licensed under the [MIT License](LICENSE).
