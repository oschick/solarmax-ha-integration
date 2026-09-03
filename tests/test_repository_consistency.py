"""Repository metadata and localization consistency checks."""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_INTEGRATION = _ROOT / "custom_components" / "solarmax"


def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _leaf_paths(value: object, prefix: str = "") -> set[str]:
    """Return dotted paths for every leaf in a nested mapping."""
    if not isinstance(value, dict):
        return {prefix}

    paths: set[str] = set()
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else key
        paths.update(_leaf_paths(child, path))
    return paths


def test_translation_files_have_the_same_keys() -> None:
    """Adding a UI string without every locale must fail validation."""
    expected = _leaf_paths(_load_json(_INTEGRATION / "strings.json"))

    for path in sorted((_INTEGRATION / "translations").glob("*.json")):
        actual = _leaf_paths(_load_json(path))
        assert actual == expected, (
            f"{path.name}: missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


def test_manifest_and_project_versions_match() -> None:
    """A release tag must not package conflicting source versions."""
    manifest_version = _load_json(_INTEGRATION / "manifest.json")["version"]
    with (_ROOT / "pyproject.toml").open("rb") as handle:
        project_version = tomllib.load(handle)["project"]["version"]

    assert manifest_version == project_version


def test_hacs_zip_settings_are_coherent() -> None:
    """A named HACS release asset must opt into ZIP releases."""
    hacs = _load_json(_ROOT / "hacs.json")

    assert "filename" not in hacs or hacs.get("zip_release") is True


def test_agent_guides_are_identical() -> None:
    """Codex and Claude must receive the same repository guidance."""
    assert (_ROOT / "AGENTS.md").read_bytes() == (_ROOT / "CLAUDE.md").read_bytes()


def test_release_version_checker_accepts_matching_tag() -> None:
    """A release tag matching both source versions must pass."""
    result = subprocess.run(
        [sys.executable, _ROOT / "script" / "check-release", "v1.3.3"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_release_version_checker_rejects_mismatching_tag() -> None:
    """Publishing a tag that disagrees with source metadata must fail."""
    result = subprocess.run(
        [sys.executable, _ROOT / "script" / "check-release", "v9.9.9"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "does not match source version 1.3.3" in result.stderr
