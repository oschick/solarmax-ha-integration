# Contributing

Bug reports, device compatibility results, translations, tests, and code changes are welcome. Check existing issues before opening a new one.

## Local setup

Use Python 3.13 or 3.14 for development. CI also tests the minimum supported pair, Python 3.12 with Home Assistant 2024.12.

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements_dev.txt
script/check
```

`script/check` runs Ruff, the format check, mypy, pytest, and coverage. Coverage must remain at or above 90 percent.

Run one test while iterating:

```bash
.venv/bin/python -m pytest tests/test_connection_engine.py::test_name -q
```

## Repository map

| Path | Responsibility |
| --- | --- |
| `custom_components/solarmax/protocol.py` | MaxComm framing, checksum validation, parsing, and scaling |
| `custom_components/solarmax/connection.py` | Persistent TCP link and connection state machine |
| `custom_components/solarmax/coordinator.py` | Home Assistant polling, sun policy, and repairs |
| `custom_components/solarmax/sensor.py` | Entity values, availability, and night policies |
| `custom_components/solarmax/config_flow.py` | Initial setup and options flow |
| `tools/inverter_emulator.py` | Hardware-free MaxComm server |
| `tests/emulator.py` | Pytest wrapper for the emulator |

Read [docs/architecture.md](docs/architecture.md) before changing connection, polling, availability, or night behavior.

## Change requirements

- Add focused tests for behavior changes and bug fixes.
- Keep runtime code compatible with Home Assistant 2024.12.
- Add each user-facing string to `strings.json` and every translation file.
- Update `README.md` and `CHANGELOG.md` when users will notice the change.
- Keep `AGENTS.md` and `CLAUDE.md` byte-identical.
- Preserve entity unique IDs. Add a migration when a key must change.

The inverter accepts one TCP client. Tests and probes must close sockets, including failure paths. Do not run the hardware probe while Home Assistant or vendor software holds the inverter connection.

## Pull requests

Keep each pull request focused. Include the problem, the chosen behavior, and the commands you ran. Attach diagnostics or logs for device-specific work after removing private network data.

CI runs repository checks against the current pinned Home Assistant release, tests the minimum supported release, and performs a scheduled test against the latest available test stack. HACS and Hassfest validate integration metadata.

## Translations

Copy `custom_components/solarmax/translations/en.json` to the target BCP 47 language code. Translate values without changing keys or placeholders such as `{host}`, `{port}`, and `{minutes}`.

`tests/test_repository_consistency.py` rejects missing translation keys.

## Releases

Maintainers publish a release with these steps:

1. Update the version in `pyproject.toml` and `custom_components/solarmax/manifest.json`.
2. Move the relevant `CHANGELOG.md` entries from Unreleased into the new version.
3. Run `script/check` and `script/check-release vX.Y.Z`.
4. Commit the release, create tag `vX.Y.Z`, and push the tag.

The tag workflow validates the tagged source before it builds `solarmax.zip` and creates the GitHub release.
