"""Provider failures shared by the adapters and the worker."""


class ProviderError(RuntimeError):
    def __init__(self, code="provider_unavailable", retry_after=30, ambiguous=False):
        super().__init__(code)
        self.retry_after = retry_after
        self.ambiguous = ambiguous


class ConfigurationError(ProviderError):
    pass
