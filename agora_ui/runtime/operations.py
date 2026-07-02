from __future__ import annotations

import importlib
import json
from collections import Counter
from pathlib import Path
from random import Random
from typing import Any

from ..boundary_schemas import FinalManifestSpec, RunConfigSpec, RuntimePolicyRegistrySpec, RuntimeSnapshotSpec, RuntimeStoreSummarySpec, StoryPayloadSpec, TimelineRecordSpec
from .engine import RuntimeExecutionContext


def _legacy():
    return importlib.import_module("agora_ui.run_interaction_simulation")


def _policy_registry(ctx: RuntimeExecutionContext) -> dict[str, dict[str, Any]]:
    payload = ctx.get("policy_registry", {})
    if isinstance(payload, dict):
        return payload
    return {}


def _policy_id(ctx: RuntimeExecutionContext, key: str, default: str) -> str:
    policies = _policy_registry(ctx)
    payload = policies.get(key, {})
    if not isinstance(payload, dict):
        return default
    return str(payload.get("policy_id", default)).strip() or default


def _human_config(ctx: RuntimeExecutionContext) -> dict[str, Any]:
    payload = ctx.config.get("human_interaction", {})
    return payload if isinstance(payload, dict) else {}


def _human_paths(ctx: RuntimeExecutionContext) -> dict[str, Path]:
    run_dir = ctx.require("run_dir")
    return {
        "presence": run_dir / "human_presence.json",
        "queue": run_dir / "human_queue.jsonl",
        "history": run_dir / "human_interactions.jsonl",
    }


def _load_json_or_default(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _replace_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows if isinstance(row, dict))
    path.write_text(content, encoding="utf-8")


def _upsert_human_agent(ctx: RuntimeExecutionContext, *, presence: dict[str, Any]) -> Any | None:
    human_cfg = _human_config(ctx)
    if not bool(human_cfg.get("enabled", False)):
        return None
    legacy = _legacy()
    state = ctx.require("state")
    human_agent_id = str(human_cfg.get("runtime_human_agent_id", "human_interactor")).strip() or "human_interactor"
    display_name = str(presence.get("display_name", human_cfg.get("display_name", "Human Interactor"))).strip() or "Human Interactor"
    room_id = str(presence.get("room_id", human_cfg.get("default_room_id", ""))).strip()
    if not room_id:
        rooms = ctx.config.get("space", {}).get("rooms", []) or []
        if rooms and isinstance(rooms[0], dict):
            room_id = str(rooms[0].get("room_id", "")).strip()
    room = legacy._room_by_id(ctx.config, room_id, default_index=0)
    coordinates = presence.get("coordinates", {})
    if not isinstance(coordinates, dict) or not {"x", "y", "z"}.issubset(coordinates):
        spawn = legacy._spawn_coordinate_for_room(room, 0)
        coordinates = spawn.model_dump()
    agent_by_id = {agent.agent_id: agent for agent in state.agents}
    human_agent = agent_by_id.get(human_agent_id)
    public_state = {
        "role_id": "human_interactor",
        "role_name": "Human Interactor",
        "main_character": True,
        "activity_directive": "Respond to live human inputs and engage visible nearby agents in real time.",
        "runtime_memory": {
            "current_focus": str(presence.get("current_focus", "awaiting human instruction")).strip(),
            "mainline_summary": str(presence.get("mainline_summary", "Human interactor is live in the world.")).strip(),
            "human_presence": dict(presence),
        },
    }
    if human_agent is None:
        human_agent = legacy.AgentRuntimeProfileSpec.model_validate(
            {
                "agent_id": human_agent_id,
                "display_name": display_name,
                "gender_presentation": str(presence.get("gender_presentation", "person")).strip(),
                "appearance_prompt": str(
                    presence.get(
                        "appearance_prompt",
                        "A contemporary human observer rendered for an isometric simulation interface.",
                    )
                ).strip(),
                "core_values": ["curiosity", "responsiveness", "direct agency"],
                "inventory": [],
                "coordinates": coordinates,
                "room_id": room_id,
                "status_effects": [],
                "public_state": public_state,
                "private_notes": "This agent is controlled by a live human interactor.",
            }
        )
        state.agents.append(human_agent)
    else:
        human_agent.display_name = display_name
        human_agent.room_id = room_id
        human_agent.coordinates = legacy.GridPosition.model_validate(coordinates)
        human_agent.public_state.update(public_state)
    return human_agent


def sync_human_interactor(ctx: RuntimeExecutionContext, node: dict[str, Any]) -> None:
    human_cfg = _human_config(ctx)
    if not bool(human_cfg.get("enabled", False)):
        ctx.set("current_human_events", [])
        return
    paths = _human_paths(ctx)
    presence = _load_json_or_default(paths["presence"], {})
    if not isinstance(presence, dict):
        presence = {}
    human_agent = _upsert_human_agent(ctx, presence=presence)
    queued = _load_jsonl(paths["queue"])
    active_events = [row for row in queued if not bool(row.get("consumed", False))]
    for row in active_events:
        row["consumed"] = True
        row["consumed_round"] = int(ctx.require("current_round_index"))
    if active_events:
        paths["history"].parent.mkdir(parents=True, exist_ok=True)
        with paths["history"].open("a", encoding="utf-8") as handle:
            for row in active_events:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        _replace_jsonl(paths["queue"], queued)
        if human_agent is not None:
            runtime_memory = human_agent.public_state.setdefault("runtime_memory", {})
            runtime_memory["current_focus"] = str(active_events[-1].get("action_text", "human instruction")).strip()[:180]
            runtime_memory["human_pending_events"] = active_events[-6:]
    ctx.set("current_human_events", active_events)
    ctx.publish(
        "human_sync",
        {
            "round_index": ctx.require("current_round_index"),
            "active_event_count": len(active_events),
            "human_present": human_agent is not None,
        },
    )


