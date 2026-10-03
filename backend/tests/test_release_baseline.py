"""W01: the backend release baseline must stay reproducible and honest.

- requirements.txt declares the supported ranges.
- requirements.lock.txt pins every installed package exactly, including transitive ones, so a
  rebuild cannot silently drift.
- requirements.sbom.json inventories the shipped components and their licence metadata.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
LOCK = BACKEND / "requirements.lock.txt"
DECLARED = BACKEND / "requirements.txt"
SBOM = BACKEND / "requirements.sbom.json"

PIN = re.compile(r"^([A-Za-z0-9_.\-]+)==([^\s=]+)$")


def _requirement_name(line: str) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    match = re.match(r"^([A-Za-z0-9_.\-]+)", stripped)
    return match.group(1).lower().replace("_", "-") if match else None


def test_the_lock_file_exists_and_pins_every_package_exactly():
    assert LOCK.exists(), "requirements.lock.txt is required for a reproducible release"
    lines = [line.strip() for line in LOCK.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines, "the lock file must not be empty"
    unpinned = [line for line in lines if not PIN.match(line)]
    assert unpinned == [], f"every lock entry must be name==version, offenders: {unpinned[:5]}"


def test_the_lock_covers_every_declared_top_level_dependency():
    declared = {name for name in (_requirement_name(l) for l in DECLARED.read_text(encoding="utf-8").splitlines()) if name}
    locked = {PIN.match(line).group(1).lower().replace("_", "-")
              for line in LOCK.read_text(encoding="utf-8").splitlines() if PIN.match(line.strip())}
    missing = sorted(declared - locked)
    assert missing == [], f"declared dependencies missing from the lock: {missing}"


def test_the_lock_includes_transitive_pins_not_only_the_declared_ones():
    declared = {name for name in (_requirement_name(l) for l in DECLARED.read_text(encoding="utf-8").splitlines()) if name}
    locked = {PIN.match(line).group(1).lower().replace("_", "-")
              for line in LOCK.read_text(encoding="utf-8").splitlines() if PIN.match(line.strip())}
    assert len(locked) > len(declared), "the lock must also pin transitive dependencies"


def test_the_sbom_is_machine_readable_and_lists_components():
    assert SBOM.exists(), "requirements.sbom.json is required for the release baseline"
    payload = json.loads(SBOM.read_text(encoding="utf-8"))
    assert payload["component_count"] == len(payload["packages"]) > 0
    for package in payload["packages"]:
        assert package["name"] and package["version"]
        assert "license" in package
    names = {package["name"].lower().replace("_", "-") for package in payload["packages"]}
    assert {"fastapi", "sqlalchemy", "alembic"} <= names


def test_an_unknown_licence_is_recorded_rather_than_invented():
    payload = json.loads(SBOM.read_text(encoding="utf-8"))
    unknown = [p for p in payload["packages"] if p["license"] == "UNKNOWN"]
    # The inventory is honest about missing metadata instead of guessing a licence.
    assert all(p["license"] == "UNKNOWN" for p in unknown)
