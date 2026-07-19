"""Process-wide Model Gateway registry and runtime."""

from safeagent_gov.paths import resource_root

from .registry import ModelRegistry
from .service import ModelGateway

REPOSITORY_ROOT = resource_root()
DEFAULT_MODEL_REGISTRY = ModelRegistry(REPOSITORY_ROOT / "configs" / "model_gateway.yaml")
DEFAULT_MODEL_REGISTRY.load()
DEFAULT_MODEL_GATEWAY = ModelGateway(DEFAULT_MODEL_REGISTRY)
