"""External Agent platform adapters constrained to validated planning output."""

# Keep package import side-effect free. Adapters depend on planner validation,
# while the planner factory imports adapters; eager re-exports create a cycle.
__all__: list[str] = []
