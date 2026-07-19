"""Validated Agent planners; no planner has direct tool execution authority."""

from collections.abc import Mapping

from .protocol import Planner


def create_planner(
    mode: str | None = None,
    *,
    environment: Mapping[str, str] | None = None,
) -> Planner:
    """Lazily load the factory so adapters can import validation modules safely."""
    from .factory import create_planner as factory_create_planner

    return factory_create_planner(mode, environment=environment)


__all__ = ["Planner", "create_planner"]
