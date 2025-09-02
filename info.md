## Solarmax Inverter Integration

A comprehensive Home Assistant integration for monitoring Solarmax solar inverters.

> **⚠️ Compatibility:** Tested on Solarmax 7TP2 Inverter. Should work with most Solarmax inverters built before 2015.

### Features
- **Real-time monitoring** of your solar inverter
- **Easy setup** through the Home Assistant UI
- **Multiple sensors** for complete monitoring:
  - AC and DC power readings
  - Energy production metrics
  - Inverter status and diagnostics
  - Temperature monitoring
- **Local communication** - no cloud dependency
- **Configurable update intervals**

### Supported Data
- Current power output (AC/DC)
- Daily and total energy production
- Voltage and current readings
- Inverter temperature
- Operational status

### Setup
1. Install via HACS or manually
2. Restart Home Assistant
3. Go to Settings → Devices & Services
4. Click "Add Integration" and search for "Solarmax"
5. Enter your inverter's IP address and configure settings

### Requirements
- Solarmax inverter with network connectivity
- Home Assistant 2023.1.0 or newer
- Network access to the inverter from Home Assistant

### Support
For issues, feature requests, or questions, visit the [GitHub repository](https://github.com/oschick/solarmax-agent).
