import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpx
from playwright.async_api import async_playwright


MAX_REDIRECTS = 8
HTTP_TIMEOUT = 12
BROWSER_TIMEOUT_MS = 15000


def validate_url(url: str) -> str:
    """Allow public HTTP(S) URLs only."""
    if not isinstance(url, str) or len(url) > 2048:
        raise ValueError("Invalid URL.")

    parsed = urlparse(url.strip())

    if parsed.scheme not in ("http", "https"):
        raise ValueError("Only HTTP and HTTPS links are supported.")

    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Invalid URL.")

    host = parsed.hostname.rstrip(".").lower()

    if host == "localhost" or host.endswith(".localhost"):
        raise ValueError("Private destinations are not allowed.")

    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        }
    except socket.gaierror:
        raise ValueError("The domain could not be resolved.")

    if not addresses:
        raise ValueError("The domain has no public address.")

    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ValueError("Private destinations are not allowed.")

    return url.strip()


async def http_resolve(url: str) -> dict:
    current = validate_url(url)
    original = current
    redirects = 0

    async with httpx.AsyncClient(
        follow_redirects=False,
        timeout=HTTP_TIMEOUT,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; LinkResolver/1.0)"
        },
        trust_env=False,
    ) as client:
        while redirects < MAX_REDIRECTS:
            current = validate_url(current)

            try:
                async with client.stream("GET", current) as response:
                    status = response.status_code
                    location = response.headers.get("location")

                    if status in (301, 302, 303, 307, 308) and location:
                        current = urljoin(current, location)
                        redirects += 1
                        continue

                    break
            except (httpx.HTTPError, ValueError) as exc:
                return {
                    "ok": False,
                    "destination": None,
                    "status": None,
                    "redirects": redirects,
                    "error": str(exc),
                }

    if current != original:
        return {
            "ok": True,
            "destination": current,
            "status": status,
            "redirects": redirects,
            "error": None,
        }

    return {
        "ok": False,
        "destination": None,
        "status": status,
        "redirects": redirects,
        "error": "No HTTP redirect detected.",
    }


async def browser_resolve(url: str) -> dict:
    original = validate_url(url)

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context(
                service_workers="block",
                accept_downloads=False,
            )
            page = await context.new_page()

            async def guard_request(route):
                try:
                    validate_url(route.request.url)
                    await route.continue_()
                except (ValueError, OSError):
                    await route.abort()

            await page.route("**/*", guard_request)

            try:
                response = await page.goto(
                    original,
                    wait_until="domcontentloaded",
                    timeout=BROWSER_TIMEOUT_MS,
                )

                await page.wait_for_timeout(1200)

                final_url = validate_url(page.url)
                status = response.status if response else None

                # Do not claim success if the page is still the shortener.
                if final_url == original:
                    result = {
                        "ok": False,
                        "destination": None,
                        "status": status,
                        "redirects": 0,
                        "error": (
                            "No destination found. The page may require "
                            "verification or a manual step."
                        ),
                    }
                else:
                    result = {
                        "ok": True,
                        "destination": final_url,
                        "status": status,
                        "redirects": None,
                        "error": None,
                    }

            except Exception:
                result = {
                    "ok": False,
                    "destination": None,
                    "status": None,
                    "redirects": 0,
                    "error": (
                        "Browser resolution failed or timed out."
                    ),
                }

            await context.close()
            await browser.close()
            return result

    except Exception:
        return {
            "ok": False,
            "destination": None,
            "status": None,
            "redirects": 0,
            "error": "Browser could not start.",
        }


async def resolve_url(url: str) -> dict:
    try:
        original = validate_url(url)
    except (ValueError, OSError) as exc:
        return {
            "ok": False,
            "destination": None,
            "status": None,
            "redirects": 0,
            "error": str(exc),
        }

    result = await http_resolve(original)

    if result["ok"]:
        return result

    # Only use a browser if ordinary HTTP resolution did not find a target.
    return await browser_resolve(original)