def initialize_runtime(ctx: RuntimeExecutionContext, node: dict[str, Any]) -> None:
    legacy = _legacy()
    args = ctx.args
    config = ctx.config
    resume_run_dir = legacy._resolve(args.resume_run_dir) if args.resume_run_dir else None

    vertex_client = legacy.VertexJsonClient(config)
    image_generation_enabled = legacy._images_enabled(config) and not bool(args.disable_image_generation)
    image_client = legacy.VertexSDKImageClient(config) if image_generation_enabled else None

    runtime = config.get("runtime", {})
    seed = int(args.seed if args.seed is not None else runtime.get("seed", 42))
    rounds = int(args.rounds if args.rounds is not None else runtime.get("rounds", 10))
    activation = float(args.activation if args.activation is not None else runtime.get("activation_probability", 0.15))
    max_videos_per_round = int(
        args.max_videos_per_round
        if args.max_videos_per_round is not None
        else config.get("longlive", {}).get("max_videos_per_round", 2)
    )
    max_images_per_round = int(
        args.max_images_per_round if args.max_images_per_round is not None else legacy._image_max_per_round(config)
    )

    resume_payload = None
    resume_completed_round = 0
    resume_start_round = 1
    if resume_run_dir is not None:
        resume_payload = legacy._load_resume_state(resume_run_dir)
        resume_completed_round = int(resume_payload.get("completed_round", 0))
        resume_start_round = resume_completed_round + 1
        print(
            f"[RESUME] source={resume_run_dir} completed_round={resume_completed_round} target_rounds={rounds}",
            flush=True,
        )

    run_id = str(getattr(args, "run_id", "") or "").strip() or legacy._now_run_id()
    output_root = legacy._resolve(args.output_dir) if args.output_dir else legacy._resolve(
        legacy._output_config(config).get("default_output_dir", f"output/{legacy._run_name(config)}")
    )
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    resume_in_place = resume_run_dir is not None and resume_run_dir.resolve() == run_dir.resolve()

    default_scenario_dir = legacy._resolve(legacy._runner_config(config).get("scenario_dir", str(ctx.config_path.parent)))
    if args.scenario_dir:
        scenario_dir = legacy._resolve(args.scenario_dir)
    elif resume_in_place and (run_dir / "run_inputs" / "scenario").is_dir():
        scenario_dir = run_dir / "run_inputs" / "scenario"
    else:
        scenario_dir = default_scenario_dir

    ctx.set("vertex_client", vertex_client)
    ctx.set("image_client", image_client)
    ctx.set("image_generation_enabled", image_generation_enabled)
    ctx.set("seed", seed)
    ctx.set("rounds", rounds)
    ctx.set("activation_probability", activation)
    ctx.set("max_videos_per_round", max_videos_per_round)
    ctx.set("max_images_per_round", max_images_per_round)
    ctx.set("resume_run_dir", resume_run_dir)
    ctx.set("resume_payload", resume_payload)
    ctx.set("resume_completed_round", resume_completed_round)
    ctx.set("resume_start_round", resume_start_round)
    ctx.set("run_id", run_id)
    ctx.set("run_dir", run_dir)
    ctx.set("resume_in_place", resume_in_place)
    ctx.set("scenario_dir", scenario_dir)
    ctx.set("profile_cache_dir", run_dir / "agent_profile_api_cache")
    ctx.set("live_agents_dir", scenario_dir / "Agents")
    ctx.set(
        "reuse_profile_cache_dir",
        legacy._resolve(args.reuse_agent_profile_cache) if args.reuse_agent_profile_cache else None,
    )
    ctx.set("rng", Random(seed))
    ctx.set("round_indices", list(range(resume_start_round, rounds + 1)))
    ctx.set("timeline_path", run_dir / "timeline.jsonl")
    ctx.set("video_jobs_path", run_dir / "video_prompt_jobs.jsonl")
    ctx.set("image_jobs_path", run_dir / "image_jobs.jsonl")
    ctx.set("policy_registry", RuntimePolicyRegistrySpec.model_validate({"policies": dict(ctx.plan.get("policies", {}))}).model_dump()["policies"])
    ctx.publish(
        "runtime_initialized",
        {
            "run_id": run_id,
            "scenario_dir": str(scenario_dir),
            "resume_start_round": resume_start_round,
            "rounds": rounds,
        },
    )


