"""Strict loader for the four in-scope government/enterprise scenarios."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

CATALOG_PATH = Path(__file__).with_name("catalog.yaml")


class ScenarioSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,79}$")
    title: str = Field(min_length=2, max_length=80)
    description: str = Field(min_length=2, max_length=500)
    allowed_user_roles: list[str] = Field(min_length=1, max_length=20)
    default_data_labels: list[str] = Field(min_length=1, max_length=10)
    expected_tools: list[str] = Field(default_factory=list, max_length=20)


class ScenarioCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    scenarios: list[ScenarioSpec] = Field(min_length=4, max_length=4)


@lru_cache(maxsize=1)
def load_scenarios() -> ScenarioCatalog:
    raw = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))
    catalog = ScenarioCatalog.model_validate(raw)
    identifiers = [item.scenario_id for item in catalog.scenarios]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("scenario_id values must be unique")
    return catalog


def list_scenarios() -> list[ScenarioSpec]:
    return list(load_scenarios().scenarios)


def get_scenario(scenario_id: str) -> ScenarioSpec:
    for scenario in load_scenarios().scenarios:
        if scenario.scenario_id == scenario_id:
            return scenario
    raise KeyError(f"unknown scenario: {scenario_id}")
