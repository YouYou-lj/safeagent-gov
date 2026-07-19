"""Process-wide trusted Skill Runtime shared by API and Agent orchestration."""

from safeagent_gov.paths import research_component_dir, resource_root

from .executor import SkillExecutor
from .registry import SkillRegistry

REPOSITORY_ROOT = resource_root()
DEFAULT_SKILL_REGISTRY = SkillRegistry(research_component_dir("skills", repository_root=REPOSITORY_ROOT))
DEFAULT_SKILL_REGISTRY.load()
DEFAULT_SKILL_EXECUTOR = SkillExecutor(DEFAULT_SKILL_REGISTRY)