def materialize_or_resume_state(ctx: RuntimeExecutionContext, node: dict[str, Any]) -> None:
    legacy = _legacy()
    args = ctx.args
    config = ctx.config
    run_dir = ctx.require("run_dir")
    scenario_dir = ctx.require("scenario_dir")
    resume_payload = ctx.get("resume_payload")
    resume_in_place = bool(ctx.get("resume_in_place"))
    vertex_client = ctx.require("vertex_client")
    reuse_profile_cache_dir = ctx.get("reuse_profile_cache_dir")
    profile_cache_dir = ctx.require("profile_cache_dir")
    live_agents_dir = ctx.require("live_agents_dir")

    if resume_in_place:
        agent_profile_source = "resume_in_place"
        files = legacy._scenario_file_paths(scenario_dir)
    else:
        base_agent_payloads = legacy._build_agent_payloads(config)
        if reuse_profile_cache_dir is not None:
            agent_payloads = legacy._reuse_agent_profile_cache(reuse_profile_cache_dir, base_agent_payloads)
            agent_profile_source = "reused_agent_profile_cache"
            legacy.dump_json(
                run_dir / "profile_generation_run.json",
                {
                    "run_id": ctx.require("run_id"),
                    "created_at": legacy._now_iso(),
                    "source": agent_profile_source,
                    "agent_count": len(agent_payloads),
                    "live_agents_dir": str(live_agents_dir),
                    "reused_profile_cache_dir": str(reuse_profile_cache_dir),
                    "vertex_api": vertex_client.safe_config() if vertex_client is not None else None,
                },
            )
        else:
            legacy.dump_json(
                run_dir / "profile_generation_run.json",
                {
                    "run_id": ctx.require("run_id"),
                    "created_at": legacy._now_iso(),
                    "source": "vertex_api",
                    "agent_count": len(base_agent_payloads),
                    "live_agents_dir": str(live_agents_dir),
                    "profile_cache_dir": str(profile_cache_dir),
                    "vertex_api": vertex_client.safe_config(),
                },
            )
            agent_payloads = legacy._vertex_agent_profile_payloads(
                vertex_client,
                config,
                base_agent_payloads,
                profile_cache_dir=profile_cache_dir,
                live_agents_dir=live_agents_dir,
            )
            agent_payloads = legacy._vertex_initial_inventory_payloads(
                vertex_client,
                config,
                agent_payloads,
                inventory_cache_dir=run_dir / "initial_inventory_api_cache",
                live_agents_dir=live_agents_dir,
            )
            agent_profile_source = "vertex_api"
        files = legacy.materialize_scenario(config, scenario_dir, agent_payloads=agent_payloads)

    run_config_payload = RunConfigSpec.model_validate({
        "run_id": ctx.require("run_id"),
        "created_at": legacy._now_iso(),
        "config_path": str(ctx.config_path),
        "scenario_dir": str(scenario_dir),
        "scenario_files": {key: str(value) for key, value in files.items()},
        "agent_profile_cache_dir": str(profile_cache_dir) if vertex_client is not None and reuse_profile_cache_dir is None else "",
        "reused_agent_profile_cache": str(reuse_profile_cache_dir) if reuse_profile_cache_dir is not None else "",
        "rounds": ctx.require("rounds"),
        "activation_probability": ctx.require("activation_probability"),
        "seed": ctx.require("seed"),
        "agent_profile_source": agent_profile_source,
        "disable_longlive": bool(args.disable_longlive),
        "disable_image_generation": bool(args.disable_image_generation),
        "max_images_per_round": ctx.require("max_images_per_round"),
        "image_generation": legacy._image_generation_config(config),
        "inventory_generation": legacy._inventory_generation_config(config),
        "extra_world_functions": legacy._extra_world_functions_config(config),
        "always_activate_agent_ids": legacy._main_character_ids(config),
        "force_cinematic_agent_ids": legacy._force_cinematic_agent_ids(config),
        "story_filename": legacy._story_filename(config),
        "run_name": legacy._run_name(config),
        "vertex_api": vertex_client.safe_config() if vertex_client is not None else None,
        "vertex_image_sdk": ctx.get("image_client").safe_config() if ctx.get("image_client") is not None else None,
        "resume": {
            "source_run_dir": str(ctx.get("resume_run_dir")) if ctx.get("resume_run_dir") is not None else "",
            "completed_round": ctx.get("resume_completed_round", 0),
            "start_round": ctx.get("resume_start_round", 1),
            "in_place": bool(ctx.get("resume_in_place")),
        },
        "compiled_orchestration_path": str(run_dir / "compiled_orchestration.json"),
    }).model_dump()
    legacy.dump_json(
        run_dir / "run_config.json",
        run_config_payload,
    )

    if resume_payload is not None and resume_payload.get("state") is not None:
        state = resume_payload["state"]
        world_rules = resume_payload["world_rules"]
    else:
        state = legacy._load_agent_state(scenario_dir, config)
        world_rules = legacy._load_world_rules(scenario_dir)
    legacy._rebuild_runtime_memories_from_history(
        state,
        config=config,
        stories=list(resume_payload.get("stories", [])) if resume_payload else [],
        image_jobs=list(resume_payload.get("image_jobs", [])) if resume_payload else [],
        extra_world_events=list(resume_payload.get("extra_world_events", [])) if resume_payload else [],
        completed_round=ctx.get("resume_completed_round", 0) if resume_payload else 0,
    )

    ctx.set("state", state)
    ctx.set("world_rules", world_rules)
    ctx.set("control", legacy._build_control(config))
    ctx.set("longlive", legacy.LongLiveTwoPromptGenerator(config, run_dir))
    ctx.set("force_cinematic_agent_ids", set(legacy._force_cinematic_agent_ids(config)))
    ctx.set(
        "force_cinematic_only",
        bool(config.get("longlive", {}).get("force_cinematic_only_for_forced_agents", False)),
    )
    ctx.publish(
        "state_ready",
        {
            "agent_count": len(state.agents),
            "resume_payload": bool(resume_payload),
            "agent_profile_source": agent_profile_source,
        },
    )


