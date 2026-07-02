# Frontend Memory For Live Pixel UI

This document records the current frontend contract for the live Pixel UI.

It is intentionally focused on runtime behavior, not generic design ideas.

## Core Frontend Rule

The frontend no longer treats live movement as a pure HTTP CRUD flow.

Current shape:

- REST boots the world and creates the session
- WebSocket carries high-frequency movement input and movement deltas
- REST `/live/state` remains as a slower completeness and fallback channel

This means the frontend now has two different responsibilities:

- immediate local visual response
- eventual convergence to backend authority

## Session Bootstrap

The current boot sequence is:

1. fetch available Pixel worlds from `/api/pixel/worlds`
2. fetch or infer the chosen package world record
3. create a live session through REST
4. read realtime metadata such as `ws_url` or `live_ws_url_template`
5. connect the WebSocket
6. keep the session alive with heartbeat and slower state refreshes

The initial world and package discovery still come from the DB-backed package APIs.

## Authoritative Versus Predicted State

The frontend now keeps two ideas separate:

- authoritative agent state
- predicted local controller state

Rules:

- the server remains authoritative
- the local controller agent may move immediately on input
- server `state_delta` messages reconcile the local agent
- remote agents are rendered from authoritative updates only

This split is what makes low-latency movement possible without giving up DB-backed truth.

## Realtime Movement Contract

Current movement path:

- local input generates a `client_action_id` and `input_seq`
- the frontend immediately updates the local sprite and animation
- the same input is sent over WebSocket
- the server tick loop processes buffered inputs
- the server broadcasts `state_delta`
- the frontend clears confirmed pending moves using `last_input_seq`
- if the server result differs, the local agent is reconciled

The frontend should never assume that prediction itself is the final truth.

## Remote Agent Rendering

Remote agents should not teleport on each delta.

Current rule:

- store the incoming authoritative target position
- move the sprite with short interpolation or tweening over roughly one tick

This keeps 20-player movement visually stable when deltas arrive every `50ms`.

## REST Fallback Rule

REST state fetch is still needed, but it is not the hot path anymore.

Use REST for:

- initial full snapshot
- inventory, room, route, and event completeness
- reconnect recovery
- slower consistency refresh

Do not use REST polling as the primary movement transport again.

## Controller And Target Semantics

The frontend must keep these roles distinct:

- controller agent
- target agent

Rules:

- in live mode, the claimed agent is the controller
- selected target agent is a separate concept
- trade, item use, and target-aware dialogue use the selected target
- controller identity should not be overwritten by target selection

This is now a hard UI contract, not a naming preference.

## Pending State

The frontend maintains explicit pending state for accepted-but-not-yet-settled live actions.

Important examples:

- pending moves
- pending speech
- pending trade requests
- pending task assignments

These are keyed by client-generated identifiers so that later server events can reconcile them cleanly.

## Current Layout Contract

The intended Pixel UI layout is:

- center-first map stage
- right-side utility rail
- target bubble only when a target agent is selected

The right rail currently groups:

- live speaking and mode controls
- agent selector
- trade near the upper interaction block
- inventory, pending actions, and dialogue below

The layout should keep the map dominant while still exposing live controls.

## Cache And Bundle Rule

The Pixel frontend bundle version must be bumped whenever the shipped frontend contract changes in a way that browsers or headless harnesses could cache incorrectly.

That includes:

- script imports
- DOM structure that the harness depends on
- WebSocket boot logic
- live control availability

## Guardrails

Keep these guardrails in place:

- backend package state remains authoritative
- do not move inventory or trade truth into the browser
- keep controller and target state separate
- keep WebSocket movement and REST snapshots complementary, not competing
- only relax REST polling frequency when WebSocket health is good

## Current Non-Goal

The frontend is not trying to become a full delta-merge ECS client.

The design goal is narrower:

- instant-feeling local movement
- smooth remote movement
- DB-backed authority
- low operational complexity
