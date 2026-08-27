"""Fail-closed network boundary with DNS pinning and bounded HTML responses."""
import asyncio
import ipaddress
import os
import socket
import weakref
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

PIAOTIA_HOSTS = frozenset({"piaotia.com", "www.piaotia.com", "piaotian.com", "www.piaotian.com"})
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_CATALOG_CHAPTERS = 20000
_loop_rates = weakref.WeakKeyDictionary()


def allowed_hosts():
    """Exact hosts only; extra hosts explicitly opt into the Biquge adapter."""
    configured = os.getenv("CRAWLER_ALLOWED_HOSTS", ",".join(sorted(PIAOTIA_HOSTS)))
    return frozenset(host.strip().lower() for host in configured.split(",") if host.strip())


def canonical_url(url: str) -> str:
    if not isinstance(url, str) or len(url) > 500 or any(ord(c) < 33 for c in url) or "\\" in url:
        raise ValueError("URL nguồn không hợp lệ.")
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.username is not None or parsed.password is not None
            or parsed.port not in (None, 443) or not parsed.hostname
            or parsed.hostname.lower() not in allowed_hosts()):
        raise ValueError("Nguồn phải dùng HTTPS và hostname trong CRAWLER_ALLOWED_HOSTS.")
    host = parsed.hostname.lower()
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("Không cho phép địa chỉ IP làm nguồn truyện.")
    return urlunsplit(("https", host, parsed.path or "/", parsed.query, ""))


def same_source_url(base: str, link: str) -> str:
    base = canonical_url(base)
    candidate = canonical_url(urljoin(base, link))
    if urlsplit(candidate).netloc != urlsplit(base).netloc:
        raise ValueError("Liên kết nguồn chuyển sang hostname khác.")
    return candidate


def prefer_ipv4() -> bool:
    """Most PaaS hosts (Render, Fly free tier) have no outbound IPv6 route.

    Chinese novel sources sit behind Cloudflare, whose resolver answers AAAA
    first, so an unordered pin connects to an unreachable IPv6 literal.
    """
    return os.getenv("CRAWLER_PREFER_IPV6", "0").strip().lower() not in ("1", "true", "yes")


async def resolve_public_addresses(host: str) -> tuple[str, ...]:
    records = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    addresses = tuple(dict.fromkeys(record[4][0] for record in records))
    if not addresses or any(not ipaddress.ip_address(value).is_global for value in addresses):
        raise ValueError("Nguồn phân giải đến địa chỉ mạng riêng hoặc không hợp lệ.")
    if prefer_ipv4():
        addresses = tuple(sorted(addresses, key=lambda value: ipaddress.ip_address(value).version))
    return addresses


class PinnedTransport(httpx.AsyncBaseTransport):
    def __init__(self):
        self.transport = httpx.AsyncHTTPTransport(
            trust_env=False, retries=0,
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=0),
        )

    async def handle_async_request(self, request):
        source = httpx.URL(canonical_url(str(request.url)))
        addresses = await resolve_public_addresses(source.host)
        # Connect to the validated IP, preserving the source's TLS identity.
        # No keepalive avoids sharing a TLS connection across same-IP hosts.
        # Bodyless reads are replayable, so an unreachable address family
        # (IPv6 on a host without egress) falls through to the next answer.
        replayable = request.method in ("GET", "HEAD")
        failure = None
        for address in addresses:
            pinned = httpx.Request(
                request.method, source.copy_with(host=address),
                headers={**dict(request.headers), "host": source.host},
                stream=request.stream,
                extensions={**request.extensions, "sni_hostname": source.host},
            )
            try:
                return await self.transport.handle_async_request(pinned)
            except (httpx.ConnectError, httpx.ConnectTimeout) as error:
                failure = error
                if not replayable:
                    raise
        raise failure

    async def aclose(self):
        await self.transport.aclose()


async def _rate_limit(host: str):
    loop = asyncio.get_running_loop()
    rates = _loop_rates.setdefault(loop, {})
    lock, previous = rates.setdefault(host, (asyncio.Lock(), 0.0))
    async with lock:
        previous = rates[host][1]
        await asyncio.sleep(max(0.0, previous + 1.0 - loop.time()))
        rates[host] = (lock, loop.time())


async def fetch_html(url: str, headers: dict, encoding="utf-8") -> str:
    url = canonical_url(url)
    async with asyncio.timeout(40):
        async with httpx.AsyncClient(
            transport=PinnedTransport(), trust_env=False, follow_redirects=False,
            timeout=httpx.Timeout(20, connect=10),
            headers={**headers, "Accept-Encoding": "identity"},
        ) as client:
            return await _fetch_redirects(client, url, encoding)


async def _fetch_redirects(client, url, encoding):
    original = url
    for _ in range(4):
        await _rate_limit(urlsplit(url).hostname)
        async with client.stream("GET", url) as response:
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise ValueError("Nguồn trả redirect không có đích.")
                url = same_source_url(original, urljoin(url, location))
                continue
            response.raise_for_status()
            payload = await _bounded_body(response)
            try:
                return payload.decode(encoding)
            except UnicodeDecodeError:
                return payload.decode("gb18030")
    raise ValueError("Nguồn redirect quá nhiều lần.")


async def _bounded_body(response):
    if response.headers.get("content-encoding", "identity").lower() not in ("", "identity"):
        raise ValueError("Nguồn trả định dạng nén không được phép.")
    content_type = response.headers.get("content-type", "text/html").lower()
    if not any(kind in content_type for kind in ("text/html", "application/xhtml+xml", "text/plain")):
        raise ValueError("Nguồn không trả nội dung HTML.")
    if int(response.headers.get("content-length", "0")) > MAX_RESPONSE_BYTES:
        raise ValueError("Nội dung nguồn vượt giới hạn kích thước.")
    chunks, length = [], 0
    async for chunk in response.aiter_bytes(chunk_size=65536):
        length += len(chunk)
        if length > MAX_RESPONSE_BYTES:
            raise ValueError("Nội dung nguồn vượt giới hạn kích thước.")
        chunks.append(chunk)
    return b"".join(chunks)