def initialize_round_accumulators(ctx: RuntimeExecutionContext, node: dict[str, Any]) -> None:
    legacy = _legacy()
    resume_payload = ctx.get("resume_payload")
    all_stories = list(resume_payload.get("stories", [])) if resume_payload else []
    all_video_jobs = list(resume_payload.get("video_jobs", [])) if resume_payload else []
    all_image_jobs = list(resume_payload.get("image_jobs", [])) if resume_payload else []
    all_extra_world_events = list(resume_payload.get("extra_world_events", [])) if resume_payload else []
    round_summaries = list(resume_payload.get("round_summaries", [])) if resume_payload else []
    route_counts = Counter(resume_payload.get("route_counts", Counter())) if resume_payload else Counter()
    longlive_counts = Counter(resume_payload.get("longlive_counts", Counter())) if resume_payload else Counter()
    image_counts = Counter(resume_payload.get("image_counts", Counter())) if resume_payload else Counter()

    ctx.set("all_stories", all_stories)
    ctx.set("all_video_jobs", all_video_jobs)
    ctx.set("all_image_jobs", all_image_jobs)
    ctx.set("all_extra_world_events", all_extra_world_events)
    ctx.set("round_summaries", round_summaries)
    ctx.set("route_counts", route_counts)
    ctx.set("longlive_counts", longlive_counts)
    ctx.set("image_counts", image_counts)

    if resume_payload is not None:
        run_dir = ctx.require("run_dir")
        legacy.dump_json(
            run_dir / "resume_manifest.json",
            {
                "source_run_dir": str(ctx.get("resume_run_dir")),
                "completed_round": ctx.get("resume_completed_round", 0),
                "start_round": ctx.get("resume_start_round", 1),
                "in_place": bool(ctx.get("resume_in_place")),
                "inherited_story_count": len(all_stories),
                "inherited_video_job_count": len(all_video_jobs),
                "inherited_image_job_count": len(all_image_jobs),
                "inherited_extra_world_event_count": len(all_extra_world_events),
            },
        )
        if not bool(ctx.get("resume_in_place")):
            for record in resume_payload.get("timeline_records", []):
                legacy._append_jsonl(ctx.require("timeline_path"), record)
            for job in all_video_jobs:
                legacy._append_jsonl(ctx.require("video_jobs_path"), job)
            for job in all_image_jobs:
                legacy._append_jsonl(ctx.require("image_jobs_path"), job)


def write_compiled_runtime_plan(ctx: RuntimeExecutionContext, node: dict[str, Any]) -> None:
    legacy = _legacy()
    legacy.dump_json(ctx.require("run_dir") / "compiled_orchestration.json", ctx.plan)


def prepare_round(ctx: RuntimeExecutionContext, node: dict[str, Any]) -> None:
    round_index = int(ctx.require("round_index"))
    ctx.set("current_round_index", round_index)
    ctx.set("round_intents", [])
    ctx.set("round_stories", [])
    ctx.set("round_video_jobs", [])
    ctx.set("round_image_jobs", [])
    ctx.set("round_extra_world_events", [])
    ctx.set("videos_used", 0)
    ctx.set("images_used", 0)
    ctx.set("round_serial", 0)
    ctx.publish("round_start", {"round_index": round_index})


def run_extra_world_functions(ctx: RuntimeExecutionContext, node: dict[str, Any]) -> None:
    legacy = _legacy()
    events = legacy._run_extra_world_functions(
        client=ctx.require("vertex_client"),
        config=ctx.config,
        state=ctx.require("state"),
        round_index=ctx.require("current_round_index"),
        run_dir=ctx.require("run_dir"),
        rng=ctx.require("rng"),
    )
    ctx.set("round_extra_world_events", events)


def activate_agents(ctx: RuntimeExecutionContext, node: dict[str, Any]) -> None:
    policy_id = _policy_id(ctx, "activation_policy", "bernoulli_plus_always_active")
    if policy_id not in {"bernoulli_plus_always_active", "human_visible_decay_activation"}:
        raise NotImplementedError(f"unsupported activation policy: {policy_id}")
    legacy = _legacy()
    rng = ctx.require("rng")
    state = ctx.require("state")
    activation = float(ctx.require("activation_probability"))
    human_policy = ctx.config.get("human_interaction", {}) if isinstance(ctx.config.get("human_interaction", {}), dict) else {}
    human_agent_id = str(human_policy.get("runtime_human_agent_id", "human_interactor")).strip()
    human_agent = next((agent for agent in state.agents if agent.agent_id == human_agent_id), None)
    visible_radius = max(0, int(human_policy.get("visible_radius_steps", 0) or 0))
    non_visible_decay = float(human_policy.get("non_visible_activation_decay", 0.15) or 0.15)
    min_non_visible = float(human_policy.get("non_visible_min_activation", 0.05) or 0.05)
    activated = []
    for agent in state.agents:
        effective_activation = activation
        if policy_id == "human_visible_decay_activation" and human_agent is not None and agent.agent_id != human_agent.agent_id:
            distance = legacy._walkable_distance_config(agent.coordinates, human_agent.coordinates, ctx.config)
            same_room = bool(agent.room_id and human_agent.room_id and agent.room_id == human_agent.room_id)
            if same_room or (distance is not None and distance <= visible_radius):
                effective_activation = 1.0
            else:
                distance_penalty = non_visible_decay * max(1, distance if distance is not None else 2)
                effective_activation = max(min_non_visible, activation - distance_penalty)
        if rng.random() < effective_activation:
            activated.append(agent)
    activated_ids = {agent.agent_id for agent in activated}
    agents_by_id = legacy._agent_map(state)
    for agent_id in legacy._main_character_ids(ctx.config):
        agent = agents_by_id.get(agent_id)
        if agent is not None and agent.agent_id not in activated_ids:
            activated.append(agent)
            activated_ids.add(agent.agent_id)
    ctx.set("activated_agents", activated)
    ctx.publish(
        "activation",
        {
            "round_index": ctx.require("current_round_index"),
            "activated_agent_count": len(activated),
        },
    )


