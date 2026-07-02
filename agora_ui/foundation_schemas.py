"""Shared schemas for the unified agent/world/flex foundation layer."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class GridPosition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    z: int = Field(ge=0)


class GridShape(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: int = Field(default=1, ge=1)
    y: int = Field(default=1, ge=1)
    z: int = Field(default=1, ge=1)


class DoorwaySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doorway_id: str = ""
    position: GridPosition
    connects_to_room_id: str = ""
    label: str = ""


class AgentSeed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    display_name: str
    reference_source: str = ""
    reference_profile: str = ""
    profile_brief: str = ""
    user_core_values: list[str] = Field(default_factory=list)
    attributes: dict[str, int] = Field(default_factory=dict)
    gender_presentation: str = ""
    appearance_prompt: str = ""
    voice_style: str = ""
    stance: str = ""
    runtime_tags: list[str] = Field(default_factory=list)
    generation_mode: Literal["auto", "user"] = "auto"

    @field_validator("agent_id", "display_name")
    @classmethod
    def _validate_required_strings(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("must be non-empty")
        return text

    @field_validator("attributes")
    @classmethod
    def _validate_attributes(cls, value: dict[str, int]) -> dict[str, int]:
        clean: dict[str, int] = {}
        for key, raw in dict(value).items():
            number = int(raw)
            if not 0 <= number <= 100:
                raise ValueError(f"attribute '{key}' must be within 0..100")
            clean[str(key)] = number
        return clean


class AgentSeedList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_name: str = "agent_seed_list"
    agents: list[AgentSeed]

    @model_validator(mode="after")
    def _validate_unique_agent_ids(self) -> "AgentSeedList":
        seen: set[str] = set()
        for item in self.agents:
            if item.agent_id in seen:
                raise ValueError(f"duplicate agent_id: {item.agent_id}")
            seen.add(item.agent_id)
        return self


class AgentProfileWorkflow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_name: str = "agent_profile_workflow"
    flex_api_url: str = "http://127.0.0.1:8000/v1"
    model: str = ""
    default_generation_mode: Literal["auto", "user"] = "auto"
    default_core_values: list[str] = Field(default_factory=list)
    default_attributes: dict[str, int] = Field(default_factory=dict)
    default_runtime_tags: list[str] = Field(default_factory=list)
    default_voice_style: str = ""
    default_stance: str = ""
    output_subdir: str = "output/agent_profile_workflow"
    generated_profile_filename: str = "generated_profiles.jsonc"
    compiled_profile_filename: str = "compiled_profiles.json"
    max_retries: int = Field(default=2, ge=1, le=8)

    @field_validator("default_attributes")
    @classmethod
    def _validate_default_attributes(cls, value: dict[str, int]) -> dict[str, int]:
        clean: dict[str, int] = {}
        for key, raw in dict(value).items():
            number = int(raw)
            if not 0 <= number <= 100:
                raise ValueError(f"default attribute '{key}' must be within 0..100")
            clean[str(key)] = number
        return clean


class AgentProfileSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    display_name: str
    reference_source: str = ""
    reference_profile: str = ""
    profile_brief: str
    core_values: list[str]
    attributes: dict[str, int] = Field(default_factory=dict)
    gender_presentation: str = ""
    appearance_prompt: str = ""
    voice_style: str = ""
    stance: str = ""
    runtime_tags: list[str] = Field(default_factory=list)
    generated_from: Literal["seed_user", "seed_auto", "workflow_default"] = "seed_auto"

    @field_validator("agent_id", "display_name", "profile_brief")
    @classmethod
    def _validate_profile_strings(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("must be non-empty")
        return text

    @field_validator("core_values")
    @classmethod
    def _validate_core_values(cls, value: list[str]) -> list[str]:
        clean = [str(item).strip() for item in value if str(item).strip()]
        if not clean:
            raise ValueError("core_values must contain at least one item")
        return clean

    @field_validator("attributes")
    @classmethod
    def _validate_profile_attributes(cls, value: dict[str, int]) -> dict[str, int]:
        clean: dict[str, int] = {}
        for key, raw in dict(value).items():
            number = int(raw)
            if not 0 <= number <= 100:
                raise ValueError(f"attribute '{key}' must be within 0..100")
            clean[str(key)] = number
        return clean


class GeneratedAgentProfiles(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_name: str
    generated_at: str
    profiles: list[AgentProfileSpec]


class AgentProfileCompileResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_name: str
    generated_at: str
    profile_count: int = Field(ge=0)
    profiles: list[AgentProfileSpec]
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class RoomSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    room_id: str = ""
    name: str = ""
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    z: int = Field(ge=0)
    width_tiles: int = Field(default=1, ge=1)
    height_tiles: int = Field(default=1, ge=1)
    footprint_tiles: list[GridPosition] = Field(default_factory=list)
    doorways: list[DoorwaySpec] = Field(default_factory=list)
    spawn_points: list[GridPosition] = Field(default_factory=list)
    visual: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    footprint_area: int = Field(default=0, ge=0)
    capacity_estimate: int = Field(default=0, ge=0)
    occupancy_density: float = Field(default=0.0, ge=0.0)
    pressure_band: str = ""
    image_url: str = ""
    flux_floor_prompt: str = ""
    room_scene_prompt: str = ""


class WorldTopology(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topology_mode: Literal["grid", "rooms"] = "grid"
    grid_shape: GridShape = Field(default_factory=GridShape)
    rooms: list[RoomSpec] = Field(default_factory=list)


class OccupancyPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_agents_per_room: int = Field(default=1, ge=1)


class WorldSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    world_id: str
    world_description: str
    world_summary: str = ""
    movement_mode: Literal["single", "multi"] = "multi"
    turn_order: Literal["round_robin", "agent_id"] = "round_robin"
    conflict_resolution: Literal["agent_id_order"] = "agent_id_order"
    world_rules: list[str] = Field(default_factory=list)
    topology: WorldTopology
    occupancy_policy: OccupancyPolicy = Field(default_factory=OccupancyPolicy)
    interaction_rules: list[Any] = Field(default_factory=list)
    item_rules: dict[str, Any] = Field(default_factory=dict)

    @field_validator("world_id", "world_description")
    @classmethod
    def _validate_world_strings(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("must be non-empty")
        return text


class MovementAxisBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: int = Field(default=1, ge=0)
    y: int = Field(default=1, ge=0)
    z: int = Field(default=1, ge=0)


class MovementPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    basis: Literal["grid", "room"] = "grid"
    min_steps: int = Field(default=0, ge=0)
    max_steps: int = Field(default=1, ge=0)
    axis_step_budget: MovementAxisBudget = Field(default_factory=MovementAxisBudget)

    @model_validator(mode="after")
    def _validate_step_bounds(self) -> "MovementPolicy":
        if self.max_steps < self.min_steps:
            raise ValueError("max_steps must be >= min_steps")
        return self


class WorldAgentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    display_name: str = ""
    initial_room_id: Optional[str] = None
    initial_coordinate: Optional[GridPosition] = None
    movement_policy: Optional[MovementPolicy] = None
    notes: str = ""

    @field_validator("agent_id")
    @classmethod
    def _validate_agent_id(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("agent_id must be non-empty")
        return text


class WorldAgentsSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active_agent_ids: list[str] = Field(default_factory=list)
    inactive_agent_ids: list[str] = Field(default_factory=list)
    agents: list[WorldAgentSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_agent_lists(self) -> "WorldAgentsSpec":
        active = {item.strip() for item in self.active_agent_ids if str(item).strip()}
        inactive = {item.strip() for item in self.inactive_agent_ids if str(item).strip()}
        overlap = sorted(active & inactive)
        if overlap:
            raise ValueError(
                "active_agent_ids and inactive_agent_ids must be disjoint: "
                + ", ".join(overlap)
            )
        seen: set[str] = set()
        for item in self.agents:
            if item.agent_id in seen:
                raise ValueError(f"duplicate agent_id in world_agents: {item.agent_id}")
            seen.add(item.agent_id)
        return self


class WorldControlSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_name: str = "world_rule_debug"
    rounds: int = Field(default=5, ge=0)
    seed: int = 42
    log_level: Literal["summary", "round", "verbose"] = "round"
    validate_only: bool = False
    default_room_name_prefix: str = "room"
    default_movement_policy: MovementPolicy = Field(default_factory=MovementPolicy)
    clock: "WorldClockSpec" = Field(default_factory=lambda: WorldClockSpec())
    decision: "DecisionRuntimeSpec" = Field(default_factory=lambda: DecisionRuntimeSpec())
    output_subdir: str = "output/world_rule_debug"


class WorldClockSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    initial_time: str = "08:00"
    step_minutes: int = Field(default=5, ge=1)

    @field_validator("initial_time")
    @classmethod
    def _validate_initial_time(cls, value: str) -> str:
        text = str(value).strip()
        parts = text.split(":")
        if len(parts) != 2:
            raise ValueError("initial_time must use HH:MM format")
        try:
            hour = int(parts[0])
            minute = int(parts[1])
        except Exception as exc:
            raise ValueError("initial_time must use HH:MM format") from exc
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("initial_time must be within 00:00..23:59")
        return f"{hour:02d}:{minute:02d}"


class DecisionRuntimeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backend: Literal["heuristic", "flex"] = "heuristic"
    flex_api_url: str = "http://127.0.0.1:8000/v1"
    model: str = ""
    thinking_level: Literal["none", "low", "medium", "high"] = "low"
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    concurrency_limit: int = Field(default=10, ge=0)
    request_timeout_seconds: float = Field(default=30.0, ge=1.0)
    max_output_tokens: int = Field(default=512, ge=32)


class CompiledRoomSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    room_id: str
    name: str
    coordinate: GridPosition


class CompiledWorldAgent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    display_name: str
    active: bool
    initial_room_id: str
    initial_coordinate: GridPosition
    movement_policy: MovementPolicy


class CompiledWorldSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    world: WorldSpec
    control: WorldControlSpec
    rooms: list[CompiledRoomSpec]
    agents: list[CompiledWorldAgent]


class WorldRuleTraceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    round_index: int = Field(ge=1)
    clock_time: str
    agent_id: str
    active: bool
    movement_mode: Literal["single", "multi"]
    decision_backend: Literal["heuristic", "flex"]
    decision_status: Literal[
        "inactive",
        "idle",
        "moved",
        "blocked",
        "conflict_lost",
    ]
    decision_reason: str = ""
    basis: Literal["grid", "room"]
    steps_requested: int = Field(ge=0)
    steps_executed: int = Field(ge=0)
    blocked_steps: int = Field(ge=0)
    start_room_id: str
    end_room_id: str
    requested_target_room_id: Optional[str] = None
    start_coordinate: GridPosition
    end_coordinate: GridPosition
    visited_room_ids: list[str] = Field(default_factory=list)
    note: str = ""


class WorldRuleDebugManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    world_id: str
    rounds: int = Field(ge=0)
    movement_mode: Literal["single", "multi"]
    final_clock_time: str
    room_count: int = Field(ge=0)
    agent_count: int = Field(ge=0)
    active_agent_count: int = Field(ge=0)
    files: dict[str, str] = Field(default_factory=dict)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
