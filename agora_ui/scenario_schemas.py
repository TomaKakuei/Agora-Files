"""Schemas for Scenario Manifest launcher packaging."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .adjudicator_schemas import RelationshipVectorSpec
from .foundation_schemas import GridPosition, GridShape, RoomSpec


ProviderName = Literal["Local", "Gemini_Studio", "Vertex_AI", "GPT", "Generic"]


class ScenarioMetaSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    world_id: str
    world_name: str
    version: str = "1.0"
    description: str
    simulation_objective: str = ""
    player_entry_points: list[str] = Field(default_factory=list)
    creator_conflict_hooks: list[str] = Field(default_factory=list)

    @field_validator("world_id", "world_name", "description")
    @classmethod
    def _validate_required_strings(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("must be non-empty")
        return text


class ScenarioApiConfigSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: ProviderName = "Local"
    model: str = ""
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    flex_api_url: str = "http://127.0.0.1:8000/v1"
    server_script: str = ""


class ScenarioSimulationParamsSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_timesteps: int = Field(default=1, ge=1)
    parallel_execution: bool = True
    tick_rate_ms: int = Field(default=0, ge=0)
    concurrency_limit: int = Field(default=10, ge=1)


class ScenarioEngineConfigSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    world_mode: Literal["Fixed", "LLM_Wrap"] = "LLM_Wrap"
    adjudicator_api: ScenarioApiConfigSpec = Field(default_factory=ScenarioApiConfigSpec)
    agent_default_api: ScenarioApiConfigSpec = Field(default_factory=lambda: ScenarioApiConfigSpec(provider="Local", temperature=0.8))
    simulation_params: ScenarioSimulationParamsSpec = Field(default_factory=ScenarioSimulationParamsSpec)


class ScenarioAssetBindingsSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    world_rules_path: str = "./world_rules.json"
    map_grid_path: str = "./map_grid.json"
    active_agents: list[str] = Field(default_factory=list)
    relationship_tensor_path: str = ""
    localized_visual_state_path: str = ""
    intents_path: str = "./agent_intents.json"
    intent_batches_path: str = ""
    prompt_path: str = ""

    @model_validator(mode="after")
    def _validate_agent_paths(self) -> "ScenarioAssetBindingsSpec":
        if not self.active_agents:
            raise ValueError("active_agents must contain at least one agent file")
        return self


class ScenarioManifestSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_meta: ScenarioMetaSpec
    engine_config: ScenarioEngineConfigSpec
    asset_bindings: ScenarioAssetBindingsSpec


class ScenarioMapGridSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grid_shape: GridShape = Field(default_factory=GridShape)
    map_visual: dict[str, Any] = Field(default_factory=dict)
    rooms: list[RoomSpec] = Field(default_factory=list)
    initial_positions: dict[str, GridPosition] = Field(default_factory=dict)
    initial_room_ids: dict[str, str] = Field(default_factory=dict)


class RelationshipTensorBundleSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relationship_tensor: dict[str, dict[str, RelationshipVectorSpec]] = Field(default_factory=dict)
