"""Network-only Duels.ink client."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import requests

from lorcana.duels.history_parser import parse_history_page
from lorcana.duels.types import HistoryPage
from lorcana.errors import LorcanaError

DUELS_BASE_URL = "https://duels.ink"
MATCH_HISTORY_URL = f"{DUELS_BASE_URL}/api/me/match-history"
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class DuelsClientError(LorcanaError):
    pass


class DuelsAuthenticationError(DuelsClientError):
    pass


class DuelsClient:
    def __init__(
        self,
        token: str,
        *,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_attempts: int = 5,
        initial_retry_seconds: float = 2.0,
        max_retry_seconds: float = 60.0,
    ) -> None:
        if not token.strip():
            raise ValueError("Duels token must not be empty")
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        self._token = token.strip()
        self.session = session or requests.Session()
        self.sleep = sleep
        self.max_attempts = max_attempts
        self.initial_retry_seconds = initial_retry_seconds
        self.max_retry_seconds = max_retry_seconds

    def _delay_for(self, response: requests.Response | None, attempt: int) -> float:
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                return float(retry_after)
        return min(self.initial_retry_seconds * (2 ** (attempt - 1)), self.max_retry_seconds)

    def _request(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        accept: str = "application/json",
        send_authorization: bool = True,
        timeout: float = 30,
    ) -> requests.Response:
        headers = {
            "Accept": accept,
            "Cache-Control": "no-cache, no-store, max-age=0",
            "Pragma": "no-cache",
            "User-Agent": "Lorcana-Team-Coach/1.0",
        }
        if send_authorization:
            headers["Authorization"] = f"Bearer {self._token}"

        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            response: requests.Response | None = None
            try:
                response = self.session.get(url, headers=headers, params=params, timeout=timeout)
            except (requests.Timeout, requests.ConnectionError) as error:
                last_error = error
                if attempt == self.max_attempts:
                    break
                self.sleep(self._delay_for(None, attempt))
                continue
            if response.status_code in RETRYABLE_STATUS_CODES:
                last_error = DuelsClientError(f"Duels returned HTTP {response.status_code}")
                if attempt == self.max_attempts:
                    break
                self.sleep(self._delay_for(response, attempt))
                continue
            try:
                response.raise_for_status()
            except requests.HTTPError as error:
                if response.status_code in {401, 403}:
                    raise DuelsAuthenticationError(
                        f"Duels authentication failed with HTTP {response.status_code}"
                    ) from error
                raise DuelsClientError(f"Duels returned HTTP {response.status_code}") from error
            return response
        if last_error is not None:
            raise DuelsClientError(f"Duels request failed after {self.max_attempts} attempts") from last_error
        raise DuelsClientError("Duels request retry loop exited unexpectedly")

    def fetch_history_page(self, cursor: str | None = None) -> HistoryPage:
        params: dict[str, Any] = {"format": "json", "_cb": str(int(time.time() * 1000))}
        if cursor:
            params["cursor"] = cursor
        response = self._request(MATCH_HISTORY_URL, params=params)
        try:
            payload = response.json()
        except ValueError as error:
            raise DuelsClientError("Duels returned invalid JSON for match history") from error
        try:
            return parse_history_page(payload)
        except ValueError as error:
            raise DuelsClientError(str(error)) from error

    def download_replay(self, replay_url: str) -> bytes:
        parsed = urlsplit(replay_url)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname:
            raise DuelsClientError("Duels replay URL is invalid")
        # Signed replay object URLs can legitimately use external storage. Never
        # leak the Duels bearer token to an external host.
        hostname = parsed.hostname.lower()
        trusted_for_auth = hostname == "duels.ink" or hostname.endswith(".duels.ink")
        response = self._request(
            replay_url,
            accept="*/*",
            send_authorization=trusted_for_auth,
        )
        if not response.content:
            raise DuelsClientError("Duels returned an empty replay artifact")
        return bytes(response.content)

    def close(self) -> None:
        self.session.close()
