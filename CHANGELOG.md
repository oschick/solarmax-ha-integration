# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

We rebuilt inverter communication around one TCP session and added optional
overnight sensor values. Home Assistant uses separate states for normal dusk
shutdowns and daytime faults, adapts its polling rate, and can start while the
inverter sleeps.

### Breaking changes

- The new connection engine replaces the previous request-per-poll transport.
  Hardware testing covers one SolarMax 7TP2; other inverter models and firmware
  versions may behave differently.
- The Status Code entity now shows **Offline (expected)** (`offline_expected`)
  instead of **Offline (Night)** (`offline_night`), and **Offline (fault)**
  (`offline_fault`) instead of **Connection failed** (`connection_failed`).
  Update automations and dashboards that match the old raw values.
- The integration now requires Home Assistant 2024.12.0 or newer and Python
  3.12 or newer.

### Added

- **Keep sensor values overnight** can show zero for production, retain
  cumulative and static values, and reset daily energy at local midnight. Grid
  and temperature readings remain unavailable. Synthetic readings identify
  their source through `night_value_source`.
- The connection engine reuses one TCP connection, limits each poll to 15
  seconds, and changes its polling interval based on inverter state. Home
  Assistant can create entities while the inverter sleeps.
- An armed daytime **Offline (expected)** (`offline_expected`) state becomes
  **Offline (fault)** (`offline_fault`) after one hour and ten failed probes.
- Users can dismiss a connection repair for 24 hours during the same fault
  episode.

### Fixed

- Shutdown waits for active connections, polls, emulator handlers, and sensor
  platform unloads. The engine cannot reopen a socket after closing.
- Initial setup validates MaxComm frames and respects **Verify response
  checksum**, including the option to ignore checksums. Runtime polling retries
  once after lost responses, corrupt frames, peer closes, or partial static
  data.
- Response handling now allows the MaxComm protocol's three-second response
  window, with a 3.5-second timeout and a 15-second overall poll budget.
- Valid fields survive when the inverter returns one malformed field.
- Failed device-information requests no longer block valid live telemetry, and
  each poll classifies a connection failure only once.
- Nighttime zero policies no longer create values for registers the inverter
  has never reported. Unsupported sensors remain unavailable.
- Saving integration options no longer opens a competing connection to an
  inverter that accepts one TCP client.
- Opening a connection repair no longer fails when Home Assistant provides no
  issue data, and dismissing it suppresses the same fault for 24 hours.
- Expected nighttime shutdowns reset fault timers, so an inverter that remains
  offline after dawn starts a new daytime fault episode.
- Delayed model, firmware, and serial data now refreshes the Home Assistant
  device registry after the inverter becomes available.
- Diagnostics no longer expose the inverter serial number.
- HACS installs the same `solarmax.zip` archive that the release workflow tests
  and attests.

### Maintenance

- CI uses one required merge gate, tests Python 3.12 through 3.14, checks changed
  lines for coverage, and validates workflows with actionlint and zizmor.
- CodeQL scans pull requests, while a weekly canary checks the newest compatible
  Home Assistant test stack.
- Releases now start manually from `main`, validate the packaged integration,
  attest the ZIP, and create a draft for review before publication.
- The release workflow now prepares a review branch when source versions need
  updating. It supports SemVer prerelease suffixes such as alpha, beta, release
  candidate, and test.
- Guided issue forms and separate contributor, architecture, and
  troubleshooting guides make reports and maintenance easier to follow.

## [1.3.3] - 2026-08-11

### Added
- **Configurable twilight elevation threshold**: the sun elevation (in degrees) below which the inverter is expected to be offline during dusk/dawn can now be adjusted via the integration's config/options flow instead of being hardcoded, with matching documentation in the README, Fixes #20.

## [1.3.2] - 2026-08-03

