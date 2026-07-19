"""Private, path-safe SkillScan policy loader."""

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from safeagent_gov.errors import PolicyConfigurationError, PolicyNotFoundError

POLICY_PATH = Path(__file__).resolve().parents[1] / "policies" / "skill_scan_rules.yaml"


@lru_cache(maxsize=1)
def load_scan_policy() -> dict[str, Any]:
    if not POLICY_PATH.is_file():
        raise PolicyNotFoundError(f"Policy not found: {POLICY_PATH.name}")
    with POLICY_PATH.open("r", encoding="utf-8") as handle:
        policy = yaml.safe_load(handle) or {}
    if not isinstance(policy, dict) or "dangerous_api" not in policy:
        raise PolicyConfigurationError("SkillScan policy is missing dangerous_api rules")
    return policy


def reload_scan_policy() -> None:
    load_scan_policy.cache_clear()
