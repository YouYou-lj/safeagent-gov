"""Private, path-safe PromptShield policy loader."""

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from safeagent_gov.errors import PolicyConfigurationError, PolicyNotFoundError

POLICY_PATH = Path(__file__).resolve().parents[1] / "policies" / "prompt_attack_rules.yaml"
CLASSIFIER_PATH = Path(__file__).resolve().parents[1] / "policies" / "classifier_model.yaml"


@lru_cache(maxsize=1)
def load_prompt_policy() -> dict[str, Any]:
    if not POLICY_PATH.is_file():
        raise PolicyNotFoundError(f"Policy not found: {POLICY_PATH.name}")
    with POLICY_PATH.open("r", encoding="utf-8") as handle:
        policy = yaml.safe_load(handle) or {}
    if not isinstance(policy, dict) or "prompt_injection" not in policy:
        raise PolicyConfigurationError("PromptShield policy is missing prompt_injection rules")
    return policy


def reload_prompt_policy() -> None:
    load_prompt_policy.cache_clear()
    load_classifier_model.cache_clear()


@lru_cache(maxsize=1)
def load_classifier_model() -> dict[str, Any]:
    if not CLASSIFIER_PATH.is_file():
        raise PolicyNotFoundError(f"Policy not found: {CLASSIFIER_PATH.name}")
    with CLASSIFIER_PATH.open("r", encoding="utf-8") as handle:
        model = yaml.safe_load(handle) or {}
    if not isinstance(model, dict) or "feature_lexicons" not in model or "categories" not in model:
        raise PolicyConfigurationError("PromptShield classifier model is missing features or categories")
    return model
