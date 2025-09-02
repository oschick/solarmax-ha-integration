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
4. Follow the configuration flow

### Configuration Options

| Parameter | Description | Default | Required |
|-----------|-------------|---------|----------|
| Host | IP address of your Solarmax inverter | - | Yes |
| Port | Communication port | 12345 | No |
| Update Interval | Data refresh interval (seconds) | 30 | No |
| Device Name | Custom name for the inverter | Solarmax Inverter | No |

## Supported Inverters

**Testing Status:** This integration has been specifically tested and verified on a **Solarmax 7TP2 Inverter**. While it should be compatible with most Solarmax inverters built before 2015, compatibility with other models has not been verified.

**Compatibility Notes:**
- ✅ **Verified:** Solarmax 7TP2 Inverter
- 🔄 **Expected to work:** Most Solarmax inverters manufactured before 2015
- ❓ **Unknown:** Newer inverter models (post-2015) may use different communication protocols

Please test with your specific model and report compatibility results by creating an issue. This helps improve the documentation for other users.

## Sensors

The integration provides the following sensors:

| Sensor | Description | Unit | Device Class |
|--------|-------------|------|--------------|
| AC Power | Current AC power output | W | power |
| DC Power | Current DC power input | W | power |
| Daily Energy | Energy produced today | kWh | energy |
| Total Energy | Total energy produced | kWh | energy |
| Voltage | DC voltage | V | voltage |
| Current | DC current | A | current |
| Temperature | Inverter temperature | °C | temperature |
| Status | Inverter operational status | - | - |

## Troubleshooting

### Common Issues

1. **Connection errors**: Ensure your Home Assistant instance can reach the inverter's IP address and port
2. **No data**: Check if the inverter is powered on and communicating properly
3. **Timeout errors**: Try increasing the update interval in the integration configuration

### Enable Debug Logging

To enable debug logging for troubleshooting, add the following to your `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.solarmax: debug
```

## Support

- **Issues**: [GitHub Issues](https://github.com/oschick/solarmax-ha-integration/issues)
- **Feature Requests**: [GitHub Discussions](https://github.com/oschick/solarmax-ha-integration/discussions)

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Thanks to the Home Assistant community for their support and contributions
- Special thanks to all beta testers and contributors

---

**Note**: This is a custom integration and is not officially supported by Home Assistant or Solarmax.