### Fixed
- **Day-time outages no longer stuck as "Offline (Night)"**: after a normal night, the expected-offline state is cleared on the first day-time failure. A genuine day-time outage now reports "Connection failed" and escalates in the logs (WARNING → ERROR → DEBUG) from scratch instead of being silently suppressed by the night-time failure counter.
- **Log noise on expected night-time disconnects**: a failed setup at night and the "Failed to connect / Failed to get data" messages are now logged at debug level, so a normal night no longer fills the log with errors. Day-time failures still escalate normally. Fixes #17
- **Empty inverter responses no longer logged as "Unexpected error"**: a valid frame with no parseable values is treated as a regular failed poll with the same night/day handling instead of hitting the generic error path at ERROR level on every poll.
- **Protocol errors now escalate and quiet down**: persistent checksum mismatches or IPR/IPN rejections are logged like connection errors (WARNING → ERROR once → DEBUG) instead of "Unexpected error" at ERROR level on every poll.
- **Transient protocol errors are retried**: corrupted or truncated responses (bad checksum, partial frames) are retried up to 3 times like connection errors instead of failing the poll immediately; only deterministic errors (IPR/IPN) skip the retry.
- **Connection repair issue is now actually raised**: after 4 consecutive day-time connection failures, a "Inverter Connection Issues" repair issue is created in Home Assistant with a confirm-and-fix flow, and cleared automatically once the connection is restored or night-time offline mode begins. Previously the repair platform existed but nothing ever triggered it.
- **Diagnostics identifiers fixed**: `device_info.identifiers` now uses a JSON-serializable `(domain, entry_id)` list and reports the detected inverter model (e.g. "SolarMax 7TP2") instead of a plain string and generic "Inverter".

### Changed
- **Inverter emulator**: grid frequency (TNF) is now encoded at 0.01 Hz/digit (raw 5000 → 50.0 Hz), matching the integration's scaling. The emulator previously transmitted 0.1 Hz/digit, so frequency parsed from emulator output read 10× too low.

## [1.3.1] - 2026-06-13

### Fixed
- **Energy Yesterday/Last Month/Last Year (KLD/KLM/KLY)**: removed the invalid `state_class: measurement` on these energy sensors, which Home Assistant rejects for the `energy` device class. They now report no state class (point-in-time historical totals, not running meters).

### Changed
- **Internal refactor (no functional change)**: data-driven value scaling and named frame helpers in the protocol layer; migrated sensor definitions to Home Assistant's `SensorEntityDescription` pattern; simplified the coordinator's connection-failure handling and device-info parsing; deduplicated the config-flow and repair-flow code. Entity IDs, unique IDs, and names are unchanged.

## [1.3.0] - 2026-06-12

### Added
- **Full Testing** Added comprehensive testing pipeline for all integration components (config flow, coordinator, sensors), runs on every PR and commit
- **Pre-commit Hooks**: Switched to ruff for code formatting, linting, pre-commit hooks, and CI checks for consistent code style and quality enforcement

### Fixed
- **Fix Existing Tests**: Fixed existing test suite
- **Code Hygiene & Quality**: Addressed code quality issues identified by Claude

## [1.2.1] - 2026-05-19

### Fixed
- Fixed incorrect Energy Yesterday sensor key (KDL → KLD). Thanks @olabaie
- Fixed suggested precision for frequency sensors (two decimal places). Thanks @olabaie


## [1.2.0] - 2026-05-18

### Breaking Changes
- **Checksum verification is now enabled by default**. If your inverter uses a non-standard CRC implementation, you may see "checksum verification failed" errors after upgrading. Disable the "Verify response checksum" option in the integration configuration to restore the previous behaviour.