def select_target(ctx: RuntimeExecutionContext, node: dict[str, Any]) -> None:
    policy_id = _policy_id(ctx, "target_selection_policy", "weighted_target_selection")
    if policy_id not in {"weighted_target_selection", "human_priority_target_selection"}:
        raise NotImplementedError(f"unsupported target selection policy: {policy_id}")
    legacy = _legacy()
    actor = ctx.require("actor")
    prefer_same_room_only = actor.agent_id in set(ctx.get("force_cinematic_agent_ids", set()))
    human_cfg = _human_config(ctx)
    current_human_events = ctx.get("current_human_events", [])
    if (
        policy_id == "human_priority_target_selection"
        and bool(human_cfg.get("enabled", False))
        and actor.agent_id == str(human_cfg.get("runtime_human_agent_id", "human_interactor")).strip()
        and current_human_events
    ):
        explicit_target_id = str(current_human_events[-1].get("target_agent_id", "")).strip()
        target_by_id = {candidate.agent_id: candidate for candidate in legacy._legal_targets(actor, ctx.require("state"), ctx.config)}
        if explicit_target_id and explicit_target_id in target_by_id:
            target = target_by_id[explicit_target_id]
        else:
            target = legacy._pick_target(
                ctx.require("rng"),
                actor,
                ctx.require("state"),
                ctx.config,
                round_index=ctx.require("current_round_index"),
                prefer_same_room_only=prefer_same_room_only,
            )
    else:
        target = legacy._pick_target(
            ctx.require("rng"),
            actor,
            ctx.require("state"),
            ctx.config,
            round_index=ctx.require("current_round_index"),
            prefer_same_room_only=prefer_same_room_only,
        )
    ctx.set("current_actor_skipped", target is None)
    ctx.set("current_target", target)
    if target is None:
        ctx.publish(
            "actor_skipped",
            {
                "round_index": ctx.require("current_round_index"),
                "actor_id": actor.agent_id,
                "reason": "no_legal_target",
            },
        )


def prepare_actor_request(ctx: RuntimeExecutionContext, node: dict[str, Any]) -> None:
    if ctx.get("current_actor_skipped"):
        return
    actor = ctx.require("actor")
    target = ctx.require("current_target")
    round_index = ctx.require("current_round_index")
    serial = int(ctx.require("round_serial")) + 1
    ctx.set("round_serial", serial)
    force_cinematic_agent_ids = ctx.require("force_cinematic_agent_ids")
    forced_actor_cinematic = actor.agent_id in force_cinematic_agent_ids
    force_cinematic = bool(forced_actor_cinematic)
    longlive_enabled = bool(ctx.config.get("longlive", {}).get("enabled", True)) and not bool(ctx.args.disable_longlive)
    actor_longlive_enabled = longlive_enabled and (forced_actor_cinematic or not bool(ctx.require("force_cinematic_only")))
    quota_left = max(0, int(ctx.require("max_videos_per_round")) - int(ctx.require("videos_used"))) if actor_longlive_enabled else 0
    image_quota_left = max(0, int(ctx.require("max_images_per_round")) - int(ctx.require("images_used"))) if bool(ctx.require("image_generation_enabled")) else 0
    ctx.set("current_serial", serial)
    ctx.set("current_force_cinematic", force_cinematic)
    ctx.set("current_longlive_enabled", longlive_enabled)
    ctx.set("current_quota_left", quota_left)
    ctx.set("current_image_quota_left", image_quota_left)
    print(f"[ROUTE_API] round={round_index} serial={serial} actor={actor.agent_id} target={target.agent_id}", flush=True)


def request_route(ctx: RuntimeExecutionContext, node: dict[str, Any]) -> None:
    policy_id = _policy_id(ctx, "route_request_policy", "vertex_json_route_request")
    if policy_id != "vertex_json_route_request":
        raise NotImplementedError(f"unsupported route request policy: {policy_id}")
    legacy = _legacy()
    actor = ctx.require("actor")
    target = ctx.require("current_target")
    request = legacy._vertex_action_request(
        ctx.require("vertex_client"),
        state=ctx.require("state"),
        actor=actor,
        target=target,
        config=ctx.config,
        round_index=ctx.require("current_round_index"),
        video_quota_left=ctx.require("current_quota_left"),
        image_quota_left=ctx.require("current_image_quota_left"),
        force_cinematic=bool(ctx.require("current_force_cinematic")),
    )
    if bool(ctx.require("current_force_cinematic")) and int(ctx.require("current_quota_left")) > 0:
        selected_route = legacy._route_lookup(ctx.config).get(str(request.get("route_id", "")), {})
        if str(selected_route.get("kind", request.get("kind", ""))) != "cinematic":
            raise RuntimeError(f"forced cinematic actor {actor.agent_id} did not receive a cinematic route")
    ctx.set("current_request", request)


