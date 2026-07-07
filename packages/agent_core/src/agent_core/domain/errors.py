class ServiceError(Exception):
    """Base service error.

    Optional `error_code` is a stable machine-readable identifier returned to
    API clients (e.g. `circuit_open`, `provider_unavailable`). When omitted,
    error handlers fall back to a generic code.
    """

    def __init__(self, message: str = "", *, error_code: str | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code


class ValidationError(ServiceError):
    """Raised for validation-related problems."""


class NotFoundError(ServiceError):
    """Raised when an entity cannot be found."""


class ConfigurationError(ServiceError):
    """Raised when application configuration is invalid."""


class ProviderError(ServiceError):
    """Raised when an external provider call fails."""
