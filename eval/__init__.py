"""Stable lightweight evaluation import path backed by the research archive."""

from pathlib import Path

__path__.append(str(Path(__file__).resolve().parents[1] / "research_technology" / "evaluation"))
