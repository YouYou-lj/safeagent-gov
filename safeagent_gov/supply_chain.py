"""Public SkillScan-Gov API."""

from importlib import import_module

scan_skill_package = import_module("skills.skillscan-gov.src.scanner").scan_skill_package

__all__ = ["scan_skill_package"]
