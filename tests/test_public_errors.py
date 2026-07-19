from safeagent_gov.errors import (
    ApprovalStateError,
    PolicyConfigurationError,
    SafeAgentError,
    UnknownTraceError,
    UnsafePackageError,
    UnsafeToolArgumentError,
)


def test_domain_errors_share_one_public_base_type():
    error_types = (
        ApprovalStateError,
        PolicyConfigurationError,
        UnknownTraceError,
        UnsafePackageError,
        UnsafeToolArgumentError,
    )
    assert all(issubclass(error_type, SafeAgentError) for error_type in error_types)


def test_compatibility_error_categories_are_preserved():
    assert issubclass(UnknownTraceError, KeyError)
    assert issubclass(ApprovalStateError, ValueError)
    assert issubclass(UnsafePackageError, ValueError)
