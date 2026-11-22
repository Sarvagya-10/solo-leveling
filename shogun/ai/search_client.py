"""SerpAPI DuckDuckGo search client (https://serpapi.com/search?engine=duckduckgo).

Used only to *locate* source material (official papers, answer keys, reputable
solutions). Results are shown as links with their snippets; they are never
turned into citations or questions without user review.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlparse

import httpx

from shogun.ai.errors import (
    AIAuthError,
    AINotConfiguredError,
    AIRateLimitError,
    AIResponseError,
    AIUnavailableError,
)
from shogun.config import Secret
from shogun.logging_setup import get_logger, register_secret

log = get_logger("ai.search")
SEARCH_URL = "https://serpapi.com/search"
ACCOUNT_URL = "https://serpapi.com/account"


@dataclass(frozen=True)
class SearchResult:
    title: str
    link: str
    snippet: str
    position: int


class SerpApiClient:
    def __init__(self, api_key: Secret, *, timeout: float = 30.0, max_retries: int = 2,
                 transport: httpx.BaseTransport | None = None, sleep: Callable[[float], None] = time.sleep) -> None:
        if not api_key.is_set:
            raise AINotConfiguredError(
                "SerpAPI is not configured. Add SERPAPI_API_KEY to your environment or local .env file."
            )
        register_secret(api_key.get())
        self._key = api_key
        self._timeout = timeout
        self._max_retries = max_retries
        self._transport = transport
        self._sleep = sleep

    def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        params = {**params, "api_key": self._key.get()}
        last: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                    resp = client.get(url, params=params)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last = AIUnavailableError(f"Could not reach SerpAPI ({type(exc).__name__})")
            else:
                if resp.status_code == 401:
                    raise AIAuthError("SerpAPI rejected the API key. Check SERPAPI_API_KEY.")
                if resp.status_code == 429:
                    last = AIRateLimitError("SerpAPI rate limit or monthly quota reached.")
                elif resp.status_code >= 500:
                    last = AIUnavailableError(f"SerpAPI service error ({resp.status_code})")
                else:
                    try:
                        data = resp.json()
                    except ValueError as exc:
                        raise AIResponseError("SerpAPI returned a non-JSON response") from exc
                    if isinstance(data, dict) and data.get("error"):
                        message = str(data["error"])
                        if "api key" in message.lower():
                            raise AIAuthError("SerpAPI rejected the API key. Check SERPAPI_API_KEY.")
                        if "run out" in message.lower() or "limit" in message.lower():
                            raise AIRateLimitError("SerpAPI search quota exhausted.")
                        if "hasn't returned any results" in message.lower():
                            return {"organic_results": []}
                        raise AIResponseError(f"SerpAPI error: {message[:200]}")
                    if resp.status_code >= 400:
                        raise AIResponseError(f"SerpAPI request failed ({resp.status_code})")
                    return data
            if attempt < self._max_retries:
                self._sleep(2.0 ** attempt)
        assert last is not None
        raise last

    def search(self, query: str, *, region: str = "in-en", limit: int = 10) -> list[SearchResult]:
        if not query.strip():
            raise AIResponseError("Search query is empty")
        data = self._get(SEARCH_URL, {"engine": "duckduckgo", "q": query.strip(), "kl": region})
        out: list[SearchResult] = []
        for item in data.get("organic_results", [])[:limit]:
            link = str(item.get("link", ""))
            if link.startswith(("http://", "https://")):
                out.append(SearchResult(title=str(item.get("title", ""))[:300], link=link,
                                        snippet=str(item.get("snippet", ""))[:600],
                                        position=int(item.get("position", len(out) + 1))))
        return out

    def account(self) -> dict[str, Any]:
        """Account status (does not consume search credits)."""
        data = self._get(ACCOUNT_URL, {})
        return {k: data.get(k) for k in ("plan_name", "searches_per_month", "plan_searches_left",
                                         "total_searches_left", "this_month_usage") if k in data}


# --------------------------------------------------------------------------- page fetching
class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in ("script", "style", "noscript", "svg", "head"):
            self._skip += 1
        elif tag in ("p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "table"):
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript", "svg", "head") and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    text = "".join(parser.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def pdf_to_text(data: bytes, max_pages: int = 60) -> str:
    """Extract text from a PDF (e.g. an official GATE question paper). Math may extract imperfectly."""
    import io

    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages[:max_pages]]
    except (PdfReadError, ValueError, KeyError) as exc:
        raise AIResponseError("Could not read text from this PDF") from exc
    text = "\n\n".join(p.strip() for p in pages if p.strip())
    if not text:
        raise AIResponseError("This PDF has no extractable text (it may be scanned images)")
    return text


def _safe_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise AIResponseError("Only http(s) URLs can be fetched")
    host = parsed.hostname
    if host in ("localhost",) or host.endswith(".local"):
        raise AIResponseError("Local addresses cannot be fetched")
    try:
        ip = ip_address(host)
    except ValueError:
        return url.strip()
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
        raise AIResponseError("Private network addresses cannot be fetched")
    return url.strip()


def fetch_page_text(url: str, *, timeout: float = 20.0, max_bytes: int = 2_000_000,
                    transport: httpx.BaseTransport | None = None) -> str:
    safe = _safe_url(url)
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, transport=transport,
                          headers={"User-Agent": "Mozilla/5.0 (compatible; ShogunStudyTracker/1.0)"}) as client:
            resp = client.get(safe)
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise AIUnavailableError(f"Could not fetch the page ({type(exc).__name__})") from exc
    if resp.status_code >= 400:
        raise AIResponseError(f"The page returned HTTP {resp.status_code}")
    ctype = resp.headers.get("content-type", "")
    if "pdf" in ctype or resp.content[:5] == b"%PDF-":
        return pdf_to_text(resp.content[: max_bytes * 10])
    body = resp.content[:max_bytes].decode(resp.encoding or "utf-8", errors="replace")
    return html_to_text(body) if "html" in ctype or "<html" in body[:500].lower() else body
