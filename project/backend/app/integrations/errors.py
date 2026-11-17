"""Provider failures shared by the adapters and the worker."""


class ProviderError(RuntimeError):
    def __init__(
        self, code="provider_unavailable", retry_after=30, ambiguous=False, *, detail=""
    ):
        super().__init__(code)
        self.retry_after = retry_after
        self.ambiguous = ambiguous
        # Only adapter-authored text, never raw responses or exception messages.
        self.detail = detail


class ConfigurationError(ProviderError):
    pass


def describe_failure(error):
    """Explain controlled provider failures without exposing arbitrary payloads."""
    if isinstance(error, ProviderError):
        return f"{error}: {error.detail}" if error.detail else str(error)
    return type(error).__name__
