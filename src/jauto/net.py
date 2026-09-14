"""HTTP client with rate limiting, retries and a self-identifying UA."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

import requests


class ApiError(Exception):
    """A provider API returned an unexpected response."""

    def __init__(self, message: str, status_code: Optional[int] = None, url: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.url = url


class Client:
    """Thin wrapper around requests.Session.

    - sleeps to honour NetworkConfig.request_delay between any two requests
    - retries GETs on connection errors / 429 / 5xx with backoff
    - NEVER retries POSTs (an application submission must not be duplicated)
    """

    def __init__(self, cfg, session: Optional[requests.Session] = None):
        self.cfg = cfg
        self._session = session or requests.Session()
        self._last_request = 0.0
        self._user_agent = self._build_ua(cfg)

    @staticmethod
    def _build_ua(cfg) -> str:
        contact = f"; contact:{cfg.contact_email}" if getattr(cfg, "contact_email", "") else ""
        return f"jauto/0.1 (+https://github.com/eugenshila/JAUTOMATIC-JOB-SEARCH{contact})"

    # ------------------------------------------------------------------
    def _throttle(self) -> None:
        delay = max(0.0, float(getattr(self.cfg, "request_delay", 1.0)))
        wait = delay - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    @property
    def timeout(self) -> float:
        return float(getattr(self.cfg, "timeout", 20.0))

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        self._throttle()
        kwargs.setdefault("timeout", self.timeout)
        headers = kwargs.pop("headers", {}) or {}
        headers.setdefault("User-Agent", self._user_agent)
        kwargs["headers"] = headers
        return self._session.request(method, url, **kwargs)

    # ------------------------------------------------------------------
    def get_json(self, url: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """GET a JSON document with retries; raise ApiError on failure."""
        retries = int(getattr(self.cfg, "retries", 2))
        last_error: Optional[Exception] = None
        for attempt in range(retries + 1):
            try:
                resp = self._request("GET", url, params=params)
                if resp.status_code in (429,) or 500 <= resp.status_code < 600:
                    last_error = ApiError(
                        f"HTTP {resp.status_code} from {url}", resp.status_code, url
                    )
                elif resp.status_code == 404:
                    raise ApiError(f"Not found (404): {url}", 404, url)
                elif resp.status_code >= 400:
                    raise ApiError(
                        f"HTTP {resp.status_code} from {url}: {resp.text[:200]}",
                        resp.status_code,
                        url,
                    )
                else:
                    try:
                        return resp.json()
                    except ValueError as exc:
                        raise ApiError(
                            f"Non-JSON response from {url}: {resp.text[:200]}", url=url
                        ) from exc
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = ApiError(f"Network error calling {url}: {exc}", url=url)
            if attempt < retries:
                time.sleep(1.5 * (2 ** attempt))
        raise last_error or ApiError(f"Request failed: {url}", url=url)

    # ------------------------------------------------------------------
    def post_multipart(
        self,
        url: str,
        data: Optional[Dict[str, Any]] = None,
        files: Optional[List[Tuple[str, Tuple[str, bytes, str]]]] = None,
    ) -> requests.Response:
        """POST multipart/form-data (no retries — may submit an application)."""
        return self._request("POST", url, data=data or {}, files=files or [])

    def post_urlencoded(
        self, url: str, data: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """POST application/x-www-form-urlencoded (no retries)."""
        return self._request("POST", url, data=data or {})
