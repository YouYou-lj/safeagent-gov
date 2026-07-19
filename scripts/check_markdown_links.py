"""Validate repository-local links in Markdown documentation."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".uv-cache",
    ".uv-python",
    ".venv",
    "__pycache__",
    "node_modules",
}
LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\((?P<target><[^>]+>|[^)\s]+)(?:\s+['\"][^)]*['\"])?\)")
FENCE_PATTERN = re.compile(r"^\s*(```|~~~)")
REMOTE_SCHEMES = {"data", "http", "https", "mailto"}
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


@dataclass(frozen=True)
class BrokenLink:
    source: Path
    line: int
    target: str
    reason: str


def _markdown_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*.md")
        if not any(part in EXCLUDED_PARTS for part in path.relative_to(root).parts)
    )


def _local_target(source: Path, raw_target: str, root: Path) -> tuple[Path | None, str | None]:
    target = raw_target.removeprefix("<").removesuffix(">")
    parsed = urlsplit(target)
    if parsed.scheme.lower() in REMOTE_SCHEMES or target.startswith("#"):
        return None, None
    if parsed.scheme or parsed.netloc:
        return None, None
    if not parsed.path:
        return None, None

    decoded = unquote(parsed.path)
    candidate = (source.parent / decoded).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return candidate, "target escapes the repository"
    return candidate, None


def check_markdown_links(root: Path = ROOT) -> list[BrokenLink]:
    broken: list[BrokenLink] = []
    for source in _markdown_files(root):
        in_fence = False
        for line_number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), start=1):
            if FENCE_PATTERN.match(line):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            for match in LINK_PATTERN.finditer(line):
                raw_target = match.group("target")
                candidate, error = _local_target(source, raw_target, root)
                if error:
                    broken.append(BrokenLink(source, line_number, raw_target, error))
                elif (
                    candidate is not None
                    and not candidate.exists()
                    and not any(
                        optional == candidate.relative_to(root)
                        or optional in candidate.relative_to(root).parents
                        for optional in OPTIONAL_LOCAL_ROOTS
                    )
                ):
                    broken.append(BrokenLink(source, line_number, raw_target, "target does not exist"))
    return broken


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    broken = check_markdown_links(root)
    if broken:
        for item in broken:
            source = item.source.relative_to(root)
            print(f"{source}:{item.line}: {item.target}: {item.reason}")
        raise SystemExit(1)
    print(f"Markdown link check passed ({len(_markdown_files(root))} files).")


if __name__ == "__main__":
    sys.exit(main())
