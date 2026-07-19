"""B1 token-matching baseline retained for reproducible ablation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .policy_loader import load_scan_policy

TEXT_SUFFIXES = {".py", ".js", ".ts", ".mjs", ".cjs", ".sh", ".md", ".txt", ".yaml", ".yml", ".json"}


def scan_token_baseline(root: Path) -> dict[str, Any]:
    """Run the original case-insensitive substring scanner on an extracted root."""
    rules = load_scan_policy()
    files = [root] if root.is_file() else [path for path in root.rglob("*") if path.is_file()]
    category_hits: dict[str, list[str]] = {}
    scanned_files = 0
    for path in files:
        if path.suffix.casefold() not in TEXT_SUFFIXES or path.stat().st_size > 1_000_000:
            continue
        content = path.read_text(encoding="utf-8", errors="ignore")
        scanned_files += 1
        lowered = content.casefold()
        for category, tokens in rules.get("dangerous_api", {}).items():
            hits = [token for token in tokens if token.casefold() in lowered]
            if hits:
                category_hits.setdefault(category, []).extend(f"{path.name}: {token}" for token in hits)
    score = min(100, sum(int(rules.get("risk_score", {}).get(category, 0)) for category in category_hits))
    return {
        "risk_score": score,
        "categories": sorted(category_hits),
        "category_hits": category_hits,
        "scanned_files": scanned_files,
    }