def apply_route_fallbacks(ctx: RuntimeExecutionContext, node: dict[str, Any]) -> None:
    policy_id = _policy_id(ctx, "route_quota_policy", "quota_fallback")
    if policy_id != "quota_fallback":
        raise NotImplementedError(f"unsupported route quota policy: {policy_id}")
    legacy = _legacy()
    actor = ctx.require("actor")
    target = ctx.require("current_target")
    request = dict(ctx.require("current_request"))
    round_index = ctx.require("current_round_index")
    if str(request.get("kind", "")) == "cinematic" and int(ctx.require("current_quota_left")) <= 0:
        print(f"[ROUTE_FALLBACK] round={round_index} actor={actor.agent_id} reason=cinematic_quota_exhausted", flush=True)
        request = legacy._fallback_request_for_quota(
            request,
            config=ctx.config,
            exhausted_kind="cinematic",
            actor=actor,
            target=target,
        )
    if str(request.get("kind", "")) == "image" and int(ctx.require("current_image_quota_left")) <= 0:
        print(f"[ROUTE_FALLBACK] round={round_index} actor={actor.agent_id} reason=image_quota_exhausted", flush=True)
        request = legacy._fallback_request_for_quota(
            request,
            config=ctx.config,
            exhausted_kind="image",
            actor=actor,
            target=target,
        )
    ctx.set("current_request", request)


def build_actor_outputs(ctx: RuntimeExecutionContext, node: dict[str, Any]) -> None:
    policy_id = _policy_id(ctx, "intent_builder_policy", "legacy_intent_builder")
    if policy_id != "legacy_intent_builder":
        raise NotImplementedError(f"unsupported intent builder policy: {policy_id}")
    legacy = _legacy()
    actor = ctx.require("actor")
    built_intents, video_jobs, image_jobs, story = legacy._build_intents_for_request(
        rng=ctx.require("rng"),
        round_index=ctx.require("current_round_index"),
        serial=ctx.require("current_serial"),
        state=ctx.require("state"),
        actor=actor,
        target=ctx.require("current_target"),
        request=ctx.require("current_request"),
        config=ctx.config,
        longlive=ctx.require("longlive"),
        run_dir=ctx.require("run_dir"),
        seed=ctx.require("seed"),
        disable_longlive=not bool(ctx.require("current_longlive_enabled")),
        disable_images=not bool(ctx.require("image_generation_enabled")),
        video_prompt_client=ctx.require("vertex_client"),
        image_prompt_client=ctx.require("vertex_client"),
        image_client=ctx.get("image_client"),
    )
    human_cfg = _human_config(ctx)
    current_human_events = ctx.get("current_human_events", [])
    if (
        bool(human_cfg.get("enabled", False))
        and actor.agent_id == str(human_cfg.get("runtime_human_agent_id", "human_interactor")).strip()
        and current_human_events
        and built_intents
    ):
        human_event = current_human_events[-1]
        action_text = str(human_event.get("action_text", "")).strip()
        if action_text:
            built_intents[0]["intent_text"] = action_text
            built_intents[0].setdefault("metadata", {})["human_interactor"] = True
            built_intents[0]["metadata"]["human_event"] = dict(human_event)
            story["selection_reason"] = f"human_interactor_event: {action_text[:180]}"
            story["human_event"] = dict(human_event)
    ctx.set("current_built_intents", built_intents)
    ctx.set("current_video_jobs", video_jobs)
    ctx.set("current_image_jobs", image_jobs)
    ctx.set("current_story", story)


def record_actor_outputs(ctx: RuntimeExecutionContext, node: dict[str, Any]) -> None:
    legacy = _legacy()
    round_intents = ctx.require("round_intents")
    round_video_jobs = ctx.require("round_video_jobs")
    round_image_jobs = ctx.require("round_image_jobs")
    round_stories = ctx.require("round_stories")
    all_video_jobs = ctx.require("all_video_jobs")
    all_image_jobs = ctx.require("all_image_jobs")
    route_counts = ctx.require("route_counts")
    longlive_counts = ctx.require("longlive_counts")
    image_counts = ctx.require("image_counts")

    built_intents = ctx.get("current_built_intents", [])
    video_jobs = ctx.get("current_video_jobs", [])
    image_jobs = ctx.get("current_image_jobs", [])
    story = ctx.get("current_story", {})

    round_intents.extend(built_intents)
    round_video_jobs.extend(video_jobs)
    round_image_jobs.extend(image_jobs)
    all_video_jobs.extend(video_jobs)
    all_image_jobs.extend(image_jobs)
    round_stories.append(story)
    route_counts[str(story.get("route_id", story.get("kind", "")))] += 1
    for job in video_jobs:
        ctx.set("videos_used", int(ctx.require("videos_used")) + 1)
        longlive_counts[str(job.get("status", ""))] += 1
        legacy._append_jsonl(ctx.require("video_jobs_path"), job)
    for job in image_jobs:
        ctx.set("images_used", int(ctx.require("images_used")) + 1)
        image_counts[str(job.get("status", ""))] += 1
        legacy._append_jsonl(ctx.require("image_jobs_path"), job)


