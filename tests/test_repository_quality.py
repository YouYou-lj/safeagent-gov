from __future__ import annotations

import json
from pathlib import Path

from scripts.check_markdown_links import check_markdown_links
from scripts.check_repository_index import check_repository_index
from scripts.generate_technical_manifest import build_documents

ROOT = Path(__file__).resolve().parents[1]


def test_repository_markdown_links_resolve() -> None:
    assert check_markdown_links(ROOT) == []


def test_review_index_and_package_boundaries_are_valid() -> None:
    assert check_repository_index(ROOT) == []


def test_technical_manifests_are_current_and_deterministic() -> None:
    sbom, manifest = build_documents(ROOT)
    second_sbom, second_manifest = build_documents(ROOT)

    assert sbom == second_sbom
    assert manifest == second_manifest
    assert sbom["bomFormat"] == "CycloneDX"
    assert sbom["specVersion"] == "1.6"
    assert len(sbom["components"]) >= 70
    assert manifest["reproducibility"]["source_file_count"] >= 100
    evidence_root = ROOT / "research_technology" / "evidence" / "technical"
    assert json.loads((evidence_root / "sbom.cdx.json").read_text(encoding="utf-8")) == sbom
    assert json.loads((evidence_root / "technical_manifest.json").read_text(encoding="utf-8")) == manifest
