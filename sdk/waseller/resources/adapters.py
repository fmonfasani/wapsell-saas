"""Data source adapters — concrete fetchers that turn an upstream into a
list of dicts the resource store can ingest.

The adapter contract is intentionally tiny:

    async def fetch(config: dict) -> list[dict]

Each adapter validates its own config slice; the synchronizer (next module)
takes the resulting dicts, wraps them in :class:`Resource` instances, and
upserts via :class:`ResourceRepositoryPort`.

Adapters ship with conservative defaults: short timeouts, common-browser
User-Agent, no JS rendering (we want headless scraping to "just work"
against simple sites; the user can switch to a custom adapter for SPAs).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

import httpx

from waseller.resources.models import DataSource, DataSourceKind

# Conservative timeout — sources like inmo listings rarely take more than a
# couple of seconds; long fetches usually mean the source is paginated and
# the adapter needs to be smarter, not patient.
_DEFAULT_HTTP_TIMEOUT_SECONDS = 15.0

# Default UA we send when the config doesn't override one. A common-browser
# string keeps us out of the "obvious bot" bucket of basic filters; sites
# with real anti-bot protection (Cloudflare, Akamai) won't be fooled and
# that's fine — the user can plug a different adapter for those.
_DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; WapsellBot/0.15; +https://wapsell.com)"

# HTTP status threshold above which we treat a response as an upstream
# failure. 4xx / 5xx → AdapterError; the synchronizer records the message
# on ``last_sync_error`` so operators see it in the dashboard.
_HTTP_ERROR_THRESHOLD = 400


@runtime_checkable
class DataSourceAdapterPort(Protocol):
    """Fetch contract. Returns a list of dicts shaped however the source
    pleases — the schema is emergent (see PR #35)."""

    async def fetch(self, source: DataSource) -> list[dict[str, Any]]: ...


class AdapterError(RuntimeError):
    """Raised when a fetch can't produce items — bad config, network
    failure, source-side error. The synchronizer catches these and records
    them on the source's ``last_sync_error`` field instead of crashing."""


class ManualDataSourceAdapter:
    """No-op adapter for sources whose resources are pushed manually via
    the API. Always returns empty — calling sync on a manual source is a
    valid op that just refreshes the timestamp."""

    async def fetch(self, source: DataSource) -> list[dict[str, Any]]:
        return []


class WebhookDataSourceAdapter:
    """No-op adapter for webhook sources. The webhook handler upserts
    resources as they arrive; sync is a no-op for the same reason as
    :class:`ManualDataSourceAdapter`."""

    async def fetch(self, source: DataSource) -> list[dict[str, Any]]:
        return []


class JsonApiDataSourceAdapter:
    """GETs a REST endpoint and walks the response JSON.

    Config:
      - ``url`` (required): full URL to GET.
      - ``headers`` (optional): dict of HTTP headers (e.g. auth).
      - ``items_path`` (optional): dotted path to the array inside the
        response (e.g. ``data.results``). If unset, the response itself
        must be a list.
      - ``timeout`` (optional): seconds, default 15.
    """

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def fetch(self, source: DataSource) -> list[dict[str, Any]]:
        url = source.config.get("url")
        if not isinstance(url, str) or not url.strip():
            raise AdapterError("JsonApiDataSource requires config.url")

        headers = dict(source.config.get("headers") or {})
        headers.setdefault("User-Agent", _DEFAULT_USER_AGENT)
        headers.setdefault("Accept", "application/json")

        timeout = float(source.config.get("timeout", _DEFAULT_HTTP_TIMEOUT_SECONDS))

        client = self._client or httpx.AsyncClient()
        owns_client = self._client is None
        try:
            try:
                response = await client.get(url, headers=headers, timeout=timeout)
            except httpx.HTTPError as exc:
                raise AdapterError(f"http error fetching {url}: {exc}") from exc
            if response.status_code >= _HTTP_ERROR_THRESHOLD:
                raise AdapterError(f"{url} returned HTTP {response.status_code}")
            try:
                payload = response.json()
            except ValueError as exc:
                raise AdapterError(f"{url} did not return JSON: {exc}") from exc
        finally:
            if owns_client:
                await client.aclose()

        items_path = source.config.get("items_path")
        items = payload
        if isinstance(items_path, str) and items_path.strip():
            for chunk in items_path.split("."):
                if not isinstance(items, dict):
                    raise AdapterError(f"items_path {items_path!r} fell off the JSON shape")
                items = items.get(chunk)
                if items is None:
                    raise AdapterError(f"items_path {items_path!r}: missing key {chunk!r}")
        if not isinstance(items, list):
            raise AdapterError(
                f"JsonApiDataSource expected a list at the items_path; got {type(items).__name__}"
            )
        # Coerce non-dict entries to a wrapper so the resource store always
        # gets dict-shaped data — strings/ints become {"value": ...}.
        return [item if isinstance(item, dict) else {"value": item} for item in items]


class HtmlScraperDataSourceAdapter:
    """Scrapes a public HTML page with CSS selectors.

    Config:
      - ``url`` (required): page to GET.
      - ``item_selector`` (required): CSS selector that picks each item
        block (e.g. ``"div.listing-card"``).
      - ``fields`` (optional): dict of ``{field_name: selector}``. Each
        selector is run against the item block; the matched element's
        ``.get_text(strip=True)`` becomes the value. To pull an attribute
        instead, write the selector as ``"selector@attr"`` (e.g.
        ``"a.link@href"``).
      - ``headers`` (optional): extra HTTP headers.
      - ``timeout`` (optional): seconds, default 15.

    The adapter never executes JavaScript; sites that require JS rendering
    need a different adapter (e.g. Playwright) — out of scope for the demo.
    """

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def fetch(self, source: DataSource) -> list[dict[str, Any]]:
        url = source.config.get("url")
        if not isinstance(url, str) or not url.strip():
            raise AdapterError("HtmlScraperDataSource requires config.url")
        item_selector = source.config.get("item_selector")
        if not isinstance(item_selector, str) or not item_selector.strip():
            raise AdapterError("HtmlScraperDataSource requires config.item_selector")
        fields = source.config.get("fields") or {}
        if not isinstance(fields, dict):
            raise AdapterError("HtmlScraperDataSource config.fields must be a dict")

        headers = dict(source.config.get("headers") or {})
        headers.setdefault("User-Agent", _DEFAULT_USER_AGENT)
        timeout = float(source.config.get("timeout", _DEFAULT_HTTP_TIMEOUT_SECONDS))

        client = self._client or httpx.AsyncClient()
        owns_client = self._client is None
        try:
            try:
                response = await client.get(url, headers=headers, timeout=timeout)
            except httpx.HTTPError as exc:
                raise AdapterError(f"http error fetching {url}: {exc}") from exc
            if response.status_code >= _HTTP_ERROR_THRESHOLD:
                raise AdapterError(f"{url} returned HTTP {response.status_code}")
            html = response.text
        finally:
            if owns_client:
                await client.aclose()

        return _extract_items(html, item_selector, fields)


def _extract_items(
    html: str,
    item_selector: str,
    fields: dict[str, str],
) -> list[dict[str, Any]]:
    """Parse HTML and pull one dict per item block. Kept as a module
    function so we can unit-test the scraping logic against canned HTML
    without going over the wire."""
    # Deferred import: bs4 is in deps but loading it lazily keeps the SDK
    # import path light for callers that don't scrape.
    from bs4 import BeautifulSoup  # noqa: PLC0415

    soup = BeautifulSoup(html, "html.parser")
    item_nodes = soup.select(item_selector)
    items: list[dict[str, Any]] = []
    for node in item_nodes:
        row: dict[str, Any] = {}
        for field_name, raw_selector in fields.items():
            sel, attr = _split_attr(raw_selector)
            match = node.select_one(sel) if sel else node
            if match is None:
                continue
            if attr is None:
                row[field_name] = match.get_text(strip=True)
            else:
                value = match.get(attr)
                if value is not None:
                    row[field_name] = value
        if row:
            items.append(row)
    return items


def _split_attr(raw_selector: str) -> tuple[str, str | None]:
    """``"a.link@href"`` → ``("a.link", "href")``; ``"h2"`` → ``("h2", None)``."""
    if "@" in raw_selector:
        sel, _, attr = raw_selector.rpartition("@")
        return sel.strip(), attr.strip() or None
    return raw_selector, None


def build_adapter(
    kind: DataSourceKind,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> DataSourceAdapterPort:
    """Factory: pick the right adapter for a source kind. Centralized so
    callers don't have to know each adapter's class name; the synchronizer
    asks the factory and gets back a port-compatible object."""
    if kind == DataSourceKind.HTML:
        return HtmlScraperDataSourceAdapter(client=http_client)
    if kind == DataSourceKind.JSON_API:
        return JsonApiDataSourceAdapter(client=http_client)
    if kind == DataSourceKind.WEBHOOK:
        return WebhookDataSourceAdapter()
    if kind in (DataSourceKind.MANUAL, DataSourceKind.CSV):
        return ManualDataSourceAdapter()
    raise AdapterError(f"no adapter for kind {kind}")