def adjudicate_round(ctx: RuntimeExecutionContext, node: dict[str, Any]) -> None:
    policy_id = _policy_id(ctx, "adjudication_policy", "local_universal_adjudicator")
    if policy_id != "local_universal_adjudicator":
        raise NotImplementedError(f"unsupported adjudication policy: {policy_id}")
    legacy = _legacy()
    round_index = ctx.require("current_round_index")
    round_intents = ctx.require("round_intents")
    intent_batch = legacy.AgentIntentBatchSpec.model_validate(
        {"timestep_index": round_index, "intents": round_intents}
    )
    batch_dir = ctx.require("run_dir") / "intent_batches"
    legacy.dump_json(batch_dir / f"{round_index:03d}_round_{round_index:03d}.json", intent_batch.model_dump())

    output, state, world_rules = legacy.adjudicator._local_adjudicate(
        control=ctx.require("control").model_copy(update={"timestep_index": round_index}),
        world_rules=ctx.require("world_rules"),
        agent_state=ctx.require("state"),
        intent_batch=intent_batch,
    )
    legacy._update_agent_runtime_memory(
        state,
        config=ctx.config,
        round_index=round_index,
        round_stories=ctx.require("round_stories"),
        round_extra_world_events=ctx.require("round_extra_world_events"),
        round_image_jobs=ctx.require("round_image_jobs"),
    )
    ctx.set("round_output", output)
    ctx.set("state", state)
    ctx.set("world_rules", world_rules)
    print(
        f"[ROUND_DONE] round={round_index} intents={len(round_intents)} videos={len(ctx.require('round_video_jobs'))}",
        flush=True,
    )
    legacy.dump_json(ctx.require("run_dir") / f"timestep_{round_index:03d}" / "adjudicator_output.json", output)
    state_payload = state.model_dump()
    ctx.set("round_state_payload", state_payload)
    legacy.dump_json(ctx.require("run_dir") / f"timestep_{round_index:03d}" / "updated_agent_profiles.json", state_payload)
    legacy.dump_json(ctx.require("run_dir") / f"timestep_{round_index:03d}" / "updated_world_rules.json", world_rules.model_dump())
    legacy._publish_frontend_state(
        run_id=ctx.require("run_id"),
        run_dir=ctx.require("run_dir"),
        config=ctx.config,
        scenario_dir=ctx.require("scenario_dir"),
        state_payload=state_payload,
        status="running",
        round_index=round_index,
    )


def record_round_outputs(ctx: RuntimeExecutionContext, node: dict[str, Any]) -> None:
    legacy = _legacy()
    output = ctx.require("round_output")
    action_results = output.get("State_Mutations", {}).get("action_results", [])
    success_count = sum(1 for item in action_results if item.get("status") == "success")
    summary = {
        "round_index": ctx.require("current_round_index"),
        "activated_agent_count": len(ctx.require("activated_agents")),
        "intent_count": len(ctx.require("round_intents")),
        "story_event_count": len(ctx.require("round_stories")),
        "video_job_count": len(ctx.require("round_video_jobs")),
        "image_job_count": len(ctx.require("round_image_jobs")),
        "action_success_count": success_count,
        "action_result_count": len(action_results),
        "routes": Counter(str(item.get("route_id", item.get("kind", ""))) for item in ctx.require("round_stories")),
    }
    summary["routes"] = dict(summary["routes"])
    ctx.require("round_summaries").append(summary)
    ctx.require("all_stories").extend(ctx.require("round_stories"))
    ctx.require("all_extra_world_events").extend(ctx.require("round_extra_world_events"))
    timeline_record = {
        "round_index": ctx.require("current_round_index"),
        "summary": summary,
        "stories": ctx.require("round_stories"),
        "video_jobs": ctx.require("round_video_jobs"),
        "image_jobs": ctx.require("round_image_jobs"),
        "extra_world_events": ctx.require("round_extra_world_events"),
        "action_results": action_results,
    }
    timeline_record = TimelineRecordSpec.model_validate(timeline_record).model_dump()
    legacy._append_jsonl(ctx.require("timeline_path"), timeline_record)
    ctx.publish(
        "round_complete",
        {
            "round_index": ctx.require("current_round_index"),
            "intent_count": len(ctx.require("round_intents")),
            "story_event_count": len(ctx.require("round_stories")),
        },
    )


