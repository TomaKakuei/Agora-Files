
"""Cross-boundary output schemas for runtime, replay, and asset JSON."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .foundation_schemas import GridPosition, GridShape, RoomSpec


def _non_empty_text(value: Any, label: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{label} must be non-empty")
    return text


def _int_dict(value: dict[str, Any]) -> dict[str, int]:
    clean: dict[str, int] = {}
    for key, raw in dict(value).items():
        clean[str(key)] = int(raw)
    return clean


def _str_dict(value: dict[str, Any]) -> dict[str, str]:
    clean: dict[str, str] = {}
    for key, raw in dict(value).items():
        clean[str(key)] = str(raw)
    return clean


class RunResumeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_run_dir: str = ""
    completed_round: int = Field(default=0, ge=0)
    start_round: int = Field(default=1, ge=1)
    in_place: bool = False


class RuntimePolicySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: str
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)
    notes: str = ""

    @field_validator("policy_id")
    @classmethod
    def _validate_policy_id(cls, value: str) -> str:
        return _non_empty_text(value, "policy_id")


class RuntimePolicyRegistrySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policies: dict[str, RuntimePolicySpec] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_unique_policy_ids(self) -> "RuntimePolicyRegistrySpec":
        seen: set[str] = set()
        for name, policy in self.policies.items():
            if not str(name).strip():
                raise ValueError("policy registry keys must be non-empty")
            if policy.policy_id in seen:
                raise ValueError(f"duplicate policy_id: {policy.policy_id}")
            seen.add(policy.policy_id)
        return self


class RuntimeStoreSummarySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rounds: int = Field(ge=0)
    resume_start_round: int = Field(ge=1)
    route_counts: dict[str, int] = Field(default_factory=dict)
    longlive_counts: dict[str, int] = Field(default_factory=dict)
    image_counts: dict[str, int] = Field(default_factory=dict)

    @field_validator("route_counts", "longlive_counts", "image_counts")
    @classmethod
    def _validate_counts(cls, value: dict[str, Any]) -> dict[str, int]:
        return _int_dict(value)


class TimelineSummarySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    round_index: int = Field(ge=0)
    activated_agent_count: int = Field(ge=0)
    intent_count: int = Field(ge=0)
    story_event_count: int = Field(ge=0)
    video_job_count: int = Field(ge=0)
    image_job_count: int = Field(ge=0)
    action_success_count: int = Field(ge=0)
    action_result_count: int = Field(ge=0)
    routes: dict[str, int] = Field(default_factory=dict)

    @field_validator("routes")
    @classmethod
    def _validate_routes(cls, value: dict[str, Any]) -> dict[str, int]:
        return _int_dict(value)


class TimelineRecordSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    round_index: int = Field(ge=1)
    summary: TimelineSummarySpec
    stories: list[dict[str, Any]] = Field(default_factory=list)
    video_jobs: list[dict[str, Any]] = Field(default_factory=list)
    image_jobs: list[dict[str, Any]] = Field(default_factory=list)
    extra_world_events: list[dict[str, Any]] = Field(default_factory=list)
    action_results: list[dict[str, Any]] = Field(default_factory=list)


class StoryPayloadSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    scenario_meta: dict[str, Any] = Field(default_factory=dict)
    resumed_from: RunResumeSpec = Field(default_factory=RunResumeSpec)
    round_summaries: list[TimelineSummarySpec] = Field(default_factory=list)
    stories: list[dict[str, Any]] = Field(default_factory=list)
    route_counts: dict[str, int] = Field(default_factory=dict)
    longlive_counts: dict[str, int] = Field(default_factory=dict)
    image_counts: dict[str, int] = Field(default_factory=dict)
    extra_world_events: list[dict[str, Any]] = Field(default_factory=list)
    target_legality: dict[str, Any] = Field(default_factory=dict)
    orchestration: dict[str, Any] = Field(default_factory=dict)

    @field_validator("run_id")
    @classmethod
    def _validate_run_id(cls, value: str) -> str:
        return _non_empty_text(value, "run_id")

    @field_validator("route_counts", "longlive_counts", "image_counts")
    @classmethod
    def _validate_counts(cls, value: dict[str, Any]) -> dict[str, int]:
        return _int_dict(value)


class FinalManifestSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: str
    scenario_dir: str
    rounds: int = Field(ge=0)
    resumed_from: RunResumeSpec = Field(default_factory=RunResumeSpec)
    activation_probability: float = Field(ge=0.0)
    agent_count: int = Field(ge=0)
    files: dict[str, str] = Field(default_factory=dict)
    route_counts: dict[str, int] = Field(default_factory=dict)
    longlive_counts: dict[str, int] = Field(default_factory=dict)
    image_counts: dict[str, int] = Field(default_factory=dict)
    extra_world_event_count: int = Field(ge=0)
    target_legality: dict[str, Any] = Field(default_factory=dict)
    orchestration_mode: str = ""

    @field_validator("run_id", "status", "scenario_dir")
    @classmethod
    def _validate_required_strings(cls, value: str) -> str:
        return _non_empty_text(value, "value")

    @field_validator("files")
    @classmethod
    def _validate_files(cls, value: dict[str, Any]) -> dict[str, str]:
        return _str_dict(value)

    @field_validator("route_counts", "longlive_counts", "image_counts")
    @classmethod
    def _validate_counts(cls, value: dict[str, Any]) -> dict[str, int]:
        return _int_dict(value)


class RuntimeSnapshotSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    compiled_orchestration: dict[str, Any] = Field(default_factory=dict)
    component_state: dict[str, Any] = Field(default_factory=dict)
    event_bus: dict[str, Any] = Field(default_factory=dict)
    store_summary: RuntimeStoreSummarySpec = Field(default_factory=RuntimeStoreSummarySpec)

    @field_validator("run_id")
    @classmethod
    def _validate_run_id(cls, value: str) -> str:
        return _non_empty_text(value, "run_id")


class RunConfigSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    created_at: str
    config_path: str
    scenario_dir: str
    scenario_files: dict[str, str] = Field(default_factory=dict)
    agent_profile_cache_dir: str = ""
    reused_agent_profile_cache: str = ""
    rounds: int = Field(ge=0)
    activation_probability: float = Field(ge=0.0)
    seed: int
    agent_profile_source: str
    disable_longlive: bool = False
    disable_image_generation: bool = False
    max_images_per_round: int = Field(ge=0)
    image_generation: dict[str, Any] = Field(default_factory=dict)
    inventory_generation: dict[str, Any] = Field(default_factory=dict)
    extra_world_functions: dict[str, Any] = Field(default_factory=dict)
    always_activate_agent_ids: list[str] = Field(default_factory=list)
    force_cinematic_agent_ids: list[str] = Field(default_factory=list)
    story_filename: str
    run_name: str
    vertex_api: Optional[dict[str, Any]] = None
    vertex_image_sdk: Optional[dict[str, Any]] = None
    resume: RunResumeSpec = Field(default_factory=RunResumeSpec)
    compiled_orchestration_path: str

    @field_validator("run_id", "created_at", "config_path", "scenario_dir", "agent_profile_source", "story_filename", "run_name", "compiled_orchestration_path")
    @classmethod
    def _validate_required_strings(cls, value: str) -> str:
        return _non_empty_text(value, "value")

    @field_validator("scenario_files")
    @classmethod
    def _validate_scenario_files(cls, value: dict[str, Any]) -> dict[str, str]:
        return _str_dict(value)


class ReplayImageOptionsSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generate_character_portraits: bool = True
    item_image_mode: str = "off"


class ReplayWorldSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    world_id: str
    world_name: str
    description: str
    simulation_objective: str
    domain_label: str = ""
    image_options: ReplayImageOptionsSpec = Field(default_factory=ReplayImageOptionsSpec)

    @field_validator("world_id", "world_name", "description", "simulation_objective")
    @classmethod
    def _validate_required_strings(cls, value: str) -> str:
        return _non_empty_text(value, "value")


class ReplayRunSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    run_dir: str
    status: str
    created_at: str = ""
    rounds_target: int = Field(ge=0)
    rounds_completed: int = Field(ge=0)
    activation_probability: float = Field(ge=0.0)
    agent_count: int = Field(ge=0)
    route_counts: dict[str, int] = Field(default_factory=dict)
    longlive_counts: dict[str, int] = Field(default_factory=dict)
    image_counts: dict[str, int] = Field(default_factory=dict)

    @field_validator("run_id", "run_dir", "status")
    @classmethod
    def _validate_required_strings(cls, value: str) -> str:
        return _non_empty_text(value, "value")

    @field_validator("route_counts", "longlive_counts", "image_counts")
    @classmethod
    def _validate_counts(cls, value: dict[str, Any]) -> dict[str, int]:
        return _int_dict(value)


class ReplayMapSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grid_shape: GridShape = Field(default_factory=GridShape)
    map_visual: dict[str, Any] = Field(default_factory=dict)
    bounds: dict[str, int] = Field(default_factory=dict)
    capacity_per_coordinate: int = Field(default=1, ge=1)
    rooms: list[RoomSpec] = Field(default_factory=list)

    @field_validator("bounds")
    @classmethod
    def _validate_bounds(cls, value: dict[str, Any]) -> dict[str, int]:
        return _int_dict(value)


class ReplayAgentSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    agent_id: str
    display_name: str = ""
    room_id: str = ""
    coordinates: GridPosition = Field(default_factory=lambda: GridPosition(x=0, y=0, z=0))
    main_character: bool = False
    role_name: str = ""
    activity_directive: str = ""
    appearance_prompt: str = ""
    room_visual: dict[str, Any] = Field(default_factory=dict)
    agent_number: int = 0
    image_url: str = ""

    @field_validator("agent_id")
    @classmethod
    def _validate_agent_id(cls, value: str) -> str:
        return _non_empty_text(value, "agent_id")


class ReplayFrameSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    frame_index: int = Field(ge=0)
    round_index: int = Field(ge=0)
    label: str
    summary: TimelineSummarySpec
    rooms: list[dict[str, Any]] = Field(default_factory=list)
    agents: list[ReplayAgentSpec] = Field(default_factory=list)
    relationship_edges: list[dict[str, Any]] = Field(default_factory=list)
    social_groups: list[dict[str, Any]] = Field(default_factory=list)
    stories: list[dict[str, Any]] = Field(default_factory=list)
    longlive_jobs: list[dict[str, Any]] = Field(default_factory=list)
    image_jobs: list[dict[str, Any]] = Field(default_factory=list)
    extra_world_events: list[dict[str, Any]] = Field(default_factory=list)
    action_results: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("label")
    @classmethod
    def _validate_label(cls, value: str) -> str:
        return _non_empty_text(value, "label")


class ReplayBundleSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: str
    world: ReplayWorldSpec
    run: ReplayRunSpec
    map: ReplayMapSpec
    agents: list[ReplayAgentSpec] = Field(default_factory=list)
    relationship_graph: dict[str, Any] = Field(default_factory=dict)
    frames: list[ReplayFrameSpec] = Field(default_factory=list)

    @field_validator("generated_at")
    @classmethod
    def _validate_generated_at(cls, value: str) -> str:
        return _non_empty_text(value, "generated_at")

    @model_validator(mode="after")
    def _validate_unique_agents(self) -> "ReplayBundleSpec":
        seen: set[str] = set()
        for agent in self.agents:
            if agent.agent_id in seen:
                raise ValueError(f"duplicate agent_id: {agent.agent_id}")
            seen.add(agent.agent_id)
        return self


class PromptBundleSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    display_name: str
    world_id: str
    world_name: str
    room_id: str
    room_name: str
    room_visual: dict[str, Any] = Field(default_factory=dict)
    core_values: list[str] = Field(default_factory=list)
    personality_tags: list[str] = Field(default_factory=list)
    framework_version: str
    sheet_layout: dict[str, Any] = Field(default_factory=dict)
    processing: dict[str, Any] = Field(default_factory=dict)
    alignment_policy: dict[str, Any] = Field(default_factory=dict)
    concept_prompt: str
    sprite_prompt: str
    negative_prompt: str

    @field_validator("agent_id", "display_name", "world_id", "world_name", "room_id", "room_name", "framework_version", "concept_prompt", "sprite_prompt", "negative_prompt")
    @classmethod
    def _validate_required_strings(cls, value: str) -> str:
        return _non_empty_text(value, "value")


class AssetEventSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: str
    id: str
    display_name: str
    atlas_url: str
    json_url: str
    revision: str
    world_id: str = ""
    world_name: str = ""
    world_revision: str = ""
    portrait_url: str = ""
    default_animation: str
    animations: dict[str, Any] = Field(default_factory=dict)
    generated_at: str

    @field_validator("event", "id", "display_name", "atlas_url", "json_url", "revision", "default_animation", "generated_at")
    @classmethod
    def _validate_required_strings(cls, value: str) -> str:
        return _non_empty_text(value, "value")

    @field_validator("world_id", "world_name", "world_revision", "portrait_url")
    @classmethod
    def _validate_optional_strings(cls, value: str) -> str:
        return str(value).strip()


class AssetBundleSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    revision: str
    world_id: str = ""
    world_name: str = ""
    world_revision: str = ""
    concept_summary: dict[str, Any] = Field(default_factory=dict)
    reference_image_summary: dict[str, Any] = Field(default_factory=dict)
    sprite_summary: dict[str, Any] = Field(default_factory=dict)
    reused_raw_summary: dict[str, Any] = Field(default_factory=dict)
    atlas_png: str
    atlas_json: str
    quality_report_path: str
    raw_sheet_quality_report_path: str = ""
    quality_summary: dict[str, Any] = Field(default_factory=dict)
    overall_status: str = ""
    event: AssetEventSpec

    @field_validator("agent_id", "revision", "atlas_png", "atlas_json", "quality_report_path")
    @classmethod
    def _validate_required_strings(cls, value: str) -> str:
        return _non_empty_text(value, "value")

    @field_validator("world_id", "world_name", "world_revision")
    @classmethod
    def _validate_optional_world_strings(cls, value: str) -> str:
        return str(value).strip()

    @field_validator("raw_sheet_quality_report_path")
    @classmethod
    def _validate_optional_path(cls, value: str) -> str:
        return str(value).strip()

    @field_validator("overall_status")
    @classmethod
    def _validate_overall_status(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            return ""
        return _non_empty_text(text, "overall_status")


class BootstrapAgentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    display_name: str
    room_id: str
    coordinates: GridPosition
    main_character: bool = False
    role_name: str = ""
    activity_directive: str = ""
    appearance_prompt: str = ""
    room_visual: dict[str, Any] = Field(default_factory=dict)
    agent_number: int = 0

    @field_validator("agent_id", "display_name", "room_id")
    @classmethod
    def _validate_required_strings(cls, value: str) -> str:
        return _non_empty_text(value, "value")


class BootstrapAgentsSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: str
    agent_count: int = Field(ge=0)
    agents: list[BootstrapAgentSpec] = Field(default_factory=list)

    @field_validator("generated_at")
    @classmethod
    def _validate_generated_at(cls, value: str) -> str:
        return _non_empty_text(value, "generated_at")

    @model_validator(mode="after")
    def _validate_agents(self) -> "BootstrapAgentsSpec":
        if self.agent_count != len(self.agents):
            raise ValueError("agent_count must match agents length")
        seen: set[str] = set()
        for agent in self.agents:
            if agent.agent_id in seen:
                raise ValueError(f"duplicate agent_id: {agent.agent_id}")
            seen.add(agent.agent_id)
        return self


class MediaJobBaseSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: str
    round_index: int = Field(ge=0)
    actor_id: str
    target_id: str
    prompt_source: str = ""
    route_id: str = ""

    @field_validator("job_id", "status", "actor_id", "target_id")
    @classmethod
    def _validate_required_strings(cls, value: str) -> str:
        return _non_empty_text(value, "value")


class VideoJobSpec(MediaJobBaseSpec):
    prompts_jsonl_path: str = ""
    config_path: str = ""
    command_log_path: str = ""
    video_path: str = ""
    snapshot_path: str = ""
    num_output_frames: int = Field(default=0, ge=0)
    total_rgb_frames: int = Field(default=0, ge=0)
    switch_frame_indices: list[int] = Field(default_factory=list)
    output_video_fps: float = Field(default=0.0, ge=0.0)
    gpu_selection: dict[str, Any] = Field(default_factory=dict)
    actor_prompt: str = ""
    target_continuation_prompt: str = ""
    safety_notes: str = ""
    shared_action_core: dict[str, Any] = Field(default_factory=dict)
    prompt_schedule_seconds: list[int] = Field(default_factory=list)


class ImageJobSpec(MediaJobBaseSpec):
    prompt: str = ""
    artifact_label: str = ""
    safety_notes: str = ""
    job_dir: str = ""
    image_path: str = ""
    image_mime_type: str = ""
    operation: str = ""
    source_owner_agent_id: str = ""
    source_owner_display_name: str = ""
    source_item_id: str = ""
    source_artifact_label: str = ""
    source_image_path: str = ""
    error: str = ""
    raw_text: str = ""
    model: str = ""
    backend: str = ""


class WorldBuilderStructuredSummarySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    room_count: int = Field(default=0, ge=0)
    agent_count: int = Field(default=0, ge=0)
    main_character_count: int = Field(default=0, ge=0)
    role_group_count: int = Field(default=0, ge=0)
    ordinary_route_count: int = Field(default=0, ge=0)
    cinematic_route_count: int = Field(default=0, ge=0)
    custom_action_count: int = Field(default=0, ge=0)
    gameplay_loop_count: int = Field(default=0, ge=0)
    player_entry_point_count: int = Field(default=0, ge=0)
    economy_focus: str = ""
    exploration_focus: str = ""
    longlive_enabled: bool = True
    image_generation_enabled: bool = True
    item_image_mode: str = ""


class WorldBuilderRevisionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision_id: str
    created_at: str
    status: str
    world_name: str = ""
    world_id: str = ""
    summary_path: str = ""
    package_path: str = ""
    package_validation: dict[str, Any] = Field(default_factory=dict)
    startup_validation: dict[str, Any] = Field(default_factory=dict)
    structured_summary: WorldBuilderStructuredSummarySpec = Field(default_factory=WorldBuilderStructuredSummarySpec)
    compiler_critique: dict[str, Any] = Field(default_factory=dict)
    compiled_preview: dict[str, Any] = Field(default_factory=dict)
    error: str = ""

    @field_validator("revision_id", "created_at", "status")
    @classmethod
    def _validate_world_builder_revision_required(cls, value: str) -> str:
        return _non_empty_text(value, "value")


class WorldBuilderGenerationStatusSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    unit_name: str = ""
    stdout_path: str = ""
    updated_at: str = ""
    detail: str = ""
    request_kind: str = ""
    draft_id: str = ""
    revision_id: str = ""
    launcher_returncode: int = 0
    launcher_stdout: str = ""
    launcher_stderr: str = ""

    @field_validator("status")
    @classmethod
    def _validate_world_builder_generation_status(cls, value: str) -> str:
        return _non_empty_text(value, "status")


class WorldBuilderArtStatusSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    unit_name: str = ""
    run_dir: str = ""
    stdout_path: str = ""
    updated_at: str = ""
    detail: str = ""
    logs: list[dict[str, Any]] = Field(default_factory=list)
    qa_summary: dict[str, Any] = Field(default_factory=dict)
    backend_startup_validation: dict[str, Any] = Field(default_factory=dict)
    pixel_launch_validation: dict[str, Any] = Field(default_factory=dict)
    startup_validation: dict[str, Any] = Field(default_factory=dict)

    @field_validator("status")
    @classmethod
    def _validate_world_builder_art_status(cls, value: str) -> str:
        return _non_empty_text(value, "status")


class WorldBuilderPublishStatusSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    access_code: str = ""
    pixel_read: bool = False
    world_url: str = ""
    package_db_url: str = ""
    detail: str = ""
    package_validation: dict[str, Any] = Field(default_factory=dict)
    backend_startup_validation: dict[str, Any] = Field(default_factory=dict)
    pixel_launch_validation: dict[str, Any] = Field(default_factory=dict)
    startup_validation: dict[str, Any] = Field(default_factory=dict)

    @field_validator("status")
    @classmethod
    def _validate_world_builder_publish_status(cls, value: str) -> str:
        return _non_empty_text(value, "status")


class WorldBuilderDraftSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: str
    created_at: str
    updated_at: str
    current_revision: str
    status: str
    art_status: str
    publish_status: str
    published_access_code: str = ""
    world_name: str = ""
    world_id: str = ""
    current_revision_data: WorldBuilderRevisionSpec
    history: list[WorldBuilderRevisionSpec] = Field(default_factory=list)
    world_summary_markdown: str = ""
    package_download_url: str = ""
    generation: WorldBuilderGenerationStatusSpec = Field(default_factory=lambda: WorldBuilderGenerationStatusSpec(status="draft_ready"))
    art: WorldBuilderArtStatusSpec = Field(default_factory=lambda: WorldBuilderArtStatusSpec(status="draft_ready"))
    publish: WorldBuilderPublishStatusSpec = Field(default_factory=lambda: WorldBuilderPublishStatusSpec(status="draft_ready"))

    @field_validator("draft_id", "created_at", "updated_at", "current_revision", "status", "art_status", "publish_status")
    @classmethod
    def _validate_world_builder_draft_required(cls, value: str) -> str:
        return _non_empty_text(value, "value")
