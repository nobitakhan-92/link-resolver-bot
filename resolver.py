import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import dns.resolver
import httpx

MAX_REDIRECTS = 8
TIMEOUT = 10
HEADERS = {
    "User-Agent": "LinkResolver/1.0",
    "Accept": "text/html,*/*;q=0.8",
}


def validate_url(url: str) -> str:
    """Allow public HTTP(S) URLs only."""
    try:
        p = urlsplit(url.strip())

        if p.scheme.lower() not in ("http", "https"):
            raise ValueError("Only HTTP and HTTPS links are supported.")

        if not p.hostname or p.username or p.password:
            raise ValueError("Invalid URL.")

        host = p.hostname.rstrip(".").lower()

        if host == "localhost" or host.endswith(".localhost"):
            raise ValueError("Private destinations are not allowed.")

        try:
            ip = ipaddress.ip_address(host)
            if not ip.is_global:
                raise ValueError("Private destinations are not allowed.")
        except ValueError as exc:
            if str(exc) == "Private destinations are not allowed.":
                raise
            # Not an IP literal: resolve the hostname below.
            try:
                answers = dns.resolver.resolve(host, "A", lifetime=3)
                addresses = [str(a) for a in answers]
                try:
                    answers6 = dns.resolver.resolve(host, "AAAA", lifetime=3)
                    addresses += [str(a) for a in answers6]
                except Exception:
                    pass
            except Exception:
                try:
                    addresses = [
                        item[4][0]
                        for item in socket.getaddrinfo(
                            host, None, type=socket.SOCK_STREAM
                        )
                    ]
                except OSError:
                    raise ValueError("The hostname could not be resolved.")

            if not addresses or any(
                not ipaddress.ip_address(a).is_global for a in addresses
            ):
                raise ValueError("Private destinations are not allowed.")

        port = p.port
        if port is not None and port not in (80, 443):
            raise ValueError("Only standard HTTP(S) ports are supported.")

        return p._replace(fragment="").geturl()

    except (ValueError, TypeError) as exc:
        raise ValueError(str(exc) or "Invalid URL.") from exc


async def resolve_link(url: str) -> dict:
    current = validate_url(url)

    async with httpx.AsyncClient(
        follow_redirects=False,
        timeout=TIMEOUT,
        trust_env=False,
        headers=HEADERS,
    ) as client:
        for hop in range(MAX_REDIRECTS + 1):
            # Revalidate every hop to reduce redirect-based SSRF risks.
            current = validate_url(current)

            try:
                async with client.stream("GET", current) as response:
                    if response.status_code not in (
                        301, 302, 303, 307, 308
                    ):
                        return {
                            "ok": True,
                            "original_url": url,
                            "destination_url": current,
                            "redirects": hop,
                            "status_code": response.status_code,
                            "message": (
                                "Redirect chain resolved."
                                if hop else
                                "No HTTP redirect detected."
                            ),
                        }

                    location = response.headers.get("location")
                    if not location:
                        return {
                            "ok": False,
                            "message": "Redirect has no destination.",
                        }

                    current = urljoin(current, location)

            except httpx.TimeoutException:
                return {
                    "ok": False,
                    "message": "The website took too long to respond.",
                }
            except httpx.HTTPError:
                return {
                    "ok": False,
                    "message": "Could not access this link.",
                }
            except ValueError as exc:
                return {"ok": False, "message": str(exc)}

    return {
        "ok": False,
        "message": "Too many redirects.",
    }


def resolve_sync(url: str) -> dict:
    """Optional helper for synchronous callers."""
    return asyncio.run(resolve_link(url))    
