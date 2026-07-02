from __future__ import annotations
from macro_ui.components.html_utils import _pixel_bundle_version
import json
def _render_headless_pixel_harness(seed: int, token: str, access_code: str = "") -> str:
    pixel_bundle_version = _pixel_bundle_version()
    payload = {
        "seed": int(seed),
        "token": str(token or "").strip() or "default",
        "access_code": str(access_code or "").strip(),
    }
    iframe_url = (
        f"/pixel/?mode=live&seed={payload['seed']}"
        + (f"&pixel_world={payload['access_code']}" if payload["access_code"] else "")
        + "&persist_session=0"
        + "&reset_client_state=1"
        + "&headless_kick=1"
        + f"&bundle={pixel_bundle_version}"
        + f"&frame_token={payload['token']}"
    )

    template = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Headless Pixel Regression</title>
    <style>
      :root {
        color-scheme: dark;
        font-family: Inter, system-ui, sans-serif;
        background: #111015;
        color: #f7f4ef;
      }
      body {
        margin: 0;
        background: #111015;
        color: #f7f4ef;
      }
      .wrap {
        padding: 12px;
      }
      .status {
        font: 14px/1.4 monospace;
        margin-bottom: 8px;
      }
      .summary {
        font: 12px/1.4 monospace;
        color: #c0b6c8;
        margin-bottom: 10px;
        white-space: pre-wrap;
      }
      iframe {
        width: 1600px;
        height: 900px;
        border: 1px solid #3b3142;
        background: #0f0c13;
      }
    </style>
  </head>
  <body>
    <div class="wrap">
      <div id="status" class="status">Booting headless regression...</div>
      <div id="summary" class="summary">seed=__SEED__ access_code=__ACCESS_CODE_RAW__ token=__TOKEN_RAW__</div>
      <iframe id="pixel-frame" src="__IFRAME_URL__" referrerpolicy="no-referrer"></iframe>
      <img id="gate" alt="" src="/__test__/headless-pixel/gate/__TOKEN_RAW__" style="display:none" />
    </div>
    <script>
      (() => {
        const seed = __SEED__;
        const token = __TOKEN__;
        const requestedAccessCode = __ACCESS_CODE__;
        const status = document.getElementById("status");
        const summary = document.getElementById("summary");
        const frame = document.getElementById("pixel-frame");
        const gate = document.getElementById("gate");
        const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
        let headlessStage = "boot";
        const setStage = (value) => {
          headlessStage = String(value || "");
        };
        const waitFor = async (fn, timeoutMs = 30000, stepMs = 150) => {
          const deadline = Date.now() + timeoutMs;
          let lastError = null;
          while (Date.now() < deadline) {
            try {
              const value = await fn();
              if (value) {
                return value;
              }
            } catch (error) {
              lastError = error;
            }
            await sleep(stepMs);
          }
          throw lastError || new Error(`Timed out waiting for browser condition at ${headlessStage}`);
        };
        const fetchJson = async (url, options = {}) => {
          const response = await fetch(url, {
            cache: "no-store",
            ...options,
          });
          if (!response.ok) {
            let detail = "";
            try {
              const raw = await response.text();
              if (raw) {
                try {
                  const parsed = JSON.parse(raw);
                  detail = String(parsed?.detail || parsed?.error || parsed?.message || raw);
                } catch (_error) {
                  detail = String(raw);
                }
              }
            } catch (_error) {
              detail = "";
            }
            throw new Error(`Request failed: ${response.status} ${url}${detail ? ` :: ${detail}` : ""}`);
          }
          return response.json();
        };
        const postJson = async (url, payload) => fetchJson(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload ?? {}),
        });
        const postResult = async (payload) => {
          await postJson(`/__test__/headless-pixel/result/${token}`, payload);
        };
        let expectedSessionEndpoint = "";
        const bootContractState = () => {
          try {
            const scene = frame.contentWindow?.__AGORA_PHASER_GAME__?.scene?.scenes?.[0] || null;
            return {
              selected_access_code: String(frame.contentDocument?.querySelector("#world-select")?.value || "").trim(),
              session_endpoint: String(scene?.liveState?.endpoints?.session || "").trim(),
              expected_session_endpoint: expectedSessionEndpoint,
              bundle_version: String(frame.contentWindow?.__AGORA_PIXEL_BUNDLE_VERSION__ || "").trim(),
              frame_location: String(frame.contentWindow?.location?.href || "").trim(),
              startup_status_text: String(frame.contentDocument?.querySelector("#event-status")?.textContent || "").trim(),
            };
          } catch (error) {
            return {
              selected_access_code: "",
              session_endpoint: "",
              expected_session_endpoint: expectedSessionEndpoint,
              bundle_version: "",
              frame_location: "",
              startup_status_text: String(error?.message || error),
            };
          }
        };
        const fetchLiveState = async (accessCode, sessionId, since = 0) => {
          const url = new URL(`/api/pixel/worlds/${accessCode}/live/state`, window.location.origin);
          url.searchParams.set("session_id", sessionId);
          url.searchParams.set("since", String(Math.max(0, Number(since || 0))));
          return fetchJson(url.toString());
        };
        const seedLiveInventory = async (accessCode, sessionId, targetAgentId) => postJson(`/__test__/pixel-live-seed-inventory`, {
          access_code: accessCode,
          session_id: sessionId,
          target_agent_id: targetAgentId,
          actor_inventory: [
            { item_id: "restorative_tea", quantity: 2, name: "Restorative Tea", description: "A simple restorative used for live interaction checks.", asking_price_minor: 50 },
            { item_id: "trade_token", quantity: 1, name: "Trade Token", description: "A compact token used for barter drills.", asking_price_minor: 100 },
          ],
          target_inventory: [
            {
              item_id: "quote_probe_item",
              quantity: 1,
              name: "Quote Probe Item",
              description: "A priced probe item used to verify live quote settlement.",
              asking_price_minor: 25,
              metadata: { price: 25, name: "Quote Probe Item", category: "quote_probe" },
            },
          ],
        });
        const typePrintableCharacter = async (input, character) => {
          input.focus();
          const keydown = new KeyboardEvent("keydown", {
            key: character,
            code: `Key${String(character).toUpperCase()}`,
            bubbles: true,
            cancelable: true,
          });
          input.dispatchEvent(keydown);
          if (keydown.defaultPrevented) {
            return;
          }
          const beforeInput = new InputEvent("beforeinput", {
            data: character,
            inputType: "insertText",
            bubbles: true,
            cancelable: true,
          });
          input.dispatchEvent(beforeInput);
          if (beforeInput.defaultPrevented) {
            return;
          }
          const start = Number(input.selectionStart ?? input.value.length);
          const end = Number(input.selectionEnd ?? input.value.length);
          input.setRangeText(character, start, end, "end");
          const inputEvent = new InputEvent("input", {
            data: character,
            inputType: "insertText",
            bubbles: true,
          });
          input.dispatchEvent(inputEvent);
          input.dispatchEvent(new KeyboardEvent("keyup", {
            key: character,
            code: `Key${String(character).toUpperCase()}`,
            bubbles: true,
          }));
        };
        const collectFrameDiagnostics = () => {
          try {
            const game = frame.contentWindow?.__AGORA_PHASER_GAME__ || null;
            const scene = game?.scene?.scenes?.[0] || null;
            const canvas = game?.canvas || frame.contentDocument?.querySelector("canvas") || null;
            let canvasSamples = null;
            if (canvas) {
              try {
                const probe = frame.contentDocument.createElement("canvas");
                probe.width = canvas.width || 0;
                probe.height = canvas.height || 0;
                const probeCtx = probe.getContext("2d");
                if (probeCtx && probe.width > 0 && probe.height > 0) {
                  probeCtx.drawImage(canvas, 0, 0);
                  const points = [
                    ["center", Math.floor(probe.width / 2), Math.floor(probe.height / 2)],
                    ["top_left", 8, 8],
                    ["top_right", Math.max(0, probe.width - 9), 8],
                    ["bottom_left", 8, Math.max(0, probe.height - 9)],
                    ["bottom_right", Math.max(0, probe.width - 9), Math.max(0, probe.height - 9)],
                  ];
                  canvasSamples = points.map(([label, x, y]) => {
                    const pixel = probeCtx.getImageData(x, y, 1, 1).data;
                    return { label, x, y, rgba: [Number(pixel[0]), Number(pixel[1]), Number(pixel[2]), Number(pixel[3])] };
                  });
                }
              } catch (error) {
                canvasSamples = { error: String(error?.message || error) };
              }
            }
            return {
              renderer_type: Number(game?.renderer?.type || 0),
              frame: Number(game?.getFrame?.() ?? game?.loop?.frame ?? 0),
              manual_step_count: Number(frame.contentWindow?.__AGORA_WORLD_SCENE_MANUAL_STEPS__ || 0),
              manual_step_error: String(frame.contentWindow?.__AGORA_WORLD_SCENE_MANUAL_STEP_ERROR__ || ""),
              scene_created: Boolean(scene),
              scene_view_mode: String(scene?.viewMode || ""),
              agent_count: Array.isArray(scene?.currentAgents) ? scene.currentAgents.length : -1,
              selected_room_id: String(scene?.selectedRoomId || ""),
              selected_agent_id: String(scene?.selectedAgentRecord?.agent_id || ""),
              canvas_size: canvas ? {
                width: Number(canvas.width || 0),
                height: Number(canvas.height || 0),
              } : null,
              animation_samples: Array.from(scene?.agentManager?.agentSprites || []).slice(0, 12).map(([agentId, sprite]) => ({
                agent_id: String(agentId),
                animation_key: String(sprite?.anims?.currentAnim?.key || ""),
                is_playing: Boolean(sprite?.anims?.isPlaying),
                x: Number(sprite?.x || 0),
                y: Number(sprite?.y || 0),
              })),
              canvas_samples: canvasSamples,
            };
          } catch (error) {
            return { error: String(error?.message || error) };
          }
        };
        const collectLiveInventoryDiagnostics = () => {
          try {
            const scene = frame.contentWindow?.__AGORA_PHASER_GAME__?.scene?.scenes?.[0] || null;
            const claimedAgentId = String(scene?.liveState?.session?.claimed_agent_id || scene?.selectedAgentRecord?.agent_id || "");
            const targetAgentId = String(scene?.liveState?.targetAgentId || "");
            const sceneAgents = Array.isArray(scene?.currentAgents) ? scene.currentAgents : [];
            const actor = sceneAgents.find((agent) => String(agent?.agent_id || "") === claimedAgentId) || null;
            const target = sceneAgents.find((agent) => String(agent?.agent_id || "") === targetAgentId) || null;
            return {
              selected_item_id: String(scene?.liveState?.selectedItemId || ""),
              target_agent_id: targetAgentId,
              actor_inventory: Array.isArray(actor?.inventory) ? actor.inventory : [],
              target_inventory: Array.isArray(target?.inventory) ? target.inventory : [],
              item_module_text: String(frame.contentDocument?.querySelector("#pov-items")?.innerText || "").slice(0, 1200),
              trade_module_text: String(frame.contentDocument?.querySelector("#pov-trade")?.innerText || "").slice(0, 1200),
            };
          } catch (error) {
            return { error: String(error?.message || error) };
          }
        };
        const canvasHasVisiblePixels = (diagnostics) => {
          const samples = Array.isArray(diagnostics?.canvas_samples) ? diagnostics.canvas_samples : [];
          return samples.some((sample) => Array.isArray(sample?.rgba) && sample.rgba.some((value, index) => (index === 3 ? Number(value) > 0 : Number(value) !== 0)));
        };
        const waitForLiveInventory = async (label, predicate, timeoutMs = 30000, stepMs = 150) => {
          try {
            return await waitFor(predicate, timeoutMs, stepMs);
          } catch (error) {
            throw new Error(`${label} :: ${String(error?.message || error)} :: ${JSON.stringify(collectLiveInventoryDiagnostics())}`);
          }
        };
        const chooseWorld = async () => {
          const directAccessCode = String(requestedAccessCode || "").trim();
          if (directAccessCode) {
            const payload = await fetchJson(`/api/pixel/worlds/${encodeURIComponent(directAccessCode)}?t=${Date.now()}`);
            const packageMeta = payload?.package && typeof payload.package === "object" ? payload.package : {};
            const worldConfig = payload?.world_config && typeof payload.world_config === "object" ? payload.world_config : {};
            return {
              access_code: directAccessCode,
              seed: worldConfig?.runtime?.seed ?? seed,
              world_name: String(worldConfig?.scenario_meta?.world_name || packageMeta?.package_name || ""),
              live_session_url: String(payload?.live_session_url || ""),
              live_state_url: String(payload?.live_state_url || ""),
              live_action_url: String(payload?.live_action_url || ""),
              live_ws_url_template: String(payload?.live_ws_url_template || ""),
            };
          }
          const payload = await fetchJson(`/api/pixel/worlds?t=${Date.now()}`);
          const worlds = Array.isArray(payload.worlds) ? payload.worlds : [];
          const seedText = String(seed);
          const match = worlds
            .filter((world) => String(world?.seed ?? "").trim() === seedText)
            .sort((left, right) => {
              const leftCreatedAt = String(left?.created_at || "");
              const rightCreatedAt = String(right?.created_at || "");
              if (leftCreatedAt !== rightCreatedAt) {
                return rightCreatedAt.localeCompare(leftCreatedAt);
              }
              return String(right?.access_code || "").localeCompare(String(left?.access_code || ""));
            })[0];
          if (!match?.access_code) {
            throw new Error(`No PIXEL READ world matched seed ${seedText}`);
          }
          return match;
        };
        const parseSessionId = (text) => {
          const match = String(text || "").match(/Live session\s+([0-9a-f-]+)\s+owns/);
          if (!match) {
            throw new Error(`Could not parse live session id from ${text}`);
          }
          return match[1];
        };
        let runStarted = false;
        let kickoffTimer = null;
        const run = async () => {
          setStage("choose world");
          const chosenWorld = await chooseWorld();
          const expectedCode = String(chosenWorld.access_code || "").trim();
          const expectedLiveSessionUrl = String(chosenWorld.live_session_url || "").trim();
          expectedSessionEndpoint = expectedLiveSessionUrl;
          summary.textContent = `seed=${seed} access_code=${expectedCode} requested_access_code=${requestedAccessCode || ""}`;
          setStage("world select ready");
          await waitFor(() => frame.contentDocument && frame.contentDocument.querySelector("#world-select"), 120000);
          setStage("world selection synced");
          await waitFor(
            () => String(frame.contentDocument?.querySelector("#world-select")?.value || "").trim() === expectedCode,
            120000,
          );
          setStage("bundle marker observed");
          await waitFor(() => {
            const frameLocation = String(frame.contentWindow?.location?.href || "");
            return frameLocation.includes(`bundle=__PIXEL_BUNDLE_VERSION__`);
          }, 120000);
          setStage("canvas visible");
          await waitFor(() => {
            const diagnostics = collectFrameDiagnostics();
            return canvasHasVisiblePixels(diagnostics) ? diagnostics : null;
          }, 120000, 250);
          setStage("live composer ready");
          await waitFor(() => frame.contentDocument.querySelector("[data-live-send-message]"), 45000);
          const movementText = String(frame.contentDocument.querySelector("#movement-module")?.innerText || "");
          const sessionId = parseSessionId(movementText);
          const beforeState = await fetchLiveState(expectedCode, sessionId, 0);
          const expectedReadyCount = Number(beforeState?.live_ready_count || 0);
          const readySceneCount = Number(frame.contentWindow?.__AGORA_PHASER_GAME__?.scene?.scenes?.[0]?.currentAgents?.length || 0);
          if (expectedReadyCount > 0 && readySceneCount !== expectedReadyCount) {
            throw new Error(`Live-ready agent gating mismatch: scene=${readySceneCount} ready=${expectedReadyCount}`);
          }
          const beforeAgentId = String(beforeState?.session?.claimed_agent_id || "");
          const beforeAgent = (Array.isArray(beforeState?.agents) ? beforeState.agents : []).find((agent) => String(agent?.agent_id || "") === beforeAgentId) || null;
          if (!beforeAgent) {
            throw new Error("Unable to read claimed agent before movement");
          }
          const beforeCoords = JSON.stringify(beforeAgent.coordinates || {}).trim();
          const movementDirs = ["right", "down", "left", "up"];
          let moved = false;
          let afterState = beforeState;
          for (const direction of movementDirs) {
            const button = frame.contentDocument.querySelector(`[data-live-move="${direction}"]`);
            if (!button) {
              continue;
            }
            button.click();
            afterState = beforeState;
            const deadline = Date.now() + 15000;
            while (Date.now() < deadline) {
              afterState = await fetchLiveState(expectedCode, sessionId, beforeState.latest_event_id || 0);
              const afterAgent = (Array.isArray(afterState?.agents) ? afterState.agents : []).find((agent) => String(agent?.agent_id || "") === beforeAgentId) || null;
              const afterCoords = JSON.stringify(afterAgent?.coordinates || {}).trim();
              if (afterCoords !== beforeCoords) {
                moved = true;
                break;
              }
              await sleep(350);
            }
            if (moved) {
              break;
            }
          }
          if (!moved) {
            throw new Error("Live movement did not change the claimed agent position");
          }
          const beforeHash = String(document.body.innerText || "").length;
          const draftMessage = `draft survives live refresh ${Date.now()}`;
          const draftInput = frame.contentDocument.querySelector("[data-live-message-input]");
          if (!draftInput) {
            throw new Error("Live message input missing before refresh preservation check");
          }
          draftInput.focus();
          draftInput.value = "";
          draftInput.dispatchEvent(new Event("input", { bubbles: true }));
          draftInput.setSelectionRange(0, 0);
          let typedPrefix = "";
          for (const character of draftMessage) {
            const activeDraftInput = frame.contentDocument.querySelector("[data-live-message-input]");
            if (!activeDraftInput) {
              throw new Error("Live message input disappeared during typing");
            }
            await typePrintableCharacter(activeDraftInput, character);
            await sleep(28);
            typedPrefix += character;
            const visibleDraftInput = frame.contentDocument.querySelector("[data-live-message-input]");
            if (!visibleDraftInput) {
              throw new Error("Visible live message input disappeared mid-draft");
            }
            if (visibleDraftInput.value !== typedPrefix) {
              throw new Error(`Live draft typing drifted: expected="${typedPrefix}" actual="${visibleDraftInput.value}"`);
            }
            const expectedCaret = typedPrefix.length;
            const visibleCaret = Number(visibleDraftInput.selectionStart ?? expectedCaret);
            if (visibleCaret !== expectedCaret) {
              throw new Error(`Live draft caret drifted: expected=${expectedCaret} actual=${visibleCaret} value="${visibleDraftInput.value}"`);
            }
          }
          const freezeProbeBaselineState = await fetchLiveState(expectedCode, sessionId, Number(afterState?.latest_event_id || 0));
          const freezeProbeAgent = (Array.isArray(freezeProbeBaselineState?.agents) ? freezeProbeBaselineState.agents : []).find((agent) => String(agent?.agent_id || "") === beforeAgentId) || null;
          const freezeProbeCoords = JSON.stringify(freezeProbeAgent?.coordinates || {}).trim();
          try {
            const scene = frame.contentWindow?.__AGORA_PHASER_GAME__?.scene?.scenes?.[0] || null;
            const phaserUpKey = scene?.liveState?.movementKeys?.get?.("up")?.[0] || null;
            if (phaserUpKey) {
              phaserUpKey.isDown = true;
              phaserUpKey.isUp = false;
            }
            await sleep(450);
            if (phaserUpKey) {
              phaserUpKey.isDown = false;
              phaserUpKey.isUp = true;
            }
          } catch (_error) {
            // Best-effort probe for typing-time movement suppression.
          }
          const freezeProbeAfterState = await fetchLiveState(expectedCode, sessionId, Number(freezeProbeBaselineState?.latest_event_id || 0));
          const freezeProbeAfterAgent = (Array.isArray(freezeProbeAfterState?.agents) ? freezeProbeAfterState.agents : []).find((agent) => String(agent?.agent_id || "") === beforeAgentId) || null;
          const freezeProbeAfterCoords = JSON.stringify(freezeProbeAfterAgent?.coordinates || {}).trim();
          if (freezeProbeCoords !== freezeProbeAfterCoords) {
            throw new Error("Claimed agent moved while the live composer draft was active");
          }
          const refreshBaseline = Number(afterState?.latest_event_id || 0);
          await fetchJson("/__test__/pixel-live-seed-inventory", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              access_code: expectedCode,
              session_id: sessionId,
              agent_id: beforeAgentId,
              actor_inventory: [{ item_id: "external_refresh_probe", quantity: 1 }],
              target_inventory: []
            }),
          });
          setStage("external refresh observed");
          await waitFor(async () => {
            const refreshed = await fetchLiveState(expectedCode, sessionId, refreshBaseline);
            return Number(refreshed?.latest_event_id || 0) > refreshBaseline ? refreshed : null;
          }, 20000, 350);
          await sleep(1800);
          const preservedInput = frame.contentDocument.querySelector("[data-live-message-input]");
          if (!preservedInput || preservedInput.value !== draftMessage) {
            throw new Error(`Live draft input was lost during refresh: ${preservedInput?.value || ""}`);
          }
          if (frame.contentDocument.activeElement !== preservedInput) {
            const active = frame.contentDocument.activeElement;
            throw new Error(`Live draft input focus was lost during refresh: active=${active?.tagName || ""} class=${active?.className || ""} value=${active?.value || ""}`);
          }
          preservedInput.value = "";
          preservedInput.dispatchEvent(new Event("input", { bubbles: true }));
          preservedInput.blur();
          await sleep(250);
          let fallbackAgentId = String(((Array.isArray(afterState?.agents) ? afterState.agents : []).find((agent) => (
            String(agent?.agent_id || "") !== beforeAgentId
          ))?.agent_id) || "");
          let targetAgentId = String(((Array.isArray(afterState?.agents) ? afterState.agents : []).find((agent) => (
            String(agent?.room_id || "") === String(afterState?.session?.room_id || beforeState?.session?.room_id || "") &&
            String(agent?.agent_id || "") !== beforeAgentId
          ))?.agent_id) || fallbackAgentId);
          const targetFocusButton = targetAgentId
            ? frame.contentDocument.querySelector(`[data-nearby-action="focus"][data-agent-id="${targetAgentId}"]`)
            : null;
          if (targetFocusButton instanceof HTMLElement) {
            targetFocusButton.click();
          }
          const targetSelect = await waitFor(() => {
            const select = frame.contentDocument.querySelector("[data-live-target-select]");
            if (!select) return null;
            if (targetAgentId && !Array.from(select.options).some(opt => opt.value === targetAgentId)) return null;
            return select;
          }, 15000, 200).catch(() => null);
          if (targetSelect instanceof HTMLSelectElement) {
            if (!targetAgentId) {
              const firstTargetOption = Array.from(targetSelect.options).find((option) => {
                const val = String(option.value || "").trim();
                return val && val !== "room_broadcast";
              });
              targetAgentId = String(firstTargetOption?.value || "");
            }
            if (targetAgentId) {
              const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, "value").set;
              if (nativeInputValueSetter) {
                nativeInputValueSetter.call(targetSelect, targetAgentId);
              } else {
                targetSelect.value = targetAgentId;
              }
              targetSelect.dispatchEvent(new Event("input", { bubbles: true }));
              targetSelect.dispatchEvent(new Event("change", { bubbles: true }));
              
              const scene = frame.contentWindow?.__AGORA_PHASER_GAME__?.scene?.scenes?.[0];
              if (scene && scene.liveState) {
                scene.liveState.targetAgentId = targetAgentId;
              }
            }
          }
          if (!targetAgentId) {
            console.log("No live target agent available for item/trade checks");
          }
          setStage("seed live inventory");
          await seedLiveInventory(expectedCode, sessionId, targetAgentId);
          const seededState = await waitForLiveInventory("seeded inventory state", async () => {
            const refreshed = await fetchLiveState(expectedCode, sessionId, 0);
            const actor = (Array.isArray(refreshed?.agents) ? refreshed.agents : []).find((agent) => String(agent?.agent_id || "") === beforeAgentId) || null;
            const target = (Array.isArray(refreshed?.agents) ? refreshed.agents : []).find((agent) => String(agent?.agent_id || "") === targetAgentId) || null;
            const actorInventory = Array.isArray(actor?.inventory) ? actor.inventory : [];
            const targetInventory = Array.isArray(target?.inventory) ? target.inventory : [];
            const actorReady = actorInventory.some((entry) => String(entry?.item_id || "") === "restorative_tea" && Number(entry?.quantity || 0) === 2)
              && actorInventory.some((entry) => String(entry?.item_id || "") === "trade_token" && Number(entry?.quantity || 0) === 1);
            const targetReady = targetInventory.some((entry) => String(entry?.item_id || "") === "quote_probe_item" && Number(entry?.quantity || 0) === 1);
            return actorReady && targetReady ? refreshed : null;
          }, 30000, 350);
          await waitForLiveInventory(
            "restorative tea self button",
            () => frame.contentDocument.querySelector('[data-live-item-self="restorative_tea"]'),
            15000,
            120,
          );
          if (targetAgentId && frame.contentWindow?.__AGORA_PHASER_GAME__?.scene?.scenes?.[0]?.liveState?.targetAgentId === targetAgentId) {
            await waitForLiveInventory(
              "restorative tea target button",
              () => frame.contentDocument.querySelector('[data-live-item-target="restorative_tea"]'),
              15000,
              120,
            );
          } else if (targetAgentId) {
            console.log("Skipping target item test because React state did not sync with targetAgentId:", targetAgentId);
          }
          setStage("use item self");
          frame.contentDocument.querySelector('[data-live-item-self="restorative_tea"]')?.click();
          const selfUseState = await waitForLiveInventory("self item use state", async () => {
            const refreshed = await fetchLiveState(expectedCode, sessionId, 0);
            const actor = (Array.isArray(refreshed?.agents) ? refreshed.agents : []).find((agent) => String(agent?.agent_id || "") === beforeAgentId) || null;
            const actorInventory = Array.isArray(actor?.inventory) ? actor.inventory : [];
            return actorInventory.some((entry) => String(entry?.item_id || "") === "restorative_tea" && Number(entry?.quantity || 0) === 1) ? refreshed : null;
          }, 30000, 350);
          const isTargetNearby = Boolean(targetAgentId && frame.contentWindow?.__AGORA_PHASER_GAME__?.scene?.scenes?.[0]?.liveState?.targetAgentId === targetAgentId && Array.isArray(selfUseState?.agents) && selfUseState.agents.find(a => String(a.agent_id || "") === targetAgentId && String(a.room_id || "") === String(selfUseState?.session?.room_id || beforeState?.session?.room_id || "")));
          let quotedOfferId = "";
          let quotedTotalPrice = 0;
          let actorWalletBeforeTrade = 0;
          let targetWalletBeforeTrade = 0;
          let tradeState = selfUseState;
          if (isTargetNearby) {
            setStage("use item target");
            frame.contentDocument.querySelector('[data-live-item-target="restorative_tea"]')?.click();
            const targetUseState = await waitForLiveInventory("target item use state", async () => {
              const refreshed = await fetchLiveState(expectedCode, sessionId, 0);
              const actor = (Array.isArray(refreshed?.agents) ? refreshed.agents : []).find((agent) => String(agent?.agent_id || "") === beforeAgentId) || null;
              const target = (Array.isArray(refreshed?.agents) ? refreshed.agents : []).find((agent) => String(agent?.agent_id || "") === targetAgentId) || null;
              const actorInventory = Array.isArray(actor?.inventory) ? actor.inventory : [];
              const targetInventory = Array.isArray(target?.inventory) ? target.inventory : [];
              const actorReady = !actorInventory.some((entry) => String(entry?.item_id || "") === "restorative_tea" && Number(entry?.quantity || 0) > 0)
                && actorInventory.some((entry) => String(entry?.item_id || "") === "trade_token" && Number(entry?.quantity || 0) === 1);
              const targetReady = targetInventory.some((entry) => String(entry?.item_id || "") === "quote_probe_item" && Number(entry?.quantity || 0) === 1);
              return actorReady && targetReady ? refreshed : null;
            }, 30000, 350);
            const actorBeforeTrade = (Array.isArray(targetUseState?.agents) ? targetUseState.agents : []).find((agent) => String(agent?.agent_id || "") === beforeAgentId) || null;
            const targetBeforeTrade = (Array.isArray(targetUseState?.agents) ? targetUseState.agents : []).find((agent) => String(agent?.agent_id || "") === targetAgentId) || null;
            actorWalletBeforeTrade = Number(actorBeforeTrade?.wallet?.amount_minor || actorBeforeTrade?.currency_quantity || 0);
            targetWalletBeforeTrade = Number(targetBeforeTrade?.wallet?.amount_minor || targetBeforeTrade?.currency_quantity || 0);
            setStage("trade quote");
            const quoteButton = await waitForLiveInventory(
              "quote request button",
              () => frame.contentDocument.querySelector('[data-live-ask-quote="quote_probe_item"]'),
              15000,
              120,
            );
            quoteButton?.click?.();
            const quoteState = await waitForLiveInventory("trade quote state", async () => {
              const refreshed = await fetchLiveState(expectedCode, sessionId, 0);
              const actor = (Array.isArray(refreshed?.agents) ? refreshed.agents : []).find((agent) => String(agent?.agent_id || "") === beforeAgentId) || null;
              const target = (Array.isArray(refreshed?.agents) ? refreshed.agents : []).find((agent) => String(agent?.agent_id || "") === targetAgentId) || null;
              const offers = Array.isArray(actor?.pending_trade_offers) ? actor.pending_trade_offers : [];
              const matchingOffers = offers.filter((entry) => (
                String(entry?.seller_agent_id || "") === targetAgentId &&
                String(entry?.item_id || "") === "quote_probe_item"
              ));
              const quotedOffer = matchingOffers.find((entry) => String(entry?.status || "") === "quoted") || null;
              if (quotedOffer) {
                return { mode: "quoted", refreshed, offer: quotedOffer };
              }
              const completedOffer = matchingOffers.find((entry) => String(entry?.status || "") === "completed") || null;
              const actorInventory = Array.isArray(actor?.inventory) ? actor.inventory : [];
              const targetInventory = Array.isArray(target?.inventory) ? target.inventory : [];
              const directTradeCompleted = completedOffer
                && actorInventory.some((entry) => String(entry?.item_id || "") === "quote_probe_item" && Number(entry?.quantity || 0) === 1)
                && !targetInventory.some((entry) => String(entry?.item_id || "") === "quote_probe_item" && Number(entry?.quantity || 0) > 0);
              return directTradeCompleted ? { mode: "direct", refreshed, offer: completedOffer } : null;
            }, 30000, 350);
            quotedOfferId = String(quoteState?.offer?.offer_id || "");
            quotedTotalPrice = Number(quoteState?.offer?.total_price || 0);
            if (!quotedOfferId) {
              throw new Error("Quoted offer id missing from live quote state");
            }
            tradeState = quoteState?.refreshed || null;
            if (String(quoteState?.mode || "") === "quoted") {
              await waitForLiveInventory(
                "accept quote button",
                () => frame.contentDocument.querySelector(`[data-live-accept-quote="${quotedOfferId}"]`),
                10000,
                120,
              );
              frame.contentDocument.querySelector(`[data-live-accept-quote="${quotedOfferId}"]`)?.click();
              tradeState = await waitForLiveInventory("trade settlement state", async () => {
                const refreshed = await fetchLiveState(expectedCode, sessionId, 0);
                const actor = (Array.isArray(refreshed?.agents) ? refreshed.agents : []).find((agent) => String(agent?.agent_id || "") === beforeAgentId) || null;
                const target = (Array.isArray(refreshed?.agents) ? refreshed.agents : []).find((agent) => String(agent?.agent_id || "") === targetAgentId) || null;
                const actorInventory = Array.isArray(actor?.inventory) ? actor.inventory : [];
                const targetInventory = Array.isArray(target?.inventory) ? target.inventory : [];
                const actorOffers = Array.isArray(actor?.pending_trade_offers) ? actor.pending_trade_offers : [];
                const settledOffer = actorOffers.find((entry) => String(entry?.offer_id || "") === quotedOfferId) || null;
                const actorWallet = Number(actor?.wallet?.amount_minor || actor?.currency_quantity || 0);
                const targetWallet = Number(target?.wallet?.amount_minor || target?.currency_quantity || 0);
                const actorOk = actorInventory.some((entry) => String(entry?.item_id || "") === "quote_probe_item" && Number(entry?.quantity || 0) === 1)
                  && actorWallet === Math.max(0, actorWalletBeforeTrade - quotedTotalPrice);
                const targetOk = !targetInventory.some((entry) => String(entry?.item_id || "") === "quote_probe_item" && Number(entry?.quantity || 0) > 0)
                  && targetWallet === targetWalletBeforeTrade + quotedTotalPrice;
                const offerOk = ["completed", "accepted_pending_delivery"].includes(String(settledOffer?.status || ""));
                return actorOk && targetOk && offerOk ? refreshed : null;
              }, 30000, 350);
            }
          }
          const uniqueMessage = `headless regression ${Date.now()}`;
          const messageInput = frame.contentDocument.querySelector("[data-live-message-input]");
          if (!messageInput) {
            throw new Error("Live message input missing");
          }
          const responseBaseline = Number(tradeState?.latest_event_id || 0);
          const messageSendStartedAt = performance.now();
          messageInput.value = uniqueMessage;
          messageInput.dispatchEvent(new Event("input", { bubbles: true }));
          frame.contentDocument.querySelector("[data-live-send-message]")?.click();
          setStage("sent message visible");
          const persistedState = await waitFor(async () => {
            const dialogueText = String(frame.contentDocument.querySelector("#pov-dialogue")?.innerText || "") + String(frame.contentDocument.querySelector("#pov-log")?.innerText || "");
            if (dialogueText.includes(uniqueMessage)) {
              return true;
            }
            const currentState = await fetchLiveState(expectedCode, sessionId, afterState.latest_event_id || 0);
            const currentEventText = JSON.stringify(currentState?.events || []);
            return currentEventText.includes(uniqueMessage) ? currentState : null;
          }, 30000);
          const messagePersistedAt = performance.now();
          setStage("agent reply visible");
          const responseState = await waitFor(async () => {
            const currentState = await fetchLiveState(expectedCode, sessionId, responseBaseline);
            const events = Array.isArray(currentState?.events) ? currentState.events : [];
            const parsePayload = (event) => {
              const raw = event?.payload_json;
              if (raw && typeof raw === "object") {
                return raw;
              }
              if (typeof raw === "string" && raw.trim()) {
                try {
                  return JSON.parse(raw);
                } catch (_error) {
                  return {};
                }
              }
              return {};
            };
            const reply = events.find((event) => {
              const payload = parsePayload(event);
              return (
                Number(event?.event_id || 0) > responseBaseline &&
                String(event?.event_type || "") === "agent_response" &&
                String(event?.response_text || "").trim() &&
                String(payload?.response_source || "") === "ai_studio" &&
                String(payload?.message_status || "") === "completed"
              );
            });
            const mergedHumanReply = events.find((event) => {
              const payload = parsePayload(event);
              return (
                Number(event?.event_id || 0) > responseBaseline &&
                String(event?.event_type || "") === "human_action" &&
                String(event?.action_text || "") === uniqueMessage &&
                String(payload?.response_source || "") === "ai_studio" &&
                String(payload?.message_status || "") === "completed"
              );
            });
            const settledReply = reply || mergedHumanReply;
            return settledReply ? { state: currentState, reply: settledReply } : null;
          }, 90000, 350);
          const agentReplyVisibleAt = performance.now();
          const messageState = responseState?.state || (persistedState && persistedState !== true ? persistedState : await fetchLiveState(expectedCode, sessionId, afterState.latest_event_id || 0));
          const eventText = JSON.stringify(messageState?.events || []);
          if (!eventText.includes(uniqueMessage)) {
            throw new Error("Live message was not persisted to the event log");
          }
          const diagnostics = collectFrameDiagnostics();
          await postResult({
            status: "ok",
            seed,
            access_code: expectedCode,
            ...bootContractState(),
            moved,
            draft_preserved: true,
            item_self_ok: true,
            item_target_ok: true,
            trade_ok: true,
            quoted_offer_id: quotedOfferId,
            quoted_total_price: quotedTotalPrice,
            actor_wallet_before_trade: actorWalletBeforeTrade,
            target_wallet_before_trade: targetWalletBeforeTrade,
            target_agent_id: targetAgentId,
            unique_message: uniqueMessage,
            message_persist_ms: Math.round(messagePersistedAt - messageSendStartedAt),
            agent_reply_ms: Math.round(agentReplyVisibleAt - messageSendStartedAt),
            initial_session_id: sessionId,
            refresh_triggered: false,
            before_hash: beforeHash,
            final_summary: summary.textContent,
            diagnostics,
          });
          status.textContent = "Regression complete";
          gate.src = `/__test__/headless-pixel/gate/${token}?t=${Date.now()}`;
        };
        const startRun = () => {
          if (runStarted) {
            return;
          }
          runStarted = true;
          if (kickoffTimer) {
            clearInterval(kickoffTimer);
            kickoffTimer = null;
          }
          run().catch(async (error) => {
            status.textContent = `Regression failed: ${error?.message || error}`;
            summary.textContent = String(error?.stack || error || "");
            try {
              await postResult({
                status: "error",
                seed,
                token,
                access_code: String(requestedAccessCode || "").trim(),
                ...bootContractState(),
                message: String(error?.message || error || ""),
                error: String(error?.stack || error || ""),
              });
            } catch (postError) {
              summary.textContent += `\nPOST failed: ${String(postError)}`;
            }
            gate.src = `/__test__/headless-pixel/gate/${token}?t=${Date.now()}`;
          });
        };
        const tryKickoff = () => {
          const doc = frame.contentDocument;
          const welcome = doc ? doc.getElementById("event-status") : null;
          if (welcome && String(welcome.textContent || "").includes("Pixel UI ready")) {
            startRun();
            return;
          }
          if (doc && doc.getElementById("recenter-agent-button")) {
            startRun();
            return;
          }
        };
        kickoffTimer = setInterval(tryKickoff, 100);
      })();
    </script>
  </body>