### Added
- **Extended Status Codes**: Thanks @olabaie & [https://github.com/t-pa/solarmaxcom](https://github.com/t-pa/solarmaxcom), Expanded SYS status map to ~110 entries (20000–20999)
- **New Sensors**: 11 additional sensors from @olabaie & [https://github.com/t-pa/solarmaxcom](https://github.com/t-pa/solarmaxcom) (disabled by default, your Inverter may not support all): Energy Yesterday (KDL), Energy Last Month (KLM), Energy Last Year (KLY), Relative Power % (PRL), Installed Power (PIN), Grid Frequency (TNF), DC Power/Voltage/Current String 3 (PD03/UD03/ID03), Inverter Temperature 2/3 (TK2/TK3), Grid Voltage Upper Limit (ULH), Grid Voltage Lower Limit (ULL), Grid Frequency Upper Limit (TNH), Grid Frequency Lower Limit (TNL).
- **Inverter Type Detection**: Device info now shows the actual inverter model (e.g. "SolarMax 7TP2") instead of generic "Inverter", queried via the MaxComm TYP register
- **Firmware Version Display**: Device info shows the real firmware version from the inverter (SWV key) instead of hardcoded "1.0.0"
- **Serial Number**: Added serial number detection (DIN key) and display in device info for unique inverter identification
- **Build/Release Number**: Added build/release number detection (BDN key) for detailed firmware information
- **Device Type Map**: Complete mapping of all 116 SolarMax device types from the MaxComm protocol specification
- **DC Voltage Sensor (UDC)**: Added official MaxComm protocol key for total DC input voltage
- **Response Checksum Verification**: Validates CRC on every inverter response to detect corrupt data
- **Protocol Error Handling**: Detects and reports MaxComm interface errors (IPR: invalid protocol, IPN: invalid port)

### Changed
- **CRC Verification Now Strict**: Response checksum mismatch raises `SolarmaxProtocolError` instead of logging a warning and continuing with potentially corrupt data. **If upgrading from v1.1.x and your inverter stops working**, disable "Verify response checksum" in the integration options.
- **Multi-Frame Response Support**: Large responses (>255 bytes) from the inverter are now correctly handled — the inverter splits them into multiple frames with individual CRCs
- **Protocol Error Not Retried**: `SolarmaxProtocolError` (IPR/IPN) is raised immediately without retry since these errors are deterministic
- **MaxComm Protocol Reference**: Integration fully refactored against the official "MaxComm Datenprotokoll" (August 2022) specification
- **Configurable Checksum Verification**: New option to disable CRC verification for inverters with non-standard checksum implementations


## [1.1.0] - 2026-05-16

### Added
- **French Translation**: Full French localization for all UI strings, entity names, status codes, and alarm states
- **Inverter Emulator**: TCP test tool (`tools/inverter_emulator.py`) for offline development with 7 scenarios and interactive mode
- **Translations Section in README**: Documentation on supported languages, status/alarm code tables, and how to contribute new languages

### Changed
- **Enum Sensor Pattern**: Status (SYS) and alarm (SAL) sensors now use Home Assistant's enum device class with translation-based state display
- **Status Code Mapping**: Corrected to actual Solarmax protocol codes (20000–20008) with proper English option keys
- **Alarm Bitmask Decoding**: Proper bitmask handling (power-of-2 values: 1, 2, 4, 8, ... 65536) with `active_alarms` attribute for multiple simultaneous alarms
- **strings.json Rebuilt**: Fully synced with all 24 sensor definitions (was missing 20 sensors, had 3 stale entries)

### Fixed
- **Status/Alarm Translation Bug**: Sensors no longer show hardcoded German strings — HA automatically translates via the enum state translation system based on user's language setting
- **Status Code Display**: Now shows human-readable translated text (e.g. "MPP operation") instead of raw numeric code

## [1.0.7] - 2026-03-27

### New Feature
- make inverter internal address configurable (#4) fixes #1

### Fixed
- Fixed daily energy unit (#3) fixes #2

## [1.0.6] - 2025-09-11

### Fixed
- **Compatibility**: Fixed `SensorEntityCategory` import error for newer Home Assistant versions
- Updated entity category import to use `EntityCategory` from `homeassistant.helpers.entity`
- **Modernization**: Updated deprecated type hints (`Dict`, `Union` → `dict`, `|`)

## [1.0.5] - 2025-09-10

### Added - Gold Tier Compliance 🏆
- **Gold**: Diagnostics platform with comprehensive device and connection information
- **Gold**: Entity categories for proper sensor organization (diagnostic vs measurement)
- **Gold**: Entity disabled by default for less critical sensors (voltages, currents, temperature)
- **Gold**: Exception translations with translatable error messages
- **Gold**: Repair issues and repair flows for connection problems
- **Gold**: Enhanced documentation with use cases, automation examples, and troubleshooting
- **Gold**: Comprehensive supported devices and known limitations documentation
- Diagnostics platform providing detailed system information and connection health
- Repair flows for connection issues and configuration problems
- Smart entity management: core sensors enabled, diagnostic sensors optional
- Translatable exception messages in English and German

### Enhanced - Quality Improvements
- Enhanced translations for repair issues and exceptions
- Comprehensive integration quality documentation and compliance checklist

## [1.0.4] - 2025-09-10

### Added - Silver/Bronze Tier Compliance
- **Quality**: Comprehensive test suite with 95%+ coverage (config flow, API, coordinator, sensor tests)
- **Quality**: Full Bronze and Silver tier Home Assistant integration standards compliance
- **Quality**: Duplicate entry prevention using unique IDs (host:port combination)
- **Quality**: Enhanced config flow with data descriptions and field context
- **Quality**: Connection validation during integration setup with ConfigEntryNotReady handling
- Comprehensive integration quality documentation and compliance checklist

### Enhanced - Quality Improvements
- **Quality**: Migrated from hass.data to ConfigEntry.runtime_data for proper resource management
- **Quality**: Added PARALLEL_UPDATES = 1 to prevent overwhelming single inverter device
- **Quality**: Improved logging strategy - log once when unavailable/restored, debug for subsequent failures
- **Quality**: Enhanced entity availability logic with smarter failure detection
- Proper config entry unloading with resource cleanup
- Smart coordinator updates with `always_update=False` for efficiency

## [1.0.3] - 2025-09-10

### Added
- **New Feature**: Integration reconfiguration support - Change host, port, update interval, and device name from Home Assistant UI
- Options flow for modifying integration settings without removal/re-adding
- Configuration validation with connection testing before applying changes
- Automatic integration reload after successful configuration changes
- Enhanced translations for reconfiguration UI (English and German)

### Fixed
- **Major**: Fixed connection timeout issues when inverter comes back online after being offline (night mode)
- **Major**: Improved socket connection handling with proper cleanup and retry mechanisms
- **Major**: Enhanced reconnection logic with exponential backoff to prevent overwhelming inverter
- Consistent timeout handling across connection and data transfer operations
- Better error differentiation between expected offline states (night) vs connection problems
- Improved connection state tracking and failure diagnostics

### Enhanced
- Added intelligent retry logic for connection failures (3 attempts with 2 sub-retries each)
- Enhanced error handling with context-aware logging (night vs day failures)
- Improved sensor availability logic based on connection state and expected offline periods
- Better status messages showing connection failure counts and offline reasons
- Extended diagnostic attributes for troubleshooting connection issues
- Added connection health tracking with timestamps for last successful updates
- Enhanced config flow with options flow support and update listeners

### Technical Improvements
- New exception classes (`SolarmaxConnectionError`, `SolarmaxTimeoutError`) for better error handling
- Connection state properties (`consecutive_failures`, `last_successful_update`, `is_expected_offline`)
- Enhanced status translations for offline states and connection failures

### Added
- Initial HACS compatibility
- Comprehensive README documentation
- MIT License

## [1.0.0] - 2025-09-03

### Added
- Initial release of Solarmax Inverter integration
- Support for Solarmax solar inverters
- Config flow for easy setup
- Multiple sensor types:
  - AC Power (PAC)
  - DC Power (PDC)
  - Energy production metrics
  - Inverter status and diagnostics
- Local polling communication
- Configurable update intervals
- Multi-language support (English, German)
- Device and diagnostic information

### Technical
- Async/await support
- Data coordinator for efficient updates
- Proper error handling and logging
- Translation support
- HACS compatibility

[Unreleased]: https://github.com/oschick/solarmax-ha-integration/compare/v1.3.3...HEAD
[1.3.3]: https://github.com/oschick/solarmax-ha-integration/compare/v1.3.2...v1.3.3
[1.3.2]: https://github.com/oschick/solarmax-ha-integration/compare/v1.3.1...v1.3.2
[1.3.1]: https://github.com/oschick/solarmax-ha-integration/compare/v1.3.0...v1.3.1
[1.3.0]: https://github.com/oschick/solarmax-ha-integration/compare/v1.2.1...v1.3.0
[1.2.1]: https://github.com/oschick/solarmax-ha-integration/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/oschick/solarmax-ha-integration/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/oschick/solarmax-ha-integration/compare/v1.0.7...v1.1.0
[1.0.7]: https://github.com/oschick/solarmax-ha-integration/compare/v1.0.6...v1.0.7
[1.0.6]: https://github.com/oschick/solarmax-ha-integration/compare/v1.0.5...v1.0.6
[1.0.5]: https://github.com/oschick/solarmax-ha-integration/compare/v1.0.4...v1.0.5
[1.0.4]: https://github.com/oschick/solarmax-ha-integration/compare/v1.0.3...v1.0.4
[1.0.3]: https://github.com/oschick/solarmax-ha-integration/compare/v1.0.0...v1.0.3
[1.0.0]: https://github.com/oschick/solarmax-ha-integration/releases/tag/v1.0.0
