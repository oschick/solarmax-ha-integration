# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/oschick/solarmax-ha-integration/compare/v1.0.5...HEAD
[1.0.5]: https://github.com/oschick/solarmax-ha-integration/compare/v1.0.4...v1.0.5
[1.0.4]: https://github.com/oschick/solarmax-ha-integration/compare/v1.0.3...v1.0.4
[1.0.3]: https://github.com/oschick/solarmax-ha-integration/compare/v1.0.0...v1.0.3
[1.0.0]: https://github.com/oschick/solarmax-ha-integration/releases/tag/v1.0.0
