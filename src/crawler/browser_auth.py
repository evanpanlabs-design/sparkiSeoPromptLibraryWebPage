"""
Browser-based X authentication using Playwright.

Uses Playwright to:
1. Navigate to x.com and solve any Cloudflare challenges
2. Log in with credentials (or let user log in manually)
3. Export session cookies to outputs/cookies.json

Usage:
    # Interactive (opens browser, you log in manually)
    python -m src.crawler.browser_auth

    # Headless with credentials
    python -m src.crawler.browser_auth --username USER --password PASS
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_COOKIES = PROJECT_ROOT / "outputs" / "cookies.json"


async def run_auth_interactive(cookies_path: Path, proxy: str | None):
    """Open browser and let user log in manually."""
    proxy_config = {"server": proxy} if proxy else None

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            proxy=proxy_config,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        page = await context.new_page()
        print("Opening x.com login page...")
        await page.goto("https://x.com/i/flow/login", timeout=60000)
        print("Browser opened. Please log in to X manually.")
        print("After logging in, press Enter here to save cookies...")
        input()
        cookies = await context.cookies()
        await _save_cookies(cookies, cookies_path)
        await browser.close()


async def run_auth_headless(username: str, password: str, email: str | None,
                            cookies_path: Path, proxy: str | None):
    """Automated login with credentials."""
    proxy_config = {"server": proxy} if proxy else None

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            proxy=proxy_config,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        page = await context.new_page()
        print("Navigating to x.com...")
        await page.goto("https://x.com/i/flow/login", timeout=60000)

        # Enter username
        await page.wait_for_selector('input[autocomplete="username"]', timeout=30000)
        await page.fill('input[autocomplete="username"]', username)
        await page.click('[role="button"]:has-text("Next")')

        # Password field (may need email verification first)
        try:
            await page.wait_for_selector('input[name="password"]', timeout=10000)
        except Exception:
            try:
                await page.wait_for_selector('input[autocomplete="username"]', timeout=5000)
                email_to_use = email or input("X requires email verification. Enter your email: ").strip()
                await page.fill('input[autocomplete="username"]', email_to_use)
                await page.click('[role="button"]:has-text("Next")')
                await page.wait_for_selector('input[name="password"]', timeout=15000)
            except Exception as e:
                print(f"Could not reach password field: {e}")
                await page.screenshot(path=str(PROJECT_ROOT / "outputs" / "verify_page.png"))
                print("Screenshot saved to outputs/verify_page.png")
                await browser.close()
                sys.exit(1)

        await page.fill('input[name="password"]', password)
        await page.click('[data-testid="LoginForm_Login_Button"]')

        # Wait for login success
        await page.wait_for_selector('[data-testid="primaryColumn"]', timeout=30000)
        print("Login successful!")

        cookies = await context.cookies()
        await _save_cookies(cookies, cookies_path)
        await browser.close()


async def _save_cookies(cookies: list[dict], cookies_path: Path):
    """Save cookies in {name: value} format expected by BrowserManager.load_cookies."""
    cookies_path.parent.mkdir(parents=True, exist_ok=True)
    simple = {}
    for c in cookies:
        simple[c["name"]] = c["value"]
    with open(cookies_path, "w", encoding="utf-8") as f:
        json.dump(simple, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(simple)} cookies to {cookies_path}")


async def verify_session(cookies_path: Path, proxy: str | None) -> bool:
    """Verify cookies are valid by loading them into a new context."""
    proxy_config = {"server": proxy} if proxy else None

    with open(cookies_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    adapted = []
    for name, value in raw.items():
        is_secure = name.startswith("__Secure-") or name.startswith("__Host-")
        # __Host- cookies require exact domain match (no leading dot) and secure
        domain = "x.com" if name.startswith("__Host-") else ".x.com"
        adapted.append({
            "name": name,
            "value": value,
            "domain": domain,
            "path": "/",
            "secure": True,
            "sameSite": "Strict",
        })

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, proxy=proxy_config)
        context = await browser.new_context()
        await context.add_cookies(adapted)
        page = await context.new_page()
        await page.goto("https://x.com", timeout=30000)
        try:
            await page.wait_for_selector('[data-testid="primaryColumn"]', timeout=15000)
            print("Session valid — cookies are working.")
            await browser.close()
            return True
        except Exception:
            print("Session invalid or expired.")
            await browser.close()
            return False


async def main():
    parser = argparse.ArgumentParser(description="Browser-based X authentication")
    parser.add_argument("--username", help="X username or email")
    parser.add_argument("--password", help="X password")
    parser.add_argument("--email", help="Email for verification if prompted")
    parser.add_argument("--proxy", default=None, help="HTTP proxy (e.g. http://127.0.0.1:7897)")
    parser.add_argument("--cookies", default=str(DEFAULT_COOKIES), help="Output cookies path")
    parser.add_argument("--verify", action="store_true", help="Verify existing cookies")
    args = parser.parse_args()

    cookies_path = Path(args.cookies)

    # Resolve proxy from env if not provided
    import os
    proxy = args.proxy or os.environ.get("PROXY_SERVER", "").strip() or None

    if args.verify:
        if not cookies_path.exists():
            print(f"No cookies file at {cookies_path}")
            sys.exit(1)
        ok = await verify_session(cookies_path, proxy)
        sys.exit(0 if ok else 1)
        return

    if args.username and args.password:
        await run_auth_headless(args.username, args.password, args.email,
                                cookies_path, proxy)
    else:
        await run_auth_interactive(cookies_path, proxy)

    print("\nAuthentication complete!")


if __name__ == "__main__":
    asyncio.run(main())