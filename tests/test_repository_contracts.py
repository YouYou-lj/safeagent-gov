import re
from pathlib import Path

import yaml

from agent_demo.scenarios import load_scenarios

ROOT = Path(__file__).resolve().parents[1]
SKILLS = (
    "promptshield-gov",
    "mcpguard-gov",
    "skillscan-gov",
    "traceaudit-gov",
    "sensitivedata-gov",
    "compliance-gov",
)
INNOVATIONS = (
    "I1_provenance_risk_graph",
    "I2_taint_capability_guard",
    "I3_behavior_permission_graph",
    "I4_verifiable_trace",
    "I5_graphify_capability_graph",
)


def test_every_skill_obeys_the_standard_package_contract():
    required_dirs = ("src", "policies", "tests", "examples", "benchmarks")
    for name in SKILLS:
        package = ROOT / "research_technology" / "skills" / name
        assert (package / "SKILL.md").is_file(), name
        assert (package / "README.md").is_file(), name
        manifest_path = package / "manifest.yaml"
        assert manifest_path.is_file(), name
        assert all((package / item).is_dir() for item in required_dirs), name
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        assert manifest["category"] in {"security", "business"}
        assert manifest["execution_mode"] in {"mandatory", "routed"}
        assert manifest["trigger_stages"]
        assert 0.01 <= float(manifest["timeout_seconds"]) <= 120
        assert 0 <= int(manifest["retries"]) <= 3
        assert manifest["failure_policy"] in {"block", "continue_with_warning"}
        assert isinstance(manifest["enabled"], bool)
        assert set(manifest["required_inputs"]) <= set(manifest["inputs"])
        assert set(manifest["required_outputs"]) <= set(manifest["outputs"])
        if manifest["execution_mode"] == "mandatory":
            assert manifest["failure_policy"] == "block"
        module_path = manifest["entrypoint"].split(":", 1)[0]
        assert (package / module_path).is_file(), manifest["entrypoint"]
        assert re.fullmatch(r"\d+\.\d+\.\d+", str(manifest["version"]))


def test_every_innovation_has_a_complete_evidence_contract():
    required = ("README.md", "hypothesis.md", "algorithm.md", "baselines.md", "ablations.yaml", "evidence.md")
    for name in INNOVATIONS:
        evidence = ROOT / "research_technology" / "innovations" / name
        assert all((evidence / item).is_file() for item in required), name
        ablations = yaml.safe_load((evidence / "ablations.yaml").read_text(encoding="utf-8"))
        assert ablations["innovation"].startswith(name.split("_", 1)[0])
        assert ablations["ablations"]


def test_exactly_four_versioned_government_scenarios_are_registered():
    catalog = load_scenarios()
    assert catalog.version == "1.0.0"
    assert {item.scenario_id for item in catalog.scenarios} == {
        "government_office",
        "knowledge_service",
        "process_handling",
        "operations_collaboration",
    }
