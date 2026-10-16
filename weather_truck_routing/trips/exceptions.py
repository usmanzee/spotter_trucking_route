class ProviderError(RuntimeError):
    """Base error raised when an external provider cannot fulfill a request."""

    def __init__(
        self,
        provider: str,
        message: str,
        *,
        code: str = "provider_error",
        status_code: int | None = None,
        retryable: bool = False,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.code = code
        self.status_code = status_code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


class ProviderConfigurationError(ProviderError):
    pass


class ProviderAuthenticationError(ProviderError):
    pass


class ProviderRateLimitError(ProviderError):
    pass


class ProviderRequestError(ProviderError):
    pass


class ProviderResponseError(ProviderError):
    pass


class ProviderUnavailableError(ProviderError):
    pass


class ProviderTimeoutError(ProviderError):
    pass


class TripAnalysisError(RuntimeError):
    """A user-facing trip-analysis failure not caused by serializer validation."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 422,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.details = details or {}
