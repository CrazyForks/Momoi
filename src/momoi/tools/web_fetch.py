import asyncio
import math
from typing import Any
from urllib.parse import urljoin, urlsplit

import aiohttp
from bs4 import BeautifulSoup
from markdownify import markdownify

MAX_RESPONSE_BYTES = 2_000_000


def extract_html(html: str, url: str, mode: str) -> tuple[str, str | None]:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else None
    for element in soup.select("script, style, noscript, template, head, [hidden], [aria-hidden='true']"):
        element.decompose()
    for element in soup.find_all(["a", "img"]):
        attribute = "href" if element.name == "a" else "src"
        value = element.get(attribute)
        if not isinstance(value, str):
            continue
        absolute = urljoin(url, value)
        if urlsplit(absolute).scheme in {"http", "https", "mailto"}:
            element[attribute] = absolute
        else:
            del element[attribute]
    if mode == "text":
        return soup.get_text("\n", strip=True), title
    return markdownify(str(soup), heading_style="ATX").strip(), title


async def web_fetch(arguments: dict[str, Any]) -> dict[str, Any]:
    unknown = arguments.keys() - {"url", "extract_mode", "max_chars", "timeout_seconds"}
    if unknown:
        raise ValueError(f"unsupported web_fetch arguments: {', '.join(sorted(unknown))}")
    url = str(arguments.get("url") or "").strip()
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("url must use http or https and include a host")
    mode = arguments.get("extract_mode", "markdown")
    if mode not in {"markdown", "text"}:
        raise ValueError("extract_mode must be markdown or text")
    limit = arguments.get("max_chars", 20000)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200000:
        raise ValueError("max_chars must be between 1 and 200000")
    timeout = arguments.get("timeout_seconds", 20)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0.1 <= timeout <= 120:
        raise ValueError("timeout_seconds must be between 0.1 and 120")
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
        async with session.get(url, allow_redirects=True) as response:
            metadata = {
                "url": str(response.url),
                "requested_url": url,
                "status": response.status,
                "content_type": response.content_type,
                "extract_mode": mode,
            }
            mime = response.content_type
            if not (mime.startswith("text/") or mime in {"application/json", "application/xml", "application/xhtml+xml"} or mime.endswith(("+json", "+xml"))):
                return {"ok": False, "error": "unsupported_content_type", **metadata}
            try:
                raw = await response.content.readexactly(MAX_RESPONSE_BYTES + 1)
            except asyncio.IncompleteReadError as error:
                raw = error.partial
            source_truncated = len(raw) > MAX_RESPONSE_BYTES
            try:
                content = raw[:MAX_RESPONSE_BYTES].decode(response.charset or "utf-8", errors="replace")
            except LookupError:
                content = raw[:MAX_RESPONSE_BYTES].decode("utf-8", errors="replace")
            title = None
            if mime in {"text/html", "application/xhtml+xml"}:
                content, title = await asyncio.to_thread(extract_html, content, str(response.url), mode)
            result = {
                "ok": response.status < 400,
                **metadata,
                "title": title,
                "content": content[:limit],
                "truncated": source_truncated or len(content) > limit,
                "source_truncated": source_truncated,
                "content_length": len(content),
            }
            if response.status >= 400:
                result["error"] = "http_error"
            return result
