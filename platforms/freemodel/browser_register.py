"""FreeModel browser-assisted registration flow."""
from __future__ import annotations

import os
import re
import time
from typing import Callable, Optional
from urllib.parse import urlparse

try:
    from playwright.sync_api import Page, sync_playwright
except Exception:  # pragma: no cover
    Page = object

    def sync_playwright():
        raise RuntimeError("Playwright is required for FreeModel browser registration")

try:
    from camoufox.sync_api import Camoufox
except Exception:  # pragma: no cover
    Camoufox = None

from platforms.freemodel.core import (
    FREEMODEL_DASHBOARD_URL,
    FREEMODEL_KEYS_URL,
    extract_api_key,
    extract_freemodel_start_code,
)


def _proxy_config(proxy: Optional[str]) -> Optional[dict]:
    if not proxy:
        return None
    parsed = urlparse(proxy)
    if not parsed.scheme or not parsed.hostname or not parsed.port:
        return {"server": proxy}
    config = {"server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"}
    if parsed.username:
        config["username"] = parsed.username
    if parsed.password:
        config["password"] = parsed.password
    return config


class FreemodelBrowserRegister:
    """Register/login FreeModel with mailbox OTP, Telegram binding, and key harvest."""

    def __init__(
        self,
        *,
        headless: bool = True,
        proxy: str | None = None,
        otp_callback: Callable[[], str] | None = None,
        telegram_provider=None,
        log_fn: Callable[[str], None] = print,
        browser_engine: str = "auto",
        user_data_dir: str = "",
        api_key_timeout: int = 45,
    ):
        self.headless = headless
        self.proxy = proxy
        self.otp_callback = otp_callback
        self.telegram_provider = telegram_provider
        self.log = log_fn or print
        self.browser_engine = browser_engine
        self.user_data_dir = user_data_dir
        self.api_key_timeout = api_key_timeout

    def run(self, *, email: str, password: str = "", provider_account_ref: str = "") -> dict:
        if not self.otp_callback:
            raise RuntimeError("FreeModel registration requires an OTP callback")
        with self._browser_context() as context:
            page = context.new_page()
            page.goto(FREEMODEL_KEYS_URL, wait_until="domcontentloaded", timeout=60_000)
            self._submit_email(page, email)
            code = self.otp_callback()
            self._submit_code(page, code)
            self._wait_for_dashboard(page)
            telegram = self._bind_telegram(page, provider_account_ref or email)
            api_key = self._extract_or_create_api_key(page)
            return {
                "email": email,
                "password": password,
                "api_key": api_key,
                "telegram": telegram,
                "dashboard_url": page.url,
            }

    def _browser_context(self):
        proxy = _proxy_config(self.proxy)
        if self.browser_engine in {"camoufox", "auto"} and Camoufox is not None:
            kwargs = {"headless": self.headless}
            if proxy:
                kwargs["proxy"] = proxy
            if self.user_data_dir:
                kwargs["user_data_dir"] = self.user_data_dir
            return Camoufox(**kwargs)

        pw = sync_playwright().start()
        launch_kwargs = {"headless": self.headless}
        if proxy:
            launch_kwargs["proxy"] = proxy
        browser = pw.chromium.launch(**launch_kwargs)

        class _ContextManager:
            def __enter__(self_inner):
                self_inner._browser = browser
                self_inner._pw = pw
                self_inner._context = browser.new_context()
                return self_inner._context

            def __exit__(self_inner, exc_type, exc, tb):
                self_inner._context.close()
                self_inner._browser.close()
                self_inner._pw.stop()

        return _ContextManager()

    def _submit_email(self, page: Page, email: str) -> None:
        email_input = page.locator('input[type="email"], input[name*="email" i]').first
        email_input.wait_for(timeout=30_000)
        email_input.fill(email)
        page.get_by_role("button", name=re.compile(r"(send|code|verification)", re.I)).click(timeout=10_000)
        self.log(f"FreeModel verification code requested for {email}")

    def _submit_code(self, page: Page, code: str) -> None:
        code = str(code or "").strip()
        if not code:
            raise RuntimeError("FreeModel OTP callback returned an empty code")
        inputs = page.locator('input[inputmode="numeric"], input[type="tel"], input[maxlength="1"]')
        if inputs.count() >= len(code):
            for index, digit in enumerate(code):
                inputs.nth(index).fill(digit)
        else:
            page.keyboard.type(code)
        self.log("FreeModel verification code submitted")

    def _wait_for_dashboard(self, page: Page) -> None:
        page.wait_for_url("**/dashboard**", timeout=60_000)
        page.goto(FREEMODEL_DASHBOARD_URL, wait_until="domcontentloaded", timeout=60_000)

    def _bind_telegram(self, page: Page, provider_account_ref: str) -> dict:
        if not self.telegram_provider:
            return {}
        page.get_by_text("Bind Telegram", exact=False).click(timeout=30_000)
        link = self._find_telegram_link(page)
        token = extract_freemodel_start_code(link)
        result = self.telegram_provider.activate_bot_link(
            link,
            provider="freemodel",
            provider_account_ref=provider_account_ref,
        )
        return {
            "start_link": link,
            "start_code": token,
            **result.to_dict(),
        }

    def _find_telegram_link(self, page: Page) -> str:
        deadline = time.time() + 30
        while time.time() < deadline:
            anchors = page.locator('a[href*="FreeModelDevBot"][href*="start="]')
            if anchors.count():
                href = str(anchors.first.get_attribute("href") or "").strip()
                if href:
                    return href
            time.sleep(0.5)
        raise TimeoutError("FreeModel Telegram start link was not found")

    def _extract_or_create_api_key(self, page: Page) -> str:
        page.goto(FREEMODEL_KEYS_URL, wait_until="domcontentloaded", timeout=60_000)
        api_key = extract_api_key(page.inner_text("body", timeout=10_000))
        if api_key:
            return api_key

        for label in ("Create API Key", "New API Key", "Generate", "Create key"):
            try:
                page.get_by_role("button", name=label).click(timeout=3_000)
                break
            except Exception:
                continue

        deadline = time.time() + self.api_key_timeout
        while time.time() < deadline:
            api_key = extract_api_key(page.inner_text("body", timeout=10_000))
            if api_key:
                return api_key
            time.sleep(1)
        if os.environ.get("FREEMODEL_ALLOW_MISSING_API_KEY") == "1":
            return ""
        raise TimeoutError("FreeModel API key was not visible after registration")
