import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import dns.resolver
import httpx

MAX_REDIRECTS = 10
TIMEOUT = 12

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; LinkResolver/1.0)",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

REDIRECT_CODES = {301, 302, 303, 307, 308}


def validate_url(url: str) -> str:
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
        except ValueError:
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
                    raise ValueError("Hostname could not be resolved.")

            if not addresses or any(
                not ipaddress.ip_address(a).is_global for a in addresses
            ):
                raise ValueError("Private destinations are not allowed.")
        else:
            if not ip.is_global:
                raise ValueError("Private destinations are not allowed.")

        if p.port is not None and p.port not in (80, 443):
            raise ValueError("Only standard HTTP(S) ports are supported.")

        return p._replace(fragment="").geturl()

    except (ValueError, TypeError) as exc:
        raise ValueError(str(exc) or "Invalid URL.") from exc


async def resolve_link(url: str) -> dict:
    try:
        original = validate_url(url)
    except ValueError as exc:
        return {"ok": False, "status": "invalid", "message": str(exc)}

    current = original
    history = []

    async with httpx.AsyncClient(
        follow_redirects=False,
        timeout=TIMEOUT,
        trust_env=False,
        headers=HEADERS,
    ) as client:
        for hop in range(MAX_REDIRECTS + 1):
            try:
                current = validate_url(current)

                async with client.stream("GET", current) as response:
                    code = response.status_code
                    history.append({
                        "url": current,
                        "status_code": code,
                    })

                    if code in REDIRECT_CODES:
                        location = response.headers.get("location")

                        if not location:
                            return {
                                "ok": False,
                                "status": "unresolved",
                                "message": "Redirect has no destination.",
                                "history": history,
                            }

                        if hop == MAX_REDIRECTS:
                            break

                        current = urljoin(current, location)
                        continue

                    if code in (401, 403, 429):
                        return {
                            "ok": False,
                            "status": "blocked",
                            "message": f"Server returned HTTP {code}.",
                            "destination_url": current,
                            "redirects": hop,
                            "history": history,
                        }

                    if code >= 400:
                        return {
                            "ok": False,
                            "status": "http_error",
                            "message": f"HTTP error {code}.",
                            "destination_url": current,
                            "redirects": hop,
                            "history": history,
                        }

                    if current == original:
                        return {
                            "ok": False,
                            "status": "unresolved",
                            "message": (
                                "No destination found. The page may require "
                                "JavaScript, verification, or a browser step."
                            ),
                            "destination_url": current,
                            "redirects": hop,
                            "history": history,
                        }

                    return {
                        "ok": True,
                        "status": "resolved",
                        "message": "Destination URL found.",
                        "original_url": original,
                        "destination_url": current,
                        "redirects": hop,
                        "status_code": code,
                        "history": history,
                    }

            except httpx.TimeoutException:
                return {
                    "ok": False,
                    "status": "timeout",
                    "message": "The website took too long to respond.",
                    "history": history,
                }
            except httpx.HTTPError:
                return {
                    "ok": False,
                    "status": "network_error",
                    "message": "Could not access this link.",
                    "history": history,
                }
            except ValueError as exc:
                return {
                    "ok": False,
                    "status": "invalid_redirect",
                    "message": str(exc),
                    "history": history,
                }

    return {
        "ok": False,
        "status": "too_many_redirects",
        "message": "Too many redirects.",
        "history": history,
    }


def resolve_sync(url: str) -> dict:
    return asyncio.run(resolve_link(url))
