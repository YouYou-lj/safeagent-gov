"""Stable AgentSecEval import path backed by ``research_technology/benchmarks``."""

from pathlib import Path

__path__.append(str(Path(__file__).resolve().parents[1] / "research_technology" / "benchmarks"))
