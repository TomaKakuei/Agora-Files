#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._playwright_firefox import launch_headless_firefox_page


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe live Pixel world boot readiness.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8125")
    parser.add_argument("--access-code", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--screenshot", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_url = str(args.base_url).rstrip("/")
    screenshot_path = Path(args.screenshot).expanduser().resolve() if args.screenshot else None
    network_events: list[dict[str, object]] = []
    console_events: list[dict[str, str]] = []
    request_failures: list[dict[str, str]] = []
    page_errors: list[str] = []
    start_monotonic = time.monotonic()
    wait_error = ""
    ready_elapsed_ms = 0

    query = urllib.parse.urlencode(
        {
            "access_code": args.access_code,
            "mode": "live",
            "persist_session": "0",
            "reset_client_state": "1",
            "headless_kick": "1",
            "renderer": "canvas",
        }
    )
    page_url = f"{base_url}/pixel/index.html?{query}"

    with sync_playwright() as playwright:
        with launch_headless_firefox_page(playwright) as (_context, page):
            page.on(
                "response",
                lambda response: (
                    network_events.append(
                        {
                            "url": response.url,
                            "status": response.status,
                        }
                    )
                    if any(
                        marker in response.url
                        for marker in (
                            "current_world_pixel_set.json",
                            "world_map_source.png",
                            "bootstrap_assets.json",
                            "character_atlas.png",
                            "character_atlas.json",
                            "/live/sessions",
                            "/live/state",
                        )
                    )
                    else None
                ),
            )
            page.on(
                "console",
                lambda message: console_events.append(
                    {
                        "type": message.type,
                        "text": message.text,
                    }
                ),
            )
            page.on(
                "pageerror",
                lambda error: page_errors.append(str(error)),
            )
            page.on(
                "requestfailed",
                lambda request: request_failures.append(
                    {
                        "url": request.url,
                        "error": request.failure or "",
                    }
                ),
            )
            page.goto(page_url, wait_until="domcontentloaded", timeout=90000)
            try:
                page.wait_for_function(
                    """
                    () => {
                      const status = String(document.getElementById("event-status")?.textContent || "").trim();
                      const scene = window.__AGORA_PHASER_GAME__?.scene?.keys?.world;
                      const loadedCount = scene?.agentManager?.loadedTextureKeys?.size || 0;
                      const ready = status === "Pixel UI ready"
                        && Boolean(scene?.generatedMapImage)
                        && loadedCount >= 25;
                      return status.startsWith("Startup failed") || ready;
                    }
                    """,
                    timeout=int(float(args.timeout_seconds) * 1000),
                )
                ready_elapsed_ms = round((time.monotonic() - start_monotonic) * 1000)
            except PlaywrightTimeoutError as error:
                wait_error = str(error)
            page.wait_for_timeout(1200)
            if screenshot_path is not None:
                page.screenshot(path=str(screenshot_path), full_page=True)
            probe = page.evaluate(
                """
                async () => {
                  const status = String(document.getElementById("event-status")?.textContent || "").trim();
                  const scene = window.__AGORA_PHASER_GAME__?.scene?.keys?.world;
                  const textureManager = scene?.textures;
                  const atlasEntries = Array.from(scene?.agentManager?.loadedTextureKeys?.entries?.() || []);
                  const manifestAssets = Array.from(scene?.assetResolver?.assetsFromManifest?.() || []);
                  const firstAsset = manifestAssets[0] || null;
                  const resolvedAtlasUrl = firstAsset ? String(scene?.assetResolver?.resolveAssetUrl?.(firstAsset.atlas_url) || "") : "";
                  const resolvedJsonUrl = firstAsset ? String(scene?.assetResolver?.resolveAssetUrl?.(firstAsset.json_url) || "") : "";
                  const timedFetchStatus = async (url) => {
                    if (!url) {
                      return 0;
                    }
                    const controller = new AbortController();
                    const timer = window.setTimeout(() => controller.abort("timeout"), 5000);
                    try {
                      const response = await fetch(url, { cache: "no-store", signal: controller.signal });
                      return Number(response.status || 0);
                    } catch (_error) {
                      return -1;
                    } finally {
                      window.clearTimeout(timer);
                    }
                  };
                  let manualJsonStatus = 0;
                  let manualPngStatus = 0;
                  manualJsonStatus = await timedFetchStatus(resolvedJsonUrl);
                  manualPngStatus = await timedFetchStatus(resolvedAtlasUrl);
                  const atlasSummary = atlasEntries.map(([agentId, textureKey]) => {
                    const exists = Boolean(textureManager?.exists?.(textureKey));
                    const texture = exists ? textureManager.get(textureKey) : null;
                    const source = texture?.getSourceImage?.() || null;
                    return {
                      agent_id: agentId,
                      texture_key: textureKey,
                      exists,
                      width: Number(source?.width || 0),
                      height: Number(source?.height || 0),
                    };
                  });
                  return {
                    status,
                    world_name: String(document.getElementById("world-name")?.textContent || "").trim(),
                    current_agents: Number(scene?.currentAgents?.length || 0),
                    authoritative_agents: Number(scene?.liveState?.authoritativeAgents?.length || 0),
                    live_ready_count: Number(scene?.liveState?.liveReadyAgentIds?.length || 0),
                    loaded_atlas_count: atlasSummary.length,
                    missing_atlas_ids: atlasSummary.filter((entry) => !entry.exists).map((entry) => entry.agent_id),
                    atlas_summary: atlasSummary,
                    generated_map_key: String(scene?.generatedMapKey || ""),
                    generated_map_image: Boolean(scene?.generatedMapImage),
                    generated_map_texture_exists: Boolean(textureManager?.exists?.(scene?.generatedMapKey || "")),
                    asset_manifest_revision: String(scene?.assetSetManifest?.revision || ""),
                    map_asset_url: String(scene?.assetSetManifest?.map_asset_url || ""),
                    bootstrap_asset_count: manifestAssets.length,
                    first_asset_id: String(firstAsset?.id || ""),
                    first_asset_atlas_url: String(firstAsset?.atlas_url || ""),
                    first_asset_json_url: String(firstAsset?.json_url || ""),
                    first_asset_atlas_resolved_url: resolvedAtlasUrl,
                    first_asset_json_resolved_url: resolvedJsonUrl,
                    first_asset_manual_json_status: manualJsonStatus,
                    first_asset_manual_png_status: manualPngStatus,
                    selected_agent_id: String(scene?.agentManager?.selectedAgentId || ""),
                    location_href: String(window.location.href || ""),
                    document_ready_state: String(document.readyState || ""),
                    body_text: String(document.body?.innerText || "").slice(0, 500),
                  };
                }
                """
            )

    elapsed_ms = round((time.monotonic() - start_monotonic) * 1000)
    map_requests = [entry for entry in network_events if "world_map_source.png" in str(entry.get("url", ""))]
    atlas_png_requests = [entry for entry in network_events if "character_atlas.png" in str(entry.get("url", ""))]
    atlas_json_requests = [entry for entry in network_events if "character_atlas.json" in str(entry.get("url", ""))]
    result = {
      "page_url": page_url,
      "elapsed_ms": elapsed_ms,
      "ready_elapsed_ms": ready_elapsed_ms,
      "wait_error": wait_error,
      "probe": probe,
      "network": {
        "map_requests": map_requests,
        "atlas_png_request_count": len(atlas_png_requests),
        "atlas_json_request_count": len(atlas_json_requests),
        "all_atlas_png_200": all(int(entry.get("status", 0)) == 200 for entry in atlas_png_requests),
        "all_atlas_json_200": all(int(entry.get("status", 0)) == 200 for entry in atlas_json_requests),
      },
      "console": console_events,
      "request_failures": request_failures,
      "page_errors": page_errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
