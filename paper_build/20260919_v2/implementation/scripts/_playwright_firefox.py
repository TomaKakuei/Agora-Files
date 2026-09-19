from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from playwright.sync_api import BrowserContext, Page, Playwright


_DEFAULT_VIEWPORT = {"width": 1440, "height": 1024}
_FIREFOX_USER_PREFS = {
    "browser.cache.disk.enable": False,
    "browser.cache.memory.enable": False,
    "browser.sessionstore.resume_from_crash": False,
}
_FIREFOX_ENV_UPDATES = {
    "MOZ_HEADLESS": "1",
    "MOZ_WEBRENDER": "0",
    "MOZ_DISABLE_RDD_SANDBOX": "1",
    "MOZ_DISABLE_CONTENT_SANDBOX": "1",
    "MOZ_DISABLE_GMP_SANDBOX": "1",
    "MOZ_NO_REMOTE": "1",
    "LIBGL_ALWAYS_SOFTWARE": "1",
    "XDG_RUNTIME_DIR": "/tmp",
    "GTK_USE_PORTAL": "0",
}


@contextmanager
def launch_headless_firefox_page(
    playwright: Playwright,
    *,
    viewport: dict[str, int] | None = None,
) -> Iterator[tuple[BrowserContext, Page]]:
    profile_dir = Path(tempfile.mkdtemp(prefix="agora_firefox_profile_", dir="/tmp"))
    previous_env: dict[str, str | None] = {}
    context: BrowserContext | None = None
    try:
        for key, value in _FIREFOX_ENV_UPDATES.items():
            previous_env[key] = os.environ.get(key)
            os.environ[key] = value
        # Give Firefox a private HOME so headless runs do not collide with a user session.
        previous_env["HOME"] = os.environ.get("HOME")
        os.environ["HOME"] = str(profile_dir)
        context = playwright.firefox.launch_persistent_context(
            str(profile_dir),
            headless=True,
            viewport=viewport or dict(_DEFAULT_VIEWPORT),
            service_workers="block",
            firefox_user_prefs=dict(_FIREFOX_USER_PREFS),
        )
        page = context.pages[0] if context.pages else context.new_page()
        yield context, page
    finally:
        if context is not None:
            context.close()
        for key, previous in previous_env.items():
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous
        shutil.rmtree(profile_dir, ignore_errors=True)