def write_final_outputs(ctx: RuntimeExecutionContext, node: dict[str, Any]) -> None:
    policy_id = _policy_id(ctx, "finalization_policy", "legacy_manifest_writer")
    if policy_id != "legacy_manifest_writer":
        raise NotImplementedError(f"unsupported finalization policy: {policy_id}")
    legacy = _legacy()
    run_dir = ctx.require("run_dir")
    final_state_path = run_dir / "final_agent_profiles.json"
    final_rules_path = run_dir / "final_world_rules.json"
    final_state_payload = ctx.require("state").model_dump()
    legacy.dump_json(final_state_path, final_state_payload)
    legacy.dump_json(final_rules_path, ctx.require("world_rules").model_dump())
    state_by_id = legacy._agent_map(ctx.require("state"))
    legality = legacy._validate_target_legality(ctx.require("all_stories"), state_by_id, ctx.config)
    story_payload = {
        "run_id": ctx.require("run_id"),
        "scenario_meta": ctx.config.get("scenario_meta", {}),
        "resumed_from": {
            "run_dir": str(ctx.get("resume_run_dir")) if ctx.get("resume_run_dir") is not None else "",
            "completed_round": ctx.get("resume_completed_round", 0),
        },
        "round_summaries": ctx.require("round_summaries"),
        "stories": ctx.require("all_stories"),
        "route_counts": dict(ctx.require("route_counts")),
        "longlive_counts": dict(ctx.require("longlive_counts")),
        "image_counts": dict(ctx.require("image_counts")),
        "extra_world_events": ctx.require("all_extra_world_events"),
        "target_legality": legality,
        "orchestration": ctx.plan,
    }
    story_payload = StoryPayloadSpec.model_validate(story_payload).model_dump()
    story_path = run_dir / legacy._story_filename(ctx.config)
    legacy.dump_json(story_path, story_payload)
    api_story_summary_path = run_dir / "api_story_summary.json"
    vertex_client = ctx.get("vertex_client")
    if vertex_client is not None:
        print("[REPORT_API] generating story summary", flush=True)
        api_summary = legacy._vertex_story_summary(
            vertex_client,
            config=ctx.config,
            story_payload=story_payload,
            video_jobs=ctx.require("all_video_jobs"),
            image_jobs=ctx.require("all_image_jobs"),
        )
        legacy.dump_json(api_story_summary_path, api_summary)
    final_manifest = {
        "run_id": ctx.require("run_id"),
        "status": "ok",
        "scenario_dir": str(ctx.require("scenario_dir")),
        "rounds": ctx.require("rounds"),
        "resumed_from": {
            "run_dir": str(ctx.get("resume_run_dir")) if ctx.get("resume_run_dir") is not None else "",
            "completed_round": ctx.get("resume_completed_round", 0),
        },
        "activation_probability": ctx.require("activation_probability"),
        "agent_count": len(ctx.require("state").agents),
        "files": {
            "timeline": str(ctx.require("timeline_path")),
            "story": str(story_path),
            "api_story_summary": str(api_story_summary_path) if api_story_summary_path.is_file() else "",
            "video_prompt_jobs": str(ctx.require("video_jobs_path")),
            "image_jobs": str(ctx.require("image_jobs_path")),
            "final_agent_profiles": str(final_state_path),
            "final_world_rules": str(final_rules_path),
            "compiled_orchestration": str(run_dir / "compiled_orchestration.json"),
            "runtime_snapshot": str(run_dir / "runtime_snapshot.json"),
        },
        "route_counts": dict(ctx.require("route_counts")),
        "longlive_counts": dict(ctx.require("longlive_counts")),
        "image_counts": dict(ctx.require("image_counts")),
        "extra_world_event_count": len(ctx.require("all_extra_world_events")),
        "target_legality": legality,
        "orchestration_mode": str(ctx.plan.get("mode", "json_declared_runtime")),
    }
    final_manifest = FinalManifestSpec.model_validate(final_manifest).model_dump()
    legacy.dump_json(run_dir / "final_manifest.json", final_manifest)
    legacy._publish_frontend_state(
        run_id=ctx.require("run_id"),
        run_dir=run_dir,
        config=ctx.config,
        scenario_dir=ctx.require("scenario_dir"),
        state_payload=final_state_payload,
        status="ok",
        round_index=ctx.require("rounds"),
    )
    ctx.set("final_manifest", final_manifest)


def build_optional_report(ctx: RuntimeExecutionContext, node: dict[str, Any]) -> None:
    legacy = _legacy()
    if ctx.args.skip_report:
        return
    run_dir = ctx.require("run_dir")
    final_manifest = ctx.require("final_manifest")
    try:
        from agora_ui.build_interaction_report import build_report

        report_info = build_report(run_dir=run_dir, config=ctx.config)
        final_manifest["files"].update(report_info)
        final_manifest = FinalManifestSpec.model_validate(final_manifest).model_dump()
        legacy.dump_json(run_dir / "final_manifest.json", final_manifest)
    except Exception as exc:
        legacy.dump_json(run_dir / "report_failure.json", {"error": str(exc)})


def write_runtime_snapshot(ctx: RuntimeExecutionContext, node: dict[str, Any]) -> None:
    legacy = _legacy()
    snapshot = {
        "run_id": ctx.require("run_id"),
        "compiled_orchestration": ctx.plan,
        "component_state": ctx.component_state(),
        "event_bus": ctx.event_bus.get_state(),
        "store_summary": RuntimeStoreSummarySpec.model_validate({
            "rounds": ctx.require("rounds"),
            "resume_start_round": ctx.get("resume_start_round", 1),
            "route_counts": dict(ctx.require("route_counts")),
            "longlive_counts": dict(ctx.require("longlive_counts")),
            "image_counts": dict(ctx.require("image_counts")),
        }).model_dump(),
    }
    snapshot = RuntimeSnapshotSpec.model_validate(snapshot).model_dump()
    legacy.dump_json(ctx.require("run_dir") / "runtime_snapshot.json", snapshot)
    print(f"[DONE] run_dir={ctx.require('run_dir')}")


OPERATION_REGISTRY = {
    "initialize_runtime": initialize_runtime,
    "materialize_or_resume_state": materialize_or_resume_state,
    "initialize_round_accumulators": initialize_round_accumulators,
    "write_compiled_runtime_plan": write_compiled_runtime_plan,
    "prepare_round": prepare_round,
    "sync_human_interactor": sync_human_interactor,
    "run_extra_world_functions": run_extra_world_functions,
    "activate_agents": activate_agents,
    "select_target": select_target,
    "prepare_actor_request": prepare_actor_request,
    "request_route": request_route,
    "apply_route_fallbacks": apply_route_fallbacks,
    "build_actor_outputs": build_actor_outputs,
    "record_actor_outputs": record_actor_outputs,
    "adjudicate_round": adjudicate_round,
    "record_round_outputs": record_round_outputs,
    "write_final_outputs": write_final_outputs,
    "build_optional_report": build_optional_report,
    "write_runtime_snapshot": write_runtime_snapshot,
}
