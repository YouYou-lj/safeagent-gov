from pathlib import Path

import yaml
from mcp.servers.registry import list_registered_tools

MCP_ROOT = Path(__file__).resolve().parents[1]


def test_manifests_cover_exactly_the_public_registry():
    declared: set[str] = set()
    manifests = sorted((MCP_ROOT / "servers").glob("*/manifest.yaml"))
    assert len(manifests) == 6
    for manifest_path in manifests:
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        assert manifest["simulation_only"] is True
        assert manifest["version"] == "1.0.0"
        declared.update(manifest["capabilities"])
    assert declared == set(list_registered_tools())


def test_policy_covers_every_registered_tool():
    policy = yaml.safe_load((MCP_ROOT / "policies" / "versions" / "2.0.0.yaml").read_text(encoding="utf-8"))
    assert set(policy["tools"]) == set(list_registered_tools())
