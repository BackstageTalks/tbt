class TBTError(Exception):
    """Base application error."""


class ConfigurationError(TBTError):
    """Raised when required configuration is missing."""


class ProviderError(TBTError):
    """Raised when an upstream data provider fails."""


class ModelNotReadyError(TBTError):
    """Raised when no trained production artifact is available."""
