import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx

from trips.exceptions import (
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)


class JsonHttpClient:
    """Small HTTP adapter providing consistent retries and provider-safe errors."""

    def __init__(
        self,
        provider: str,
        *,
        http_client: httpx.Client | None = None,
        timeout_seconds: float = 10.0,
        max_retries: int = 1,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("HTTP timeout must be positive.")
        if max_retries < 0:
            raise ValueError("Maximum retries cannot be negative.")
        self.provider = provider
        self.http_client = http_client or httpx.Client()
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.sleeper = sleeper

    def get_json(self, url: str, params: Mapping[str, Any]) -> Any:
        response: httpx.Response | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.http_client.get(
                    url,
                    params=params,
                    timeout=self.timeout_seconds,
                    headers={"Accept": "application/json"},
                )
            except httpx.TimeoutException as exc:
                if attempt < self.max_retries:
                    self._backoff(attempt)
                    continue
                raise ProviderTimeoutError(
                    self.provider,
                    f"{self.provider} timed out.",
                    code="provider_timeout",
                    retryable=True,
                ) from exc
            except httpx.RequestError as exc:
                if attempt < self.max_retries:
                    self._backoff(attempt)
                    continue
                raise ProviderUnavailableError(
                    self.provider,
                    f"{self.provider} could not be reached.",
                    code="provider_unavailable",
                    retryable=True,
                ) from exc

            if response.status_code == 429 and attempt < self.max_retries:
                self._backoff(attempt)
                continue
            if response.status_code >= 500 and attempt < self.max_retries:
                self._backoff(attempt)
                continue
            break

        if response is None:  # pragma: no cover - defensive invariant
            raise ProviderUnavailableError(
                self.provider,
                f"{self.provider} did not return a response.",
                code="provider_unavailable",
                retryable=True,
            )

        self._raise_for_status(response)
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderResponseError(
                self.provider,
                f"{self.provider} returned invalid JSON.",
                code="invalid_provider_response",
                status_code=response.status_code,
            ) from exc

    def _backoff(self, attempt: int) -> None:
        self.sleeper(0.2 * (attempt + 1))

    def _raise_for_status(self, response: httpx.Response) -> None:
        status_code = response.status_code
        if 200 <= status_code < 300:
            return
        if status_code in {401, 403}:
            raise ProviderAuthenticationError(
                self.provider,
                f"{self.provider} rejected the configured credentials.",
                code="provider_authentication_failed",
                status_code=status_code,
            )
        if status_code == 429:
            retry_after = response.headers.get("Retry-After")
            retry_after_seconds = int(retry_after) if retry_after and retry_after.isdigit() else None
            raise ProviderRateLimitError(
                self.provider,
                f"{self.provider} rate limit exceeded.",
                code="provider_rate_limited",
                status_code=status_code,
                retryable=True,
                retry_after_seconds=retry_after_seconds,
            )
        if status_code >= 500:
            raise ProviderUnavailableError(
                self.provider,
                f"{self.provider} is temporarily unavailable.",
                code="provider_unavailable",
                status_code=status_code,
                retryable=True,
            )
        raise ProviderRequestError(
            self.provider,
            f"{self.provider} rejected the request.",
            code="provider_request_rejected",
            status_code=status_code,
        )