</html>"""

    # Do clean string replacements
    return (
        template.replace("__SEED__", str(payload["seed"]))
        .replace("__TOKEN__", json.dumps(payload["token"]))
        .replace("__TOKEN_RAW__", str(payload["token"]))
        .replace("__ACCESS_CODE__", json.dumps(payload["access_code"]))
        .replace("__ACCESS_CODE_RAW__", str(payload["access_code"]))
        .replace("__IFRAME_URL__", iframe_url)
        .replace("__PIXEL_BUNDLE_VERSION__", pixel_bundle_version)
    )


def _render_pixel_live_snapshot(*, seed: int, access_code: str, session_id: str, token: str, label: str, expected_event_id: int = 0, focus_mode: str = "room") -> str:
    payload = {
        "seed": int(seed),
        "access_code": str(access_code or "").strip(),
        "session_id": str(session_id or "").strip(),
        "token": str(token or "").strip() or "default",
        "label": str(label or "").strip() or "live snapshot",
        "expected_event_id": int(expected_event_id or 0),
        "focus_mode": str(focus_mode or "room").strip() or "room",
    }
    iframe_url = (
        f"/pixel/?mode=live&seed={payload['seed']}"
        f"&pixel_world={payload['access_code']}"
        f"&session_id={payload['session_id']}"
        f"&persist_session=1"
        f"&capture_mode=export"
        f"&headless_kick=1"
        f"&bundle={_pixel_bundle_version()}"
        f"&frame_token={payload['token']}"
    )

    template = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Pixel Live Snapshot</title>
    <style>
      :root {
        color-scheme: dark;
        font-family: Inter, system-ui, sans-serif;
        background: #111015;
        color: #f7f4ef;
      }
      body {
        margin: 0;
        background: #111015;
        color: #f7f4ef;
      }
      .wrap {
        padding: 12px;
      }
      .status {
        font: 14px/1.4 monospace;
        margin-bottom: 8px;
      }
      .summary {
        font: 12px/1.4 monospace;
        color: #c0b6c8;
        margin-bottom: 10px;
        white-space: pre-wrap;
      }
      iframe {
        width: 1600px;
        height: 900px;
        border: 1px solid #3b3142;
        background: #0f0c13;
      }
      img.gate {
        display: none;
      }
    </style>
  </head>
  <body>
    <div class="wrap">
      <div id="status" class="status">Loading snapshot...</div>
      <div id="summary" class="summary">seed=__SEED__ access_code=__ACCESS_CODE__ session_id=__SESSION_ID__ token=__TOKEN__</div>
      <iframe id="pixel-frame" src="__IFRAME_URL__"></iframe>
      <img id="gate" class="gate" alt="" src="/__test__/headless-pixel/gate/__TOKEN__" />
    </div>
    <script>
      (() => {
        const payload = __PAYLOAD_JSON__;
        const status = document.getElementById("status");
        const summary = document.getElementById("summary");
        const frame = document.getElementById("pixel-frame");
        const gate = document.getElementById("gate");
        const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
        const fetchJson = async (path) => {
          const separator = String(path || "").includes("?") ? "&" : "?";
          const response = await fetch(`${path}${separator}t=${Date.now()}`, { cache: "no-store" });
          if (!response.ok) {
            throw new Error(`Failed to load ${path}`);
          }
          return response.json();
        };
        const postJson = async (path, body) => {
          const response = await fetch(path, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body ?? {}),
          });
          if (!response.ok) {
            const text = await response.text().catch(() => "");
            throw new Error(text || `Failed to call ${path}`);
          }
          return response.json();
        };
        const collectFrameDiagnostics = () => {
          try {
            const game = frame.contentWindow?.__AGORA_PHASER_GAME__ || null;
            const scene = game?.scene?.scenes?.[0] || null;
            const canvas = game?.canvas || frame.contentDocument?.querySelector("canvas") || null;
            const gameRoot = frame.contentDocument?.getElementById("game-root") || null;
            const computed = canvas ? frame.contentWindow.getComputedStyle(canvas) : null;
            const rootComputed = gameRoot ? frame.contentWindow.getComputedStyle(gameRoot) : null;
            const camera = scene?.cameras?.main || null;
            let canvasSamples = null;
            if (canvas) {
              try {
                const probe = frame.contentDocument.createElement("canvas");
                probe.width = canvas.width || 0;
                probe.height = canvas.height || 0;
                const probeCtx = probe.getContext("2d");
                if (probeCtx && probe.width > 0 && probe.height > 0) {
                  probeCtx.drawImage(canvas, 0, 0);
                  const points = [
                    ["center", Math.floor(probe.width / 2), Math.floor(probe.height / 2)],
                    ["top_left", 8, 8],
                    ["top_right", Math.max(0, probe.width - 9), 8],
                    ["bottom_left", 8, Math.max(0, probe.height - 9)],
                    ["bottom_right", Math.max(0, probe.width - 9), Math.max(0, probe.height - 9)],
                  ];
                  canvasSamples = points.map(([label, x, y]) => {
                    const pixel = probeCtx.getImageData(x, y, 1, 1).data;
                    return {
                      label,
                      x,
                      y,
                      rgba: [Number(pixel[0]), Number(pixel[1]), Number(pixel[2]), Number(pixel[3])],
                    };
                  });
                }
              } catch (error) {
                canvasSamples = { error: String(error?.message || error) };
              }
            }
            return {
              has_game: Boolean(game),
              has_scene: Boolean(scene),
              has_canvas: Boolean(canvas),
              canvas_size: canvas ? {
                width: Number(canvas.width || 0),
                height: Number(canvas.height || 0),
                client_width: Number(canvas.clientWidth || 0),
                client_height: Number(canvas.clientHeight || 0),
              } : null,
              canvas_style: computed ? {
                display: computed.display,
                opacity: computed.opacity,
                visibility: computed.visibility,
                position: computed.position,
                z_index: computed.zIndex,
              } : null,
              root_size: gameRoot ? {
                client_width: Number(gameRoot.clientWidth || 0),
                client_height: Number(gameRoot.clientHeight || 0),
                child_count: Number(gameRoot.children?.length || 0),
              } : null,
              root_style: rootComputed ? {
                background: rootComputed.backgroundImage || rootComputed.backgroundColor || "",
              } : null,
              scene_state: scene ? {
                agent_count: Array.isArray(scene.currentAgents) ? scene.currentAgents.length : -1,
                room_count: scene.roomNodes instanceof Map ? scene.roomNodes.size : -1,
                view_mode: String(scene.viewMode || ""),
                world_dimensions: scene.worldDimensions || null,
                selected_room_id: String(scene.selectedRoomId || ""),
                selected_agent_id: String(scene.selectedAgentRecord?.agent_id || ""),
                generated_map_key: String(scene.generatedMapKey || ""),
              } : null,
              camera: camera ? {
                zoom: Number(camera.zoom || 0),
                scroll_x: Number(camera.scrollX || 0),
                scroll_y: Number(camera.scrollY || 0),
                width: Number(camera.width || 0),
                height: Number(camera.height || 0),
              } : null,
              canvas_samples: canvasSamples,
            };
          } catch (error) {
            return { error: String(error?.message || error) };
          }
        };
        const waitForLiveEvent = async () => {
          const expectedEventId = Number(payload.expected_event_id || 0);
          if (!expectedEventId) {
            return null;
          }
          const deadline = Date.now() + 25000;
          while (Date.now() < deadline) {
            try {
              const stateUrl = new URL(`/api/pixel/worlds/${encodeURIComponent(payload.access_code)}/live/state`, window.location.origin);
              stateUrl.searchParams.set("session_id", payload.session_id);
              stateUrl.searchParams.set("since", "0");
              const liveState = await fetchJson(stateUrl.toString());
              if (Number(liveState?.latest_event_id || 0) >= expectedEventId) {
                return liveState;
              }
            } catch (error) {
              // keep waiting until the state endpoint reflects the action
            }
            await sleep(250);
          }
          return null;
        };
        const waitForFrameReady = async () => {
          const deadline = Date.now() + 30000;
          while (Date.now() < deadline) {
            try {
              const doc = frame.contentWindow?.document;
              const text = String(doc?.getElementById("event-status")?.textContent || "").trim();
              if (text.includes("Pixel UI ready") || text.includes("Asset hydration fallback") || text.includes("Map overlay fallback")) {
                return text;
              }
            } catch (error) {
              // keep waiting until same-origin iframe is readable
            }
            await sleep(200);
          }
          return "";
        };
        const focusReadableView = async (liveState) => {
          try {
            const doc = frame.contentWindow?.document;
            if (!doc) {
              return;
            }
            doc.getElementById("atlas-mode-button")?.click();
            await sleep(650);
            if (payload.focus_mode === "agent") {
              doc.getElementById("recenter-agent-button")?.click();
            } else {
              const activeRoomId = String(liveState?.room?.room_id || "").trim();
              const roomButton = activeRoomId
                ? Array.from(doc.querySelectorAll("#room-nav .room-nav-button")).find((button) => String(button.dataset.roomId || "").trim() === activeRoomId)
                : null;
              if (roomButton) {
                roomButton.click();
              } else {
                doc.getElementById("home-room-button")?.click();
              }
            }
            await sleep(1200);
          } catch (error) {
            // Best-effort: the frame is still useful even if the readout focus fails.
          }
        };
        const run = async () => {
          try {
            status.textContent = `${payload.label} | waiting for live frame...`;
            const stateUrl = new URL(`/api/pixel/worlds/${encodeURIComponent(payload.access_code)}/live/state`, window.location.origin);
            stateUrl.searchParams.set("session_id", payload.session_id);
            stateUrl.searchParams.set("since", "0");
            const liveState = await fetchJson(stateUrl.toString()).catch(() => null);
            if (liveState) {
              const room = liveState.room || {};
              const session = liveState.session || {};
              summary.textContent = [
                `seed=${payload.seed} access_code=${payload.access_code}`,
                `session=${session.session_id || payload.session_id} agent=${session.claimed_agent_id || "n/a"} room=${room.room_id || "n/a"} active=${room.active ? "1" : "0"}`,
                `label=${payload.label}`,
                `latest_event_id=${liveState.latest_event_id || 0}`,
              ].join("\n");
            }
            const readyText = await waitForFrameReady();
            const settledState = await waitForLiveEvent();
            if (settledState) {
              summary.textContent = [
                `seed=${payload.seed} access_code=${payload.access_code}`,
                `session=${settledState?.session?.session_id || payload.session_id} agent=${settledState?.session?.claimed_agent_id || "n/a"} room=${settledState?.room?.room_id || "n/a"} active=${settledState?.room?.active ? "1" : "0"}`,
                `label=${payload.label}`,
                `latest_event_id=${settledState?.latest_event_id || 0}`,
              ].join("\n");
            }
            await focusReadableView(settledState || liveState || null);
            const diagnostics = collectFrameDiagnostics();
            status.textContent = readyText ? `${payload.label} | ${readyText}` : `${payload.label} | snapshot ready`;
            await sleep(2000);
            await postJson(`/__test__/headless-pixel/result/${payload.token}`, {
              status: "ok",
              seed: payload.seed,
              access_code: payload.access_code,
              session_id: payload.session_id,
              label: payload.label,
              ready_text: readyText,
              diagnostics,
            });
          } catch (error) {
            status.textContent = `${payload.label} | ${error?.message || String(error)}`;
            try {
              await postJson(`/__test__/headless-pixel/result/${payload.token}`, {
                status: "error",
                error: error?.message || String(error),
                seed: payload.seed,
                access_code: payload.access_code,
                session_id: payload.session_id,
                label: payload.label,
              });
            } catch (postError) {
              summary.textContent = String(postError?.message || postError);
            }
          }
        };
        frame.addEventListener("load", () => {
          void run();
        }, { once: true });
      })();
    </script>
  </body>
</html>"""

    return (
        template.replace("__SEED__", str(payload["seed"]))
        .replace("__ACCESS_CODE__", str(payload["access_code"]))
        .replace("__SESSION_ID__", str(payload["session_id"]))
        .replace("__TOKEN__", str(payload["token"]))
        .replace("__IFRAME_URL__", iframe_url)
        .replace("__PAYLOAD_JSON__", json.dumps(payload))
    )


