"""BrowserManager — Playwright browser lifecycle, cookie auth, session verification."""

import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright, Browser, BrowserContext, Playwright


class BrowserManager:
    """Manages Playwright browser lifecycle with cookie-based authentication."""

    def __init__(
        self,
        cookies_path: Path,
        proxy: str | None = None,
        headless: bool = True,
        user_agent: str | None = None,
    ):
        self.cookies_path = Path(cookies_path)
        self.proxy = proxy
        self.headless = headless
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._contexts: list[BrowserContext] = []

    @staticmethod
    def load_cookies(cookies_path: Path) -> list[dict]:
        """Load cookies from JSON and adapt to Playwright format.

        The cookies.json file contains {name: value} pairs.

        Playwright requires full cookie objects with: name, value, domain, path, secure, sameSite.

        Special handling for __Host- cookies (strict security cookies):
          - domain must be "x.com" (no leading dot), not ".x.com"
          - secure must be True
          - sameSite must be "Strict"
        Regular cookies use ".x.com", secure=True, sameSite="Strict".
        """
        with open(cookies_path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        adapted = []
        for name, value in raw.items():
            is_secure = name.startswith("__Secure-") or name.startswith("__Host-")
            domain = "x.com" if name.startswith("__Host-") else ".x.com"
            adapted.append({
                "name": name,
                "value": value,
                "domain": domain,
                "path": "/",
                "secure": True,
                "sameSite": "Strict",
            })
        return adapted

    async def _ensure_playwright(self) -> Playwright:
        """Lazily start Playwright."""
        if self._playwright is None:
            self._playwright = await async_playwright().start()
        return self._playwright

    async def _ensure_browser(self) -> Browser:
        """Lazily launch browser."""
        if self._browser is None:
            p = await self._ensure_playwright()
            launch_args = [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ]
            proxy_config = {"server": self.proxy} if self.proxy else None
            self._browser = await p.chromium.launch(
                headless=self.headless,
                proxy=proxy_config,
                args=launch_args,
            )
        return self._browser

    async def new_context(self) -> BrowserContext:
        """Create a new isolated browser context with cookies loaded."""
        browser = await self._ensure_browser()
        context = await browser.new_context(
            user_agent=self.user_agent,
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        cookies = self.load_cookies(self.cookies_path)
        await context.add_cookies(cookies)
        self._contexts.append(context)
        return context

    async def verify_session(self, context: BrowserContext) -> bool:
        """Check if cookies are still valid by navigating to X.com home."""
        try:
            page = await context.new_page()
            await page.goto("https://x.com", timeout=30_000)
            # Look for sign-in indicator — if redirected to login, session is invalid
            await page.wait_for_selector(
                "[data-testid='primaryColumn']",
                timeout=15_000,
            )
            await page.close()
            return True
        except Exception:
            try:
                await page.close()
            except Exception:
                pass
            return False

    async def close(self):
        """Clean up all contexts and browser."""
        for ctx in self._contexts:
            try:
                await ctx.close()
            except Exception:
                pass
        self._contexts.clear()
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    async def __aenter__(self) -> "BrowserManager":
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()