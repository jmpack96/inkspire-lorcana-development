"""HTTP client for Play Hub.  Fetching only; no parsing or persistence."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import requests

from lorcana.errors import LorcanaError

PLAYHUB_WEB_BASE = "https://tcg.ravensburgerplay.com"
PLAYHUB_API_BASE = "https://api.cloudflare.ravensburgerplay.com/hydraproxy"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
    ),
    "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
}
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class PlayHubClientError(LorcanaError):
    """A Play Hub request or response could not be completed safely."""


class PlayHubClient:
    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        request_delay_seconds: float = 0.51,
        max_attempts: int = 6,
        initial_retry_seconds: float = 5,
        max_retry_seconds: float = 120,
        page_size: int = 100,
    ):
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        if page_size <= 0:
            raise ValueError("page_size must be positive")
        self.session = session or requests.Session()
        self.sleep = sleep
        self.request_delay_seconds = request_delay_seconds
        self.max_attempts = max_attempts
        self.initial_retry_seconds = initial_retry_seconds
        self.max_retry_seconds = max_retry_seconds
        self.page_size = page_size

    def _delay_for(self, response: requests.Response | None, attempt: int) -> float:
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                return float(retry_after)
        return min(self.initial_retry_seconds * (2 ** (attempt - 1)), self.max_retry_seconds)

    def _get(self, url: str, *, params: dict[str, Any] | None = None, timeout: float = 30) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            response: requests.Response | None = None
            try:
                response = self.session.get(
                    url,
                    params=params,
                    headers=DEFAULT_HEADERS,
                    timeout=timeout,
                )
            except (requests.Timeout, requests.ConnectionError) as error:
                last_error = error
                if attempt == self.max_attempts:
                    break
                self.sleep(self._delay_for(None, attempt))
                continue

            if response.status_code in RETRYABLE_STATUS_CODES:
                last_error = PlayHubClientError(f"Play Hub returned HTTP {response.status_code}")
                if attempt == self.max_attempts:
                    break
                self.sleep(self._delay_for(response, attempt))
                continue

            try:
                response.raise_for_status()
            except requests.HTTPError as error:
                raise PlayHubClientError(f"Play Hub returned HTTP {response.status_code}") from error
            return response

        if isinstance(last_error, PlayHubClientError):
            raise last_error
        if last_error is not None:
            raise PlayHubClientError(f"Play Hub request failed after {self.max_attempts} attempts") from last_error
        raise PlayHubClientError("Play Hub request retry loop exited unexpectedly")

    @staticmethod
    def _json_object(response: requests.Response, *, context: str) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as error:
            raise PlayHubClientError(f"Play Hub returned invalid JSON for {context}") from error
        if not isinstance(data, dict):
            raise PlayHubClientError(f"Play Hub returned a non-object JSON payload for {context}")
        return data

    def fetch_event_html(self, event_id: int) -> str:
        response = self._get(f"{PLAYHUB_WEB_BASE}/events/{event_id}")
        return response.text

    def fetch_event_discovery_page(self, start_date: str, end_date_exclusive: str, page: int) -> dict[str, Any]:
        response = self._get(
            f"{PLAYHUB_API_BASE}/api/v2/events/",
            params={
                "start_date_after": start_date,
                "start_date_before": end_date_exclusive,
                "game_slug": "disney-lorcana",
                "page": page,
                "page_size": self.page_size,
            },
        )
        return self._json_object(response, context=f"event discovery page {page}")

    def fetch_all_discovered_events(self, start_date: str, end_date_exclusive: str) -> list[dict[str, Any]]:
        return self._fetch_all_pages(
            lambda page: self.fetch_event_discovery_page(start_date, end_date_exclusive, page),
            context=f"event discovery {start_date}..{end_date_exclusive}",
        )

    def fetch_round_match_page(self, round_id: int, page: int) -> dict[str, Any]:
        response = self._get(
            f"{PLAYHUB_API_BASE}/api/v2/tournament-rounds/{round_id}/matches/paginated/",
            params={"page": page, "page_size": self.page_size, "avoid_cache": "false"},
        )
        return self._json_object(response, context=f"round {round_id} matches page {page}")

    def fetch_standings_page(self, round_id: int, page: int) -> dict[str, Any]:
        response = self._get(
            f"{PLAYHUB_API_BASE}/api/v2/tournament-rounds/{round_id}/standings/paginated/",
            params={"page": page, "page_size": self.page_size},
        )
        return self._json_object(response, context=f"round {round_id} standings page {page}")

    def _fetch_all_pages(
        self,
        fetch_page: Callable[[int], dict[str, Any]],
        *,
        context: str,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        page = 1
        seen_pages: set[int] = set()
        while True:
            if page in seen_pages:
                raise PlayHubClientError(f"Pagination loop detected for {context} at page {page}")
            seen_pages.add(page)
            payload = fetch_page(page)
            page_results = payload.get("results", [])
            if not isinstance(page_results, list) or not all(isinstance(row, dict) for row in page_results):
                raise PlayHubClientError(f"Invalid results list for {context} page {page}")
            results.extend(page_results)

            next_page = payload.get("next_page_number")
            if next_page is None:
                return results
            if isinstance(next_page, bool):
                raise PlayHubClientError(f"Invalid next_page_number for {context}: {next_page!r}")
            try:
                page = int(next_page)
            except (TypeError, ValueError) as error:
                raise PlayHubClientError(f"Invalid next_page_number for {context}: {next_page!r}") from error
            if page <= 0:
                raise PlayHubClientError(f"Invalid next_page_number for {context}: {page!r}")
            if self.request_delay_seconds > 0:
                self.sleep(self.request_delay_seconds)

    def fetch_all_round_matches(self, round_id: int) -> list[dict[str, Any]]:
        return self._fetch_all_pages(
            lambda page: self.fetch_round_match_page(round_id, page),
            context=f"round {round_id} matches",
        )

    def fetch_all_standings(self, round_id: int) -> list[dict[str, Any]]:
        return self._fetch_all_pages(
            lambda page: self.fetch_standings_page(round_id, page),
            context=f"round {round_id} standings",
        )

    def close(self) -> None:
        self.session.close()