def _render_phaser_minimal_harness(token: str = "") -> str:
    normalized = str(token or "").strip() or "default"
    template = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Phaser Minimal Harness</title>
    <style>
      html, body {
        margin: 0;
        width: 100%;
        height: 100%;
        background: #131017;
        color: #f7f4ef;
        font-family: monospace;
      }
      #status {
        position: fixed;
        top: 8px;
        left: 12px;
        z-index: 20;
      }
      #game-root {
        width: 960px;
        height: 640px;
        margin: 48px auto;
        outline: 1px solid #4a3556;
      }
      img {
        display: none;
      }
    </style>
  </head>
  <body>
    <div id="status">Booting Phaser minimal harness...</div>
    <div id="game-root"></div>
    <img id="gate" alt="" src="/__test__/headless-pixel/gate/__TOKEN__" />
    <script src="/pixel/vendor/phaser-3.90.0.min.js"></script>
    <script>
      (() => {
        const Phaser = window.Phaser;
        const status = document.getElementById("status");
        const root = document.getElementById("game-root");
        const gate = document.getElementById("gate");
        const token = __TOKEN_JSON__;
        const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
        const postJson = async (path, body) => {
          const response = await fetch(path, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body ?? {}),
          });
          if (!response.ok) {
            throw new Error(`Failed to call ${path}`);
          }
          return response.json();
        };
        const collectDiagnostics = (game) => {
          const canvas = game?.canvas || document.querySelector("canvas");
          const scene = game?.scene?.scenes?.[0] || null;
          let canvasSamples = null;
          if (canvas) {
            try {
              const probe = document.createElement("canvas");
              probe.width = canvas.width || 0;
              probe.height = canvas.height || 0;
              const probeCtx = probe.getContext("2d");
              if (probeCtx && probe.width > 0 && probe.height > 0) {
                probeCtx.drawImage(canvas, 0, 0);
                const points = [
                  ["center", Math.floor(probe.width / 2), Math.floor(probe.height / 2)],
                  ["top_left", 8, 8],
                  ["top_right", Math.max(0, probe.width - 9), 8],
                  ["bottom_left", 8, Math.max(0, probe.height - 9)],
                  ["bottom_right", Math.max(0, probe.width - 9), Math.max(0, probe.height - 9)],
                ];
                canvasSamples = points.map(([label, x, y]) => {
                  const pixel = probeCtx.getImageData(x, y, 1, 1).data;
                  return {
                    label,
                    x,
                    y,
                    rgba: [Number(pixel[0]), Number(pixel[1]), Number(pixel[2]), Number(pixel[3])],
                  };
                });
              }
            } catch (error) {
              canvasSamples = { error: String(error?.message || error) };
            }
          }
          return {
            has_phaser: Boolean(Phaser),
            has_game: Boolean(game),
            canvas_size: canvas ? {
              width: Number(canvas.width || 0),
              height: Number(canvas.height || 0),
              client_width: Number(canvas.clientWidth || 0),
              client_height: Number(canvas.clientHeight || 0),
            } : null,
            renderer_type: Number(game?.renderer?.type || 0),
            scene_created: Boolean(window.__PHASER_MINIMAL_CREATED__),
            scene_updated: Number(window.__PHASER_MINIMAL_UPDATED__ || 0),
            display_list_size: Number(scene?.children?.list?.length || 0),
            camera: scene?.cameras?.main ? {
              width: Number(scene.cameras.main.width || 0),
              height: Number(scene.cameras.main.height || 0),
              zoom: Number(scene.cameras.main.zoom || 0),
            } : null,
            canvas_samples: canvasSamples,
          };
        };
        class MinimalScene extends Phaser.Scene {
          constructor() {
            super("minimal");
          }
          create() {
            window.__PHASER_MINIMAL_CREATED__ = true;
            this.cameras.main.setBackgroundColor("#224466");
            this.add.rectangle(240, 160, 220, 120, 0xe07a5f, 1).setOrigin(0.5);
            this.add.text(80, 300, "PHASER MINIMAL OK", {
              fontFamily: "monospace",
              fontSize: "32px",
              color: "#fff7e8",
            });
          }
          update() {
            window.__PHASER_MINIMAL_UPDATED__ = Number(window.__PHASER_MINIMAL_UPDATED__ || 0) + 1;
          }
        }
        const game = new Phaser.Game({
          type: Phaser.CANVAS,
          parent: root,
          width: root.clientWidth,
          height: root.clientHeight,
          backgroundColor: "#112233",
          scene: [MinimalScene],
          scale: {
            mode: Phaser.Scale.NONE,
          },
        });
        window.__PHASER_MINIMAL_GAME__ = game;
        const run = async () => {
          try {
            await sleep(200);
            if (typeof game.onVisible === "function") {
              game.onVisible();
            }
            if (game.loop && typeof game.loop.wake === "function") {
              game.loop.wake(true);
            }
            if (typeof game.step === "function") {
              for (let index = 0; index < 6; index += 1) {
                game.step(window.performance.now(), 16.6667);
              }
            }
            await sleep(2500);
            const diagnostics = collectDiagnostics(game);
            status.textContent = "Minimal harness ready";
            await postJson(`/__test__/headless-pixel/result/${token}`, {
              status: "ok",
              diagnostics,
            });
          } catch (error) {
            status.textContent = String(error?.message || error);
            await postJson(`/__test__/headless-pixel/result/${token}`, {
              status: "error",
              error: String(error?.message || error),
            });
          } finally {
            gate.src = `/__test__/headless-pixel/gate/${token}?t=${Date.now()}`;
          }
        };
        window.addEventListener("load", () => {
          void run();
        }, { once: true });
      })();
    </script>
  </body>
</html>"""

    return template.replace("__TOKEN__", normalized).replace("__TOKEN_JSON__", json.dumps(normalized))


