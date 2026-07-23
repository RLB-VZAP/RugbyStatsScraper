"""Thin async GraphQL client for the United Rugby Championship data API."""

import asyncio
import logging
from types import TracebackType
from typing import Any, Protocol, Self, runtime_checkable

from curl_cffi.requests import AsyncSession

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class ScraperError(RuntimeError):
    """Raised when the source API can't be reached or returns errors."""


@runtime_checkable
class AsyncPoster(Protocol):
    """The slice of `curl_cffi.requests.AsyncSession` this client needs."""

    async def post(self, url: str, **kwargs: Any) -> Any: ...


class GraphQLClient:
    """Posts queries to the URC GraphQL endpoint.

    Two hurdles sit in front of this endpoint, and both shape the code here:

    1. Cloudflare serves a JS challenge to clients whose TLS fingerprint isn't
       a real browser's. Python's stdlib TLS (and therefore plain httpx or
       requests) gets a 403 "Just a moment..." page every time. `curl_cffi`
       impersonates Chrome's fingerprint, which gets through - that's the only
       reason it's a dependency rather than httpx, which the rest of the
       project uses.
    2. The origin also checks Origin/Referer/User-Agent and 403s a bare POST.

    Don't swap the session or strip the headers without re-testing against the
    live endpoint.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        session: AsyncPoster | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._session = session
        self._owns_session = session is None

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Accept-Language": "en-GB,en;q=0.9",
            "Origin": self._settings.stats_base_url,
            "Referer": f"{self._settings.stats_base_url}/",
            "User-Agent": self._settings.user_agent,
        }

    async def __aenter__(self) -> Self:
        if self._session is None:
            self._session = AsyncSession(impersonate=self._settings.impersonate)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    async def execute(
        self, query: str, variables: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Run a query and return its `data` payload."""
        if self._session is None:
            raise ScraperError("GraphQLClient must be used as an async context manager")

        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        last_error: Exception | None = None
        for attempt in range(1, self._settings.max_retries + 1):
            try:
                response = await self._session.post(
                    self._settings.graphql_url,
                    json=payload,
                    headers=self._headers,
                    timeout=self._settings.request_timeout,
                )
                response.raise_for_status()
                body = response.json()
            except ScraperError:
                raise
            except Exception as exc:  # noqa: BLE001 - transport errors vary by backend
                last_error = exc
                logger.warning(
                    "GraphQL request failed (attempt %s/%s): %s",
                    attempt,
                    self._settings.max_retries,
                    exc,
                )
                if attempt < self._settings.max_retries:
                    await asyncio.sleep(self._settings.retry_backoff * attempt)
                continue

            if body.get("errors"):
                messages = "; ".join(
                    error.get("message", str(error)) for error in body["errors"]
                )
                raise ScraperError(f"GraphQL returned errors: {messages}")

            data = body.get("data")
            if data is None:
                raise ScraperError("GraphQL response contained no data")
            return data

        raise ScraperError(
            f"GraphQL request failed after {self._settings.max_retries} attempts"
        ) from last_error
