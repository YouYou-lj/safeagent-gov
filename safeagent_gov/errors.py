"""Shared exception hierarchy for public security interfaces."""


class SafeAgentError(Exception):
    """Base class for expected GovSafeAgent domain failures."""


class PolicyConfigurationError(SafeAgentError, ValueError):
    """A policy name, format, or value violates the fixed configuration contract."""


class PolicyNotFoundError(SafeAgentError, FileNotFoundError):
    """A required versioned policy cannot be loaded."""


class UnsafePackageError(SafeAgentError, ValueError):
    """A package violates scanner isolation or resource limits."""


class UnknownTraceError(SafeAgentError, KeyError):
    """A requested audit trace does not exist."""


class ApprovalStateError(SafeAgentError, ValueError):
    """An approval transition or decision is invalid."""


class UnsafeToolArgumentError(SafeAgentError, ValueError):
    """A tool argument escapes its declared simulator boundary."""


class CapabilityTicketError(SafeAgentError, ValueError):
    """A capability ticket is invalid, expired, out of scope or replayed."""


class TaskGraphError(SafeAgentError, ValueError):
    """A tool call diverges from the declared Agent task graph."""


class AuditIntegrityError(SafeAgentError, ValueError):
    """An audit chain, signature or required event field failed verification."""


class PlanningError(SafeAgentError, ValueError):
    """A planner is unavailable or returned an invalid, unsafe plan."""


class PlannerTransportError(PlanningError):
    """A transient remote planner transport failure that may be retried."""


class GraphifyConfigurationError(SafeAgentError, ValueError):
    """Capability graph input is invalid, stale, or crosses repository boundaries."""


class GraphifyNotBuiltError(SafeAgentError, RuntimeError):
    """A graph query was requested before a valid capability snapshot exists."""


class GraphifyNodeNotFoundError(SafeAgentError, KeyError):
    """A requested capability node does not exist in the active snapshot."""


class SkillRegistryError(SafeAgentError, ValueError):
    """A Skill manifest or registry snapshot violates the runtime contract."""


class SkillNotFoundError(SafeAgentError, KeyError):
    """A requested Skill is not present in the active registry snapshot."""


class SkillInputError(SafeAgentError, ValueError):
    """A Skill request is incomplete, unexpected or crosses a security boundary."""


class SkillOutputError(SafeAgentError, ValueError):
    """A Skill returned a value that does not satisfy its declared output contract."""


class SkillTransientError(SafeAgentError, RuntimeError):
    """A side-effect-free core Skill failed transiently and may be retried."""


class ModelGatewayConfigurationError(SafeAgentError, ValueError):
    """The model gateway registry or a provider profile is invalid."""


class ModelGatewayInputError(SafeAgentError, ValueError):
    """A model request violates the normalized gateway contract."""


class ModelGatewayBudgetError(SafeAgentError, ValueError):
    """No eligible model can satisfy the server-side cost budget."""


class ModelProviderError(SafeAgentError, RuntimeError):
    """A model provider failed or returned an invalid response."""


class ModelProviderTransportError(ModelProviderError):
    """A transient provider transport failure that may be retried or degraded."""


class ModelProviderResponseError(ModelProviderError, ValueError):
    """A provider response cannot be normalized and must not be retried."""


class ModelProviderUnavailableError(ModelProviderError):
    """All eligible model providers are disabled, open-circuited or unavailable."""


class TaskRuntimeError(SafeAgentError, RuntimeError):
    """The asynchronous task runtime cannot safely accept or finish a task."""


class TaskBackpressureError(TaskRuntimeError):
    """A bounded task pool rejected work because its queue is saturated."""


class TaskNotFoundError(TaskRuntimeError, KeyError):
    """A task identifier is absent from the local runtime store."""


class TaskTransientError(TaskRuntimeError):
    """A task handler failed transiently and may be retried within its bound."""
