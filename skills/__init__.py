"""Compatibility namespace for the paper-oriented Skill implementations."""

from pathlib import Path

__path__.append(str(Path(__file__).resolve().parents[1] / "research_technology" / "skills"))
