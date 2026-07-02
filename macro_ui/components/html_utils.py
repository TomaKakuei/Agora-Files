from __future__ import annotations
import hashlib
from pathlib import Path
from typing import Any
import os
from fastapi.responses import HTMLResponse

PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent

def _bundle_version_for_files(paths: list[Path], fallback: str = "dev") -> str:
    digest = hashlib.sha1()
    included = 0
    for path in sorted(paths):
        try:
            stat = path.stat()
        except OSError:
            continue
        included += 1
        try:
            relative = path.resolve().relative_to(PACKAGE_ROOT)
        except ValueError:
            relative = path.resolve()
        digest.update(str(relative).encode("utf-8"))
        digest.update(str(stat.st_mtime_ns).encode("utf-8"))
        digest.update(str(stat.st_size).encode("utf-8"))
    if not included:
        return fallback
    return digest.hexdigest()[:12]


def _pixel_bundle_version() -> str:
    return _bundle_version_for_files(
        [
            PACKAGE_ROOT / "frontend" / "index.html",
            PACKAGE_ROOT / "frontend" / "styles.css",
            PACKAGE_ROOT / "frontend" / "src" / "main.js",
            PACKAGE_ROOT / "frontend" / "src" / "WorldScene.js",
            PACKAGE_ROOT / "frontend" / "src" / "AgentManager.js",
        ]
    )


def _creator_bundle_version() -> str:
    return _bundle_version_for_files(
        [
            PACKAGE_ROOT / "world_creator_ui" / "index.html",
            PACKAGE_ROOT / "world_creator_ui" / "styles.css",
            PACKAGE_ROOT / "world_creator_ui" / "app.js",
            PACKAGE_ROOT / "world_creator_ui" / "fixtures" / "demo_draft.js",
        ]
    )


def _render_versioned_html(template_path: Path, replacements: dict[str, str]) -> HTMLResponse:
    text = template_path.read_text(encoding="utf-8")
    for needle, value in replacements.items():
        text = text.replace(needle, value)
    return HTMLResponse(
        content=text,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )

def _static_url(path: Path) -> str:
    return "/" + str(path.resolve().relative_to(PACKAGE_ROOT)).replace(os.sep, "/")

def _static_url_if_local(path: Path | None) -> str:
    if path is None or not path.is_file():
        return ""
    try:
        return _static_url(path)
    except Exception:
        return ""

def _resolve_asset_path(path_value: Any, *, package_root: Path = PACKAGE_ROOT) -> Path | None:
    raw = str(path_value or "").strip()
    if not raw:
        return None
    candidate = Path(raw)
    resolved = (package_root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    if not resolved.is_file():
        return None
    try:
        resolved.relative_to(package_root)
    except Exception:
        return None
    return resolved
