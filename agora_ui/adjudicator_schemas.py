"""Schemas for the Universal Core Adjudicator workflow."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .foundation_schemas import GridPosition, GridShape, RoomSpec, WorldClockSpec


ActionCall = Literal["Move", "Custom", "Item", "Image"]
WorldMode = Literal["Fixed", "LLM_Wrap"]


class AdjudicatorPromptSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_name: str = "universal_core_adjudicator"
    template_lines: list[str]

    @field_validator("template_lines")
    @classmethod
    def _validate_template_lines(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("template_lines must not be empty")
        return [str(item) for item in value]


class AdjudicatorFlexSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flex_api_url: str = "http://127.0.0.1:8000/v1"
    model: str = ""
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    thinking_level: Literal["none", "low", "medium", "high"] = "medium"
    max_output_tokens: int = Field(default=2048, ge=128)
    timeout_seconds: float = Field(default=60.0, ge=1.0)


class AdjudicatorControlSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_name: str = "universal_adjudicator"
    adjudication_backend: Literal["local", "flex"] = "local"
    world_description: str
    simulation_objective: str
    social_norms: list[str] = Field(default_factory=list)
    clock: WorldClockSpec = Field(default_factory=WorldClockSpec)
    timestep_index: int = Field(default=1, ge=1)
    priority_order: list[ActionCall] = Field(
        default_factory=lambda: ["Move", "Custom", "Item", "Image"]
    )
    prompt_file: str = "data/templates/foundation/universal_adjudicator_prompt.jsonc"
    output_subdir: str = "output/universal_adjudicator"
    flex: AdjudicatorFlexSpec = Field(default_factory=AdjudicatorFlexSpec)

    @field_validator("world_description", "simulation_objective")
    @classmethod
    def _validate_required_strings(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("must be non-empty")
        return text

    @model_validator(mode="after")
    def _validate_priority_order(self) -> "AdjudicatorControlSpec":
        seen: set[str] = set()
        for item in self.priority_order:
            if item in seen:
                raise ValueError(f"duplicate priority action: {item}")
            seen.add(item)
        missing = [item for item in ["Move", "Custom", "Item", "Image"] if item not in seen]
        if missing:
            raise ValueError("priority_order missing action(s): " + ", ".join(missing))
        return self


class MovementRuleSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_steps_per_timestep: int = Field(default=1, ge=0)
    capacity_per_coordinate: int = Field(default=1, ge=1)
    line_of_sight_required: bool = False
    allow_diagonal: bool = False


class ItemRulesSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    mass_conservation: bool = True
    require_same_coordinate_for_transfer: bool = True
    combinations: list[dict[str, Any]] = Field(default_factory=list)


class ImageRulesSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    enabled: bool = True
    allowed_operations: list[str] = Field(default_factory=lambda: ["create", "modify", "analyze"])


class CustomActionRulesSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    default_duration_steps: int = Field(default=2, ge=1)
    max_range_steps: int = Field(default=1, ge=0)
    allowed_actions: list[str] = Field(default_factory=lambda: ["Repair", "Signal"])


class WorldRulesTopologySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grid_shape: GridShape = Field(default_factory=GridShape)
    rooms: list[RoomSpec] = Field(default_factory=list)


class WorldRulesSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    world_mode: WorldMode = "LLM_Wrap"
    topology: WorldRulesTopologySpec = Field(default_factory=WorldRulesTopologySpec)
    movement: MovementRuleSpec = Field(default_factory=MovementRuleSpec)
    item_rules: ItemRulesSpec = Field(default_factory=ItemRulesSpec)
    image_rules: ImageRulesSpec = Field(default_factory=ImageRulesSpec)
    custom_action_rules: CustomActionRulesSpec = Field(default_factory=CustomActionRulesSpec)
    social_rules: list[str] = Field(default_factory=list)
    discovered_rules: list[dict[str, Any]] = Field(default_factory=list)


class InventoryItemSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str
    name: str = ""
    quantity: int = Field(default=1, ge=0)
    mass: float = Field(default=0.0, ge=0.0)
    description: str = ""
    image_path: str = ""
    image_prompt: str = ""
    condition: str = ""
    authenticity_state: str = ""
    trade_state: str = ""
    asking_price_minor: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("item_id")
    @classmethod
    def _validate_item_id(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("item_id must be non-empty")
        return text


class WalletSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency_code: str = "CNY"
    currency_symbol: str = "¥"
    minor_unit: str = "fen"
    amount_minor: int = Field(default=0, ge=0)


class PropertyAssetSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_name: str
    asset_type: str = ""
    description: str = ""
    story_use: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeAssetSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    knowledge_id: str = ""
    topic: str = ""
    summary: str = ""
    confidence: int = Field(default=50, ge=0, le=100)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StatusEffectSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effect: str
    duration_steps: int = Field(default=1, ge=1)
    source: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("effect")
    @classmethod
    def _validate_effect(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("effect must be non-empty")
        return text


class RelationshipVectorSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trust: int = Field(default=50, ge=0, le=100)
    affection: int = Field(default=50, ge=0, le=100)
    influence_fear: int = Field(default=0, ge=0, le=100)


class AgentRuntimeProfileSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    agent_number: int = 0
    display_name: str = ""
    gender_presentation: str = ""
    appearance_prompt: str = ""
    main_character: bool = False
    role_name: str = ""
    activity_directive: str = ""
    room_visual: dict[str, Any] = Field(default_factory=dict)
    core_values: list[str] = Field(default_factory=list)
    wallet: WalletSpec = Field(default_factory=WalletSpec)
    inventory: list[InventoryItemSpec] = Field(default_factory=list)
    property_library: list[PropertyAssetSpec] = Field(default_factory=list)
    knowledge_assets: list[KnowledgeAssetSpec] = Field(default_factory=list)
    coordinates: GridPosition
    room_id: str = ""
    status_effects: list[StatusEffectSpec] = Field(default_factory=list)
    public_state: dict[str, Any] = Field(default_factory=dict)
    private_notes: str = ""

    @field_validator("agent_id")
    @classmethod
    def _validate_agent_id(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("agent_id must be non-empty")
        return text


class AgentStateBundleSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agents: list[AgentRuntimeProfileSpec]
    relationship_tensor: dict[str, dict[str, RelationshipVectorSpec]] = Field(default_factory=dict)
    localized_visual_state: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_unique_agents(self) -> "AgentStateBundleSpec":
        seen: set[str] = set()
        for agent in self.agents:
            if agent.agent_id in seen:
                raise ValueError(f"duplicate agent_id: {agent.agent_id}")
            seen.add(agent.agent_id)
        return self


class ActionIntentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent_id: str
    agent_id: str
    call: ActionCall
    intent_text: str = ""
    target_agent_id: Optional[str] = None
    target_coordinates: Optional[GridPosition] = None
    operation: str = ""
    action: str = ""
    item_id: str = ""
    target_item_ids: list[str] = Field(default_factory=list)
    quantity: int = Field(default=1, ge=1)
    api_prompt: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("intent_id", "agent_id")
    @classmethod
    def _validate_required_id(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("must be non-empty")
        return text


class AgentIntentBatchSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestep_index: int = Field(default=1, ge=1)
    intents: list[ActionIntentSpec] = Field(default_factory=list)


class AdjudicatorManifestSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    timestep_index: int = Field(ge=1)
    backend: Literal["local", "flex"]
    world_mode: WorldMode
    files: dict[str, str] = Field(default_factory=dict)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
