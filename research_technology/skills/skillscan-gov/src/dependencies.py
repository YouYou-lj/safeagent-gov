"""Offline dependency/SBOM extraction and versioned risk-snapshot matching."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

import yaml
from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version

SNAPSHOT_PATH = Path(__file__).resolve().parents[1] / "policies" / "dependency_risk_snapshot.yaml"


def _component(ecosystem: str, name: str, version: str | None, source_file: str, declared_license: str | None = None) -> dict[str, Any]:
    normalized = name.casefold().replace("_", "-")
    suffix = f"@{version}" if version else ""
    return {
        "ecosystem": ecosystem,
        "name": normalized,
        "version": version,
        "purl": f"pkg:{ecosystem}/{normalized}{suffix}",
        "source_file": source_file,
        "declared_license": declared_license,
    }


def _exact_version(requirement: Requirement) -> str | None:
    exact = [item.version for item in requirement.specifier if item.operator == "==" and "*" not in item.version]
    return exact[0] if len(exact) == 1 else None


def _requirements(path: Path, relative: str) -> list[dict[str, Any]]:
    output = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(("-r", "--")):
            continue
        try:
            requirement = Requirement(line)
        except InvalidRequirement:
            continue
        output.append(_component("pypi", requirement.name, _exact_version(requirement), relative))
    return output


def _pyproject(path: Path, relative: str) -> tuple[list[dict[str, Any]], str | None]:
    payload = tomllib.loads(path.read_text(encoding="utf-8", errors="strict"))
    project = payload.get("project", {})
    license_value = project.get("license")
    if isinstance(license_value, dict):
        license_value = license_value.get("text") or license_value.get("file")
    output = []
    for raw in project.get("dependencies", []):
        try:
            requirement = Requirement(raw)
        except InvalidRequirement:
            continue
        output.append(_component("pypi", requirement.name, _exact_version(requirement), relative))
    poetry = payload.get("tool", {}).get("poetry", {})
    for name, constraint in poetry.get("dependencies", {}).items():
        if name.casefold() == "python":
            continue
        version = constraint if isinstance(constraint, str) and re.fullmatch(r"\d+(?:\.\d+)*", constraint) else None
        output.append(_component("pypi", name, version, relative))
    return output, str(license_value) if license_value else None


def _package_json(path: Path, relative: str) -> tuple[list[dict[str, Any]], str | None]:
    payload = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    license_value = payload.get("license")
    output = []
    for section in ("dependencies", "optionalDependencies", "peerDependencies", "devDependencies"):
        for name, constraint in payload.get(section, {}).items():
            version = constraint if isinstance(constraint, str) and re.fullmatch(r"\d+(?:\.\d+)*", constraint) else None
            output.append(_component("npm", name, version, relative, str(license_value) if license_value else None))
    return output, str(license_value) if license_value else None


def _package_lock(path: Path, relative: str) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    output = []
    packages = payload.get("packages", {})
    if packages:
        for location, record in packages.items():
            if not location.startswith("node_modules/"):
                continue
            name = location.removeprefix("node_modules/")
            output.append(_component("npm", name, record.get("version"), relative, record.get("license")))
    else:
        for name, record in payload.get("dependencies", {}).items():
            output.append(_component("npm", name, record.get("version"), relative))
    return output


def build_sbom(root: Path, files: list[Path]) -> dict[str, Any]:
    components: list[dict[str, Any]] = []
    package_licenses: list[str] = []
    errors: list[dict[str, str]] = []
    for path in files:
        relative = str(path.relative_to(root)) if root.is_dir() else path.name
        try:
            if path.name in {"requirements.txt", "requirements.lock"} or path.name.endswith("-requirements.txt"):
                components.extend(_requirements(path, relative))
            elif path.name == "pyproject.toml":
                found, license_value = _pyproject(path, relative)
                components.extend(found)
                if license_value:
                    package_licenses.append(license_value)
            elif path.name == "package.json":
                found, license_value = _package_json(path, relative)
                components.extend(found)
                if license_value:
                    package_licenses.append(license_value)
            elif path.name in {"package-lock.json", "npm-shrinkwrap.json"}:
                components.extend(_package_lock(path, relative))
        except (OSError, UnicodeError, json.JSONDecodeError, tomllib.TOMLDecodeError, ValueError) as exc:
            errors.append({"file": relative, "error_type": type(exc).__name__})
    unique: dict[tuple[str, str, str | None], dict[str, Any]] = {}
    for item in components:
        unique[(item["ecosystem"], item["name"], item["version"])] = item
    ordered = sorted(unique.values(), key=lambda item: (item["ecosystem"], item["name"], item["version"] or ""))
    return {
        "format": "CycloneDX-inspired-minimal",
        "components": ordered,
        "component_count": len(ordered),
        "dependencies": [{"from": "package:root", "to": item["purl"], "relationship": "depends_on"} for item in ordered],
        "declared_licenses": sorted(set(package_licenses)),
        "parse_errors": errors,
    }


def match_dependency_risks(sbom: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    snapshot = yaml.safe_load(SNAPSHOT_PATH.read_text(encoding="utf-8")) or {}
    evidence: list[dict[str, Any]] = []
    vulnerabilities = {
        (item["ecosystem"], item["package"].casefold()): item for item in snapshot.get("vulnerabilities", [])
    }
    malicious = {
        ecosystem: {name.casefold() for name in names}
        for ecosystem, names in snapshot.get("malicious_packages", {}).items()
    }
    typosquats = {
        ecosystem: {name.casefold(): target for name, target in mapping.items()}
        for ecosystem, mapping in snapshot.get("typosquats", {}).items()
    }
    high_capability = {
        ecosystem: {name.casefold() for name in names}
        for ecosystem, names in snapshot.get("known_high_capability", {}).items()
    }
    for component in sbom["components"]:
        ecosystem = component["ecosystem"]
        name = component["name"].casefold()
        base = {
            "file": component["source_file"],
            "line": 1,
            "column": 1,
            "symbol": name,
            "api": component["purl"],
            "parser": "dependency_snapshot",
        }
        if name in malicious.get(ecosystem, set()):
            evidence.append(
                {**base, "category": "malicious_dependency", "detail": "命中离线恶意包快照", "confidence": 0.99}
            )
        if name in typosquats.get(ecosystem, {}):
            evidence.append(
                {
                    **base,
                    "category": "typosquat_dependency",
                    "detail": f"疑似拼写劫持，可能目标为 {typosquats[ecosystem][name]}",
                    "confidence": 0.98,
                }
            )
        if name in high_capability.get(ecosystem, set()):
            evidence.append(
                {**base, "category": "risky_dependencies", "detail": "依赖具备高风险系统能力", "confidence": 0.8}
            )
        vulnerability = vulnerabilities.get((ecosystem, name))
        version = component.get("version")
        if vulnerability and version:
            try:
                affected = Version(version) in SpecifierSet(vulnerability["affected"])
            except (InvalidVersion, ValueError):
                affected = False
            if affected:
                evidence.append(
                    {
                        **base,
                        "category": "vulnerable_dependency",
                        "detail": f"{','.join(vulnerability['ids'])}；受影响范围 {vulnerability['affected']}",
                        "confidence": 0.99,
                    }
                )
    return evidence, str(snapshot.get("version", "unknown"))
