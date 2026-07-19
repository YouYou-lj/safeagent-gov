"""Validate review navigation, innovation package boundaries and retired paths."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INLINE_CODE_PATTERN = re.compile(r"`(?P<value>[^`\n]+)`")
FENCE_PATTERN = re.compile(r"^\s*(```|~~~)")
INNOVATION_CONTRACT = ("README.md", "algorithm.md", "baselines.md", "evidence.md", "hypothesis.md")
SKILL_CONTRACT = ("SKILL.md", "manifest.yaml", "benchmarks", "examples", "policies", "src", "tests")
CORE_SKILLS = (
    "compliance-gov",
    "mcpguard-gov",
    "promptshield-gov",
    "sensitivedata-gov",
    "skillscan-gov",
    "traceaudit-gov",
)
MCP_CONTRACT = ("README.md", "adapters", "examples", "gateway", "policies/versions", "schemas", "servers", "tests")
MCP_API_CONTRACT = (
    "backend/api/mcp_api.py",
    "backend/database.py",
    "tests/test_audit_projections.py",
    "research_technology/skills/sensitivedata-gov/manifest.yaml",
    "research_technology/skills/compliance-gov/manifest.yaml",
)
EXTERNAL_INTEGRATION_CONTRACT = (
    "integrations/reference_agent/README.md",
    "integrations/reference_agent/main.py",
    "integrations/reference_agent/process.py",
)
ENVIRONMENT_CONTRACT = (
    ".gitattributes",
    ".python-version",
    ".uv-version",
    "LICENSE",
    "OPEN_SOURCE_NOTICE.md",
    "scripts/setup_uv_env.sh",
    "scripts/uv_run.sh",
    "uv.lock",
)
MODEL_GATEWAY_CONTRACT = (
    "configs/model_gateway.yaml",
    "safeagent_gov/model_gateway/contracts.py",
    "safeagent_gov/model_gateway/providers.py",
    "safeagent_gov/model_gateway/registry.py",
    "safeagent_gov/model_gateway/service.py",
    "backend/api/model_api.py",
    "agent_demo/planners/model_gateway.py",
    "research_technology/benchmarks/runners/eval_model_gateway.py",
    "tests/test_model_gateway.py",
    "research_technology/paper_sources/docs/model_gateway.md",
)
TASK_RUNTIME_CONTRACT = (
    "safeagent_gov/task_runtime/contracts.py",
    "safeagent_gov/task_runtime/dispatcher.py",
    "safeagent_gov/task_runtime/distributed.py",
    "safeagent_gov/task_runtime/redis_store.py",
    "safeagent_gov/task_runtime/dramatiq_workers.py",
    "safeagent_gov/task_runtime/worker_runtime.py",
    "safeagent_gov/task_runtime/handlers.py",
    "backend/api/task_api.py",
    "research_technology/benchmarks/runners/eval_task_runtime.py",
    "research_technology/benchmarks/runners/eval_distributed_recovery.py",
    "research_technology/reproducibility/scripts/distributed_task_probe.py",
    "tests/test_task_runtime.py",
    "tests/test_distributed_task_runtime.py",
    "research_technology/reproducibility/docker/docker-compose.yml",
    "research_technology/paper_sources/docs/task_runtime.md",
)
VUE_FRONTEND_CONTRACT = (
    "frontend-vue/package.json",
    "frontend-vue/package-lock.json",
    "frontend-vue/src/router/routes/common.ts",
    "frontend-vue/src/layout/AppLayout.vue",
    "frontend-vue/src/api/governance/index.ts",
    "frontend-vue/src/stores/auth.ts",
    "frontend-vue/tests/console.spec.ts",
    "research_technology/reproducibility/docker/Dockerfile.frontend-vue",
    "research_technology/reproducibility/docker/deploy/vue-nginx.conf",
    "research_technology/paper_sources/docs/frontend_vue.md",
)
SECURITY_WORKBENCH_CONTRACT = (
    "safeagent_gov/mcp_manifest.py",
    "backend/api/mcp_api.py",
    "backend/api/model_api.py",
    "frontend-vue/src/api/workbench/index.ts",
    "frontend-vue/src/views/security-workbench/index.vue",
    "frontend-vue/src/views/security-workbench/components/SkillInspectionPanel.vue",
    "frontend-vue/src/views/security-workbench/components/McpManifestPanel.vue",
    "frontend-vue/src/views/security-workbench/components/AgentInspectionPanel.vue",
    "frontend-vue/src/views/security-workbench/components/ModelSessionPanel.vue",
    "tests/test_mcp_manifest_scan.py",
    "tests/test_ephemeral_model_api.py",
    "frontend-vue/tests/workbench.spec.ts",
    "research_technology/paper_sources/docs/security_workbench.md",
)
CROSS_PLATFORM_DESKTOP_CONTRACT = (
    "research_technology/core/manifest.yaml",
    "desktop/package.json",
    "desktop/package-lock.json",
    "desktop/src-tauri/Cargo.toml",
    "desktop/src-tauri/Cargo.lock",
    "desktop/src-tauri/tauri.conf.json",
    "desktop/scripts/build_sidecar.py",
    "desktop/scripts/verify_sidecar.py",
    "desktop/mac/build-mac.sh",
    "desktop/mac/tauri.macos.conf.json",
    "desktop/mac/icons/icon.icns",
    "desktop/windows/build-windows.ps1",
    "desktop/windows/tauri.windows.conf.json",
    "desktop/windows/icons/icon.ico",
    "desktop/linux/build-linux.sh",
    "desktop/linux/tauri.linux.conf.json",
    "desktop/linux/icons/icon.png",
    "scripts/build_desktop.py",
    "scripts/setup_uv_env.py",
    ".github/workflows/build-macos.yml",
    ".github/workflows/build-windows.yml",
    ".github/workflows/build-linux.yml",
    ".github/workflows/release.yml",
    "research_technology/paper_sources/docs/cross_platform_architecture.md",
)
PLATFORM_ONLY_DESKTOP_ROOTS = ("mac", "windows", "linux")
FORBIDDEN_PLATFORM_CHILDREN = ("backend", "frontend-vue", "safeagent_gov", "src", "src-tauri")
OPTIONAL_LOCAL_ROOTS = (
    Path("agent_demo/data"),
    Path("research_technology/evidence/technical"),
    Path("research_technology/benchmarks/datasets"),
    Path("research_technology/benchmarks/failures"),
    Path("research_technology/benchmarks/results"),
    Path("research_technology/datasets"),
    Path("research_technology/evaluation/results"),
    Path("research_technology/evidence/reports"),
)
RETIRED_PATHS = (
    "agent_demo/langgraph_agent/tools.py",
    "agent_demo/mcp_servers",
    "backend/core/audit_logger.py",
    "backend/core/mcp_guard.py",
    "backend/core/policy_loader.py",
    "backend/core/prompt_shield.py",
    "backend/core/skill_scan.py",
    "research_technology/mcp/policies/tool_policy.yaml",
)


def _indexed_paths(index_path: Path) -> list[str]:
    paths: list[str] = []
    in_fence = False
    for line in index_path.read_text(encoding="utf-8").splitlines():
        if FENCE_PATTERN.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for match in INLINE_CODE_PATTERN.finditer(line):
            value = match.group("value").strip()
            parts = value.split()
            if not parts:
                continue
            candidate = parts[1] if parts[0] in {"python", "uvicorn"} and len(parts) > 1 else parts[0]
            candidate = candidate.rstrip(".,;，；")
            if "/" in candidate and not candidate.startswith(("http://", "https://")):
                paths.append(candidate)
    return paths


def check_repository_index(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    index_path = root / "PROJECT_MAP.md"
    for candidate in _indexed_paths(index_path):
        candidate_path = Path(candidate)
        if any(optional == candidate_path or optional in candidate_path.parents for optional in OPTIONAL_LOCAL_ROOTS):
            continue
        if any(character in candidate for character in "*?["):
            if not list(root.glob(candidate)):
                errors.append(f"PROJECT_MAP.md path pattern has no matches: {candidate}")
        elif not (root / candidate).exists():
            errors.append(f"PROJECT_MAP.md path does not exist: {candidate}")

    technology_root = root / "research_technology"
    innovation_dirs = sorted((technology_root / "innovations").glob("I[1-5]_*/"))
    if len(innovation_dirs) != 5:
        errors.append(f"expected 5 innovation directories, found {len(innovation_dirs)}")
    for directory in innovation_dirs:
        for required in INNOVATION_CONTRACT:
            if not (directory / required).exists():
                errors.append(f"innovation contract missing: {(directory / required).relative_to(root)}")

    for skill_name in CORE_SKILLS:
        directory = technology_root / "skills" / skill_name
        for required in SKILL_CONTRACT:
            if not (directory / required).exists():
                errors.append(f"skill contract missing: {(directory / required).relative_to(root)}")

    for required in MCP_CONTRACT:
        if not (technology_root / "mcp" / required).exists():
            errors.append(f"MCP contract missing: research_technology/mcp/{required}")

    for required in MCP_API_CONTRACT:
        if not (root / required).exists():
            errors.append(f"MCP/data-governance API contract missing: {required}")

    for required in EXTERNAL_INTEGRATION_CONTRACT:
        if not (root / required).exists():
            errors.append(f"external Agent integration contract missing: {required}")

    for required in ENVIRONMENT_CONTRACT:
        if not (root / required).exists():
            errors.append(f"environment/license contract missing: {required}")

    for required in MODEL_GATEWAY_CONTRACT:
        if not (root / required).exists():
            errors.append(f"Model Gateway contract missing: {required}")

    for required in TASK_RUNTIME_CONTRACT:
        if not (root / required).exists():
            errors.append(f"Task Runtime contract missing: {required}")

    for required in VUE_FRONTEND_CONTRACT:
        if not (root / required).exists():
            errors.append(f"Vue frontend contract missing: {required}")

    for required in SECURITY_WORKBENCH_CONTRACT:
        if not (root / required).exists():
            errors.append(f"security workbench contract missing: {required}")

    model_session_source = (
        root / "frontend-vue/src/views/security-workbench/components/ModelSessionPanel.vue"
    ).read_text(encoding="utf-8")
    for forbidden_storage in ("localStorage", "sessionStorage", "useAuthStore", "useStorage"):
        if forbidden_storage in model_session_source:
            errors.append(f"ephemeral model session must not persist credentials via {forbidden_storage}")

    for required in CROSS_PLATFORM_DESKTOP_CONTRACT:
        if not (root / required).exists():
            errors.append(f"cross-platform desktop contract missing: {required}")

    desktop_root = root / "desktop"
    if (desktop_root / "src-tauri" / "icons").exists():
        errors.append("platform-specific icons must not be stored in desktop/src-tauri/icons")
    gitignore = (root / ".gitignore").read_text(encoding="utf-8")
    if "/desktop/src-tauri/gen/" not in gitignore:
        errors.append("host-generated Tauri schemas must be ignored: desktop/src-tauri/gen")
    if (desktop_root / "binaries").exists():
        errors.append("redundant Sidecar navigation path reappeared: desktop/binaries")
    desktop_package = json.loads((desktop_root / "package.json").read_text(encoding="utf-8"))
    shared_scripts = "\n".join(desktop_package.get("scripts", {}).values())
    for platform_path in ("mac/", "windows/", "linux/"):
        if platform_path in shared_scripts:
            errors.append(f"shared desktop package script references platform implementation: {platform_path}")
    for platform_name in PLATFORM_ONLY_DESKTOP_ROOTS:
        platform_root = desktop_root / platform_name
        for forbidden in FORBIDDEN_PLATFORM_CHILDREN:
            if (platform_root / forbidden).exists():
                errors.append(
                    f"shared desktop source duplicated under platform directory: "
                    f"desktop/{platform_name}/{forbidden}"
                )

    if (root / "apps" / "desktop").exists():
        errors.append("retired desktop path reappeared: apps/desktop")

    for retired in RETIRED_PATHS:
        if (root / retired).exists():
            errors.append(f"retired compatibility path reappeared: {retired}")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    errors = check_repository_index(args.root.resolve())
    if errors:
        for error in errors:
            print(error)
        raise SystemExit(1)
    print("Repository review index and package boundaries are valid.")


if __name__ == "__main__":
    main()
