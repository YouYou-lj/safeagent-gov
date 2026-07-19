"""Generate deterministic CycloneDX SBOM and technical-version evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tomllib
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "research_technology" / "evidence" / "technical"
LOCK_FILES = ("requirements.lock", "requirements-dev.lock")
UV_LOCK_FILE = "uv.lock"
NPM_LOCK_FILES = ("frontend-vue/package-lock.json", "desktop/package-lock.json")
CARGO_LOCK_FILE = "desktop/src-tauri/Cargo.lock"
ENVIRONMENT_FILES = (".python-version", ".uv-version", "LICENSE", "OPEN_SOURCE_NOTICE.md")
SOURCE_ROOTS = (
    ".github/workflows",
    "agent_demo",
    "backend",
    "research_technology/benchmarks/runners",
    "configs",
    "research_technology/core",
    "desktop",
    "frontend-vue",
    "integrations",
    "research_technology/mcp",
    "safeagent_gov",
    "scripts",
    "research_technology/skills",
    "research_technology/evaluation",
    "research_technology/reproducibility",
    "tests",
)
SOURCE_SUFFIXES = {
    ".html",
    ".js",
    ".json",
    ".lock",
    ".mjs",
    ".nsi",
    ".plist",
    ".py",
    ".ps1",
    ".scss",
    ".sh",
    ".toml",
    ".ts",
    ".vue",
    ".yaml",
    ".yml",
}
ROOT_SOURCE_FILES = (
    "research_technology/reproducibility/docker/Dockerfile.backend",
    "research_technology/reproducibility/docker/Dockerfile.frontend-vue",
    "research_technology/reproducibility/docker/docker-compose.yml",
    "pyproject.toml",
)
EXCLUDED_PARTS = {
    ".build",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".uv-cache",
    ".uv-python",
    ".venv",
    "__pycache__",
    "coverage",
    "dist",
    "node_modules",
    "target",
}
LOCK_PATTERN = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+)==(?P<version>[^;\s]+)(?:\s*;\s*(?P<marker>.+))?$"
)
IMAGE_PATTERN = re.compile(r"^(?:FROM|\s*image:)\s+(?P<image>[^\s]+)", re.MULTILINE)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _parse_lock(path: Path) -> list[tuple[str, str]]:
    dependencies: list[tuple[str, str]] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = LOCK_PATTERN.fullmatch(line)
        if not match:
            raise ValueError(f"{path}:{line_number}: dependency is not exactly pinned")
        dependencies.append((match.group("name"), match.group("version")))
    return dependencies


def _parse_npm_lock(path: Path) -> list[tuple[str, str, bool, str]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("lockfileVersion") != 3 or not isinstance(raw.get("packages"), dict):
        raise ValueError(f"{path}: only npm lockfileVersion 3 is supported")
    dependencies: list[tuple[str, str, bool, str]] = []
    for package_path, package in raw["packages"].items():
        if not package_path or not isinstance(package, dict):
            continue
        name = package.get("name")
        if not isinstance(name, str):
            name = package_path.rsplit("node_modules/", maxsplit=1)[-1]
        version = package.get("version")
        if not name or not isinstance(version, str) or not version:
            raise ValueError(f"{path}: incomplete npm package entry: {package_path}")
        integrity = package.get("integrity", "")
        if not isinstance(integrity, str):
            raise ValueError(f"{path}: invalid integrity value: {package_path}")
        dependencies.append((name, version, bool(package.get("dev", False)), integrity))
    return sorted(dependencies)


def _yaml_summary(path: Path, root: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {
        "path": path.relative_to(root).as_posix(),
        "name": str(raw.get("name", path.stem)),
        "version": str(raw.get("version", "unspecified")),
        "sha256": _sha256(path),
    }


def _source_inventory(root: Path) -> tuple[list[dict[str, str]], str]:
    paths: list[Path] = []
    for source_root in SOURCE_ROOTS:
        base = root / source_root
        if not base.exists():
            continue
        paths.extend(
            path
            for path in base.rglob("*")
            if path.is_file()
            and path.suffix in SOURCE_SUFFIXES
            and not any(part in EXCLUDED_PARTS for part in path.relative_to(root).parts)
        )
    paths.extend(root / name for name in (*ROOT_SOURCE_FILES, UV_LOCK_FILE, *LOCK_FILES, *ENVIRONMENT_FILES))
    unique_paths = sorted(set(paths))
    inventory = [
        {"path": path.relative_to(root).as_posix(), "sha256": _sha256(path)} for path in unique_paths
    ]
    aggregate = hashlib.sha256()
    for item in inventory:
        aggregate.update(item["path"].encode())
        aggregate.update(b"\0")
        aggregate.update(item["sha256"].encode())
        aggregate.update(b"\n")
    return inventory, aggregate.hexdigest()


def _runtime_images(root: Path) -> list[str]:
    images: set[str] = set()
    for path in (
        root / "research_technology/reproducibility/docker/Dockerfile.backend",
        root / "research_technology/reproducibility/docker/Dockerfile.frontend-vue",
        root / "research_technology/reproducibility/docker/docker-compose.yml",
    ):
        images.update(match.group("image") for match in IMAGE_PATTERN.finditer(path.read_text(encoding="utf-8")))
    return sorted(image for image in images if "safeagent" not in image and (":" in image or "@" in image))


def build_documents(root: Path = ROOT) -> tuple[dict[str, Any], dict[str, Any]]:
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    lock_dependencies = {name: _parse_lock(root / name) for name in LOCK_FILES}
    lock_hashes = {name: _sha256(root / name) for name in LOCK_FILES}
    uv_lock = tomllib.loads((root / UV_LOCK_FILE).read_text(encoding="utf-8"))
    uv_lock_hash = _sha256(root / UV_LOCK_FILE)
    npm_lock_dependencies = {name: _parse_npm_lock(root / name) for name in NPM_LOCK_FILES}
    npm_lock_hashes = {name: _sha256(root / name) for name in NPM_LOCK_FILES}
    cargo_lock = tomllib.loads((root / CARGO_LOCK_FILE).read_text(encoding="utf-8"))
    cargo_lock_hash = _sha256(root / CARGO_LOCK_FILE)
    all_lock_hashes = {
        **lock_hashes,
        UV_LOCK_FILE: uv_lock_hash,
        **npm_lock_hashes,
        CARGO_LOCK_FILE: cargo_lock_hash,
    }

    component_map: dict[str, dict[str, Any]] = {}
    component_refs: set[str] = set()
    for lock_name, dependencies in lock_dependencies.items():
        scope = "required" if lock_name == "requirements.lock" else "optional"
        for name, version in dependencies:
            canonical_name = _canonical_name(name)
            reference = f"pkg:pypi/{canonical_name}@{version}"
            component_refs.add(reference)
            component = component_map.setdefault(
                reference,
                {
                    "type": "library",
                    "bom-ref": reference,
                    "name": name,
                    "version": version,
                    "purl": reference,
                    "scope": scope,
                    "properties": [],
                },
            )
            if scope == "required":
                component["scope"] = "required"
            property_item = {"name": "safeagent:lockfile", "value": lock_name}
            if property_item not in component["properties"]:
                component["properties"].append(property_item)

    for lock_name, dependencies in npm_lock_dependencies.items():
        for name, version, development, integrity in dependencies:
            encoded_name = quote(name, safe="/")
            reference = f"pkg:npm/{encoded_name}@{version}"
            component_refs.add(reference)
            component = component_map.setdefault(
                reference,
                {
                    "type": "library",
                    "bom-ref": reference,
                    "name": name,
                    "version": version,
                    "purl": reference,
                    "scope": "optional" if development else "required",
                    "properties": [],
                },
            )
            properties = [{"name": "safeagent:lockfile", "value": lock_name}]
            if integrity:
                properties.append({"name": "safeagent:npm-integrity", "value": integrity})
            for property_item in properties:
                if property_item not in component["properties"]:
                    component["properties"].append(property_item)
            if not development:
                component["scope"] = "required"

    cargo_dependencies = cargo_lock.get("package", [])
    for package in cargo_dependencies:
        name = str(package["name"])
        version = str(package["version"])
        reference = f"pkg:cargo/{quote(name, safe='')}@{version}"
        component_refs.add(reference)
        properties = [{"name": "safeagent:lockfile", "value": CARGO_LOCK_FILE}]
        checksum = package.get("checksum")
        if checksum:
            properties.append({"name": "safeagent:cargo-checksum", "value": str(checksum)})
        component_map.setdefault(
            reference,
            {
                "type": "library",
                "bom-ref": reference,
                "name": name,
                "version": version,
                "purl": reference,
                "scope": "required",
                "properties": properties,
            },
        )
    components = sorted(component_map.values(), key=lambda item: item["bom-ref"])

    serial_seed = f"{project['name']}:{project['version']}:{json.dumps(all_lock_hashes, sort_keys=True)}"
    application_ref = f"pkg:generic/{project['name']}@{project['version']}"
    sbom: dict[str, Any] = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, serial_seed)}",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "bom-ref": application_ref,
                "name": project["name"],
                "version": project["version"],
                "licenses": [
                    {
                        "license": {
                            "name": "PolyForm Noncommercial License 1.0.0",
                            "url": "https://polyformproject.org/licenses/noncommercial/1.0.0",
                        }
                    }
                ],
            },
            "properties": [
                {"name": f"safeagent:{name}:sha256", "value": digest}
                for name, digest in sorted(all_lock_hashes.items())
            ],
        },
        "components": components,
        "dependencies": [{"ref": application_ref, "dependsOn": sorted(component_refs)}],
    }

    inventory, source_digest = _source_inventory(root)
    technology_root = root / "research_technology"
    policy_manifests = sorted((technology_root / "mcp" / "policies" / "versions").glob("*.yaml"))
    dataset_manifests = sorted((technology_root / "benchmarks" / "datasets").glob("*/manifest.yaml"))
    evidence_results = sorted((technology_root / "benchmarks" / "results").glob("*.json"))
    model_gateway_path = root / "configs" / "model_gateway.yaml"
    model_gateway = yaml.safe_load(model_gateway_path.read_text(encoding="utf-8"))
    provider_profiles = [
        {
            "name": provider_id,
            "model": str(profile["model"]),
            "protocol": str(profile["protocol"]),
            "private_deployment": bool(profile["private_deployment"]),
            "enabled": bool(profile["enabled"]),
            "status": (
                "verified_offline_baseline"
                if profile["protocol"] == "internal" and profile["enabled"]
                else "profile_disabled_protocol_adapter_verified_not_claimed_as_live"
            ),
        }
        for provider_id, profile in sorted(model_gateway["providers"].items())
    ]
    technical_manifest: dict[str, Any] = {
        "schema_version": "1.0.0",
        "project": {"name": project["name"], "version": project["version"]},
        "reproducibility": {
            "python_target": (root / ".python-version").read_text(encoding="utf-8").strip(),
            "node_target": "24.3.0",
            "rust_target": "1.97.1 (native macOS/Windows/Linux target)",
            "uv_target": (root / ".uv-version").read_text(encoding="utf-8").strip(),
            "container_images": _runtime_images(root),
            "lockfiles": [
                {
                    "path": name,
                    "sha256": lock_hashes[name],
                    "dependency_count": len(lock_dependencies[name]),
                }
                for name in LOCK_FILES
            ]
            + [
                {
                    "path": UV_LOCK_FILE,
                    "sha256": uv_lock_hash,
                    "dependency_count": len(uv_lock.get("package", [])),
                },
            ]
            + [
                {
                    "path": name,
                    "sha256": npm_lock_hashes[name],
                    "dependency_count": len(npm_lock_dependencies[name]),
                }
                for name in NPM_LOCK_FILES
            ]
            + [
                {
                    "path": CARGO_LOCK_FILE,
                    "sha256": cargo_lock_hash,
                    "dependency_count": len(cargo_dependencies),
                }
            ],
            "source_file_count": len(inventory),
            "source_tree_sha256": source_digest,
        },
        "model_gateway_registry": {
            "path": model_gateway_path.relative_to(root).as_posix(),
            "version": str(model_gateway["version"]),
            "sha256": _sha256(model_gateway_path),
            "provider_count": len(provider_profiles),
        },
        "models": provider_profiles
        + [
            {
                "name": "SAFEAGENT_DIFY_WORKFLOW",
                "protocol": "external_dify_legacy_planning_only",
                "status": "configuration_required_not_claimed_as_live",
            },
            {
                "name": "safeagent-reference-tool-agent@1.0.0",
                "protocol": "vendor_neutral_external_agent_over_loopback_http",
                "status": "verified",
            },
        ],
        "external_integrations": [
            {
                "name": "safeagent-reference-tool-agent",
                "protocol_version": "1.0.0",
                "transport": "real_loopback_http_child_process",
                "execution_authority": False,
                "evidence": "research_technology/benchmarks/results/external_agent_integration_v1.json",
                "compatibility_claim": "vendor-neutral planning-only contract; not official Dify/OpenClaw protocol certification",
            }
        ],
        "policy_versions": [_yaml_summary(path, root) for path in policy_manifests],
        "dataset_versions": [_yaml_summary(path, root) for path in dataset_manifests],
        "evidence": [
            {"path": path.relative_to(root).as_posix(), "sha256": _sha256(path)} for path in evidence_results
        ],
    }
    return sbom, technical_manifest


def _json_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json_text(payload), encoding="utf-8")


def generate(root: Path = ROOT, output: Path = DEFAULT_OUTPUT) -> None:
    sbom, manifest = build_documents(root)
    _write_json(output / "sbom.cdx.json", sbom)
    _write_json(output / "technical_manifest.json", manifest)


def check_generated(root: Path = ROOT, output: Path = DEFAULT_OUTPUT) -> list[str]:
    sbom, manifest = build_documents(root)
    expected = {"sbom.cdx.json": sbom, "technical_manifest.json": manifest}
    stale: list[str] = []
    for name, payload in expected.items():
        path = output / name
        if not path.exists() or path.read_text(encoding="utf-8") != _json_text(payload):
            stale.append(name)
    return stale


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true", help="fail if committed outputs are stale")
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output.resolve() if args.output else root / "research_technology" / "evidence" / "technical"
    if args.check:
        stale = check_generated(root, output)
        if stale:
            raise SystemExit(f"Technical manifest is stale: {', '.join(stale)}")
        print("Technical SBOM and manifest are current.")
    else:
        generate(root, output)
        print(f"Generated {output / 'sbom.cdx.json'}")
        print(f"Generated {output / 'technical_manifest.json'}")


if __name__ == "__main__":
    main()
