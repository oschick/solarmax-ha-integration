"""Repository metadata and localization consistency checks."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

_ROOT = Path(__file__).resolve().parent.parent
_INTEGRATION = _ROOT / "custom_components" / "solarmax"
_MARKDOWN_LINK = re.compile(r"!?\[[^]]*\]\(([^)]+)\)")


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


def _project_version() -> str:
    with (_ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["project"]["version"]


def _copy_release_fixture(tmp_path: Path) -> Path:
    """Copy the files consumed by the release checker."""
    root = tmp_path / "repository"
    integration = root / "custom_components" / "solarmax"
    scripts = root / "script"
    integration.mkdir(parents=True)
    scripts.mkdir()

    shutil.copy2(_ROOT / "pyproject.toml", root / "pyproject.toml")
    shutil.copy2(_ROOT / "CHANGELOG.md", root / "CHANGELOG.md")
    shutil.copy2(_INTEGRATION / "manifest.json", integration / "manifest.json")
    shutil.copy2(_ROOT / "script" / "check-release", scripts / "check-release")
    return root


def _write_release_archive(
    path: Path, *extra_paths: str, include_strings: bool = True
) -> None:
    """Write a minimal release archive with optional extra entries."""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("solarmax/__init__.py", "")
        archive.writestr(
            "solarmax/manifest.json",
            json.dumps({"version": _project_version()}),
        )
        if include_strings:
            archive.writestr("solarmax/strings.json", "{}")
        for extra_path in extra_paths:
            archive.writestr(extra_path, "unexpected")


def _run_release_checker(
    root: Path, *arguments: str | Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, root / "script" / "check-release", *arguments],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


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
    assert manifest_version == _project_version()


def test_hacs_zip_settings_are_coherent() -> None:
    """A named HACS release asset must opt into ZIP releases."""
    hacs = _load_json(_ROOT / "hacs.json")

    assert "filename" not in hacs or hacs.get("zip_release") is True


def test_agent_guides_are_identical() -> None:
    """Codex and Claude must receive the same repository guidance."""
    assert (_ROOT / "AGENTS.md").read_bytes() == (_ROOT / "CLAUDE.md").read_bytes()


def test_local_documentation_links_exist() -> None:
    """Local links in maintained documentation must resolve."""
    documents = [*_ROOT.glob("*.md"), *(_ROOT / "docs").glob("*.md")]
    for document in documents:
        for target in _MARKDOWN_LINK.findall(document.read_text(encoding="utf-8")):
            parsed = urlsplit(target.strip("<>"))
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            linked_path = document.parent / unquote(parsed.path)
            assert linked_path.exists(), f"{document}: missing link target {target}"


def test_release_version_checker_accepts_matching_tag() -> None:
    """A release tag matching both source versions must pass."""
    result = _run_release_checker(_ROOT, f"v{_project_version()}")

    assert result.returncode == 0, result.stderr


def test_release_version_checker_rejects_mismatching_tag() -> None:
    """Publishing a tag that disagrees with source metadata must fail."""
    result = _run_release_checker(_ROOT, f"not-v{_project_version()}")

    assert result.returncode != 0
    assert f"does not match source version {_project_version()}" in result.stderr


def test_release_checker_writes_matching_changelog_section(tmp_path: Path) -> None:
    """Release notes must come from the matching changelog section."""
    root = _copy_release_fixture(tmp_path)
    (root / "CHANGELOG.md").write_text(
        f"""\
# Changelog

## [{_project_version()}] - 2026-09-04

### Fixed

- Expected release note.

## [0.0.1] - 2020-01-01

- Older note.
""",
        encoding="utf-8",
    )
    notes = tmp_path / "release-notes.md"

    result = _run_release_checker(
        root,
        f"v{_project_version()}",
        "--notes-output",
        notes,
    )

    assert result.returncode == 0, result.stderr
    content = notes.read_text(encoding="utf-8")
    assert "Expected release note" in content
    assert "Older note" not in content


def test_release_checker_rejects_missing_changelog_section(tmp_path: Path) -> None:
    """A release without user-facing notes must fail before publishing."""
    root = _copy_release_fixture(tmp_path)
    (root / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [0.0.1] - 2020-01-01\n\n- Older note.\n",
        encoding="utf-8",
    )

    result = _run_release_checker(root, f"v{_project_version()}")

    assert result.returncode != 0
    assert f"changelog has no section for {_project_version()}" in result.stderr


def test_release_checker_accepts_expected_archive_layout(tmp_path: Path) -> None:
    """A release archive with the integration at its root must pass."""
    archive = tmp_path / "solarmax.zip"
    _write_release_archive(archive)

    result = _run_release_checker(_ROOT, f"v{_project_version()}", "--archive", archive)

    assert result.returncode == 0, result.stderr


def test_release_checker_rejects_forbidden_archive_path(tmp_path: Path) -> None:
    """Caches and bytecode must not enter a public release asset."""
    archive = tmp_path / "solarmax.zip"
    _write_release_archive(archive, "solarmax/__pycache__/const.cpython-314.pyc")

    result = _run_release_checker(_ROOT, f"v{_project_version()}", "--archive", archive)

    assert result.returncode != 0
    assert "archive contains forbidden path" in result.stderr


def test_release_checker_requires_complete_archive_layout(tmp_path: Path) -> None:
    """A release without user-facing strings must fail inspection."""
    archive = tmp_path / "solarmax.zip"
    _write_release_archive(archive, include_strings=False)

    result = _run_release_checker(_ROOT, f"v{_project_version()}", "--archive", archive)

    assert result.returncode != 0
    assert "archive is missing required files: solarmax/strings.json" in result.stderr


def test_release_checker_rejects_invalid_packaged_json(tmp_path: Path) -> None:
    """Malformed translation JSON must fail before the archive is tagged."""
    archive = tmp_path / "solarmax.zip"
    _write_release_archive(archive, "solarmax/translations/en.json")

    result = _run_release_checker(_ROOT, f"v{_project_version()}", "--archive", archive)

    assert result.returncode != 0
    assert (
        "archive contains invalid JSON: solarmax/translations/en.json" in result.stderr
    )
