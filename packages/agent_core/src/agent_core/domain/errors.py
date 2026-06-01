class ServiceError(Exception):
    """Base service error."""


class ValidationError(ServiceError):
    """Raised for validation-related problems."""


class NotFoundError(ServiceError):
    """Raised when an entity cannot be found."""


class ConfigurationError(ServiceError):
    """Raised when application configuration is invalid."""


class ProviderError(ServiceError):
    """Raised when an external provider call fails."""
