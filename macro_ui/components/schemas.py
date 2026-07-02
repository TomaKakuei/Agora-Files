from __future__ import annotations
from typing import Any, Optional
from pydantic import BaseModel, Field

class RunLaunchRequest(BaseModel):
    run_id: str = Field(default="")
    resume_run_id: str = Field(default="")
    world_name: str = Field(default="")
    world_id: str = Field(default="")
    domain_label: str = Field(default="")
    description: str = Field(default="")
    regular_agent_count: int = Field(default=40, ge=8, le=120)
    rounds: int = Field(default=25, ge=1, le=60)
    activation_probability: float = Field(default=0.3, ge=0.0, le=1.0)
    seed: int = Field(default=42627, ge=1, le=999999999)
    main_characters_always_activate: bool = True
    max_videos_per_round: int = Field(default=1, ge=0, le=10)
    max_images_per_round: int = Field(default=1, ge=0, le=10)
    segment_seconds: int = Field(default=4, ge=2, le=12)
    start_asset_worker: bool = True
    package_access_code: str = Field(default="")
    world_config: Optional[dict[str, Any]] = None


class AssetWorkerRequest(BaseModel):
    force_refresh_images: bool = False


class HumanPresenceRequest(BaseModel):
    display_name: str = Field(default="Human Interactor")
    room_id: str = Field(default="")
    coordinates: Optional[dict[str, int]] = None
    appearance_prompt: str = Field(default="")
    speed_seconds_per_round: float = Field(default=8.0, ge=0.5, le=120.0)


class HumanActionRequest(BaseModel):
    display_name: str = Field(default="Human Interactor")
    room_id: str = Field(default="")
    coordinates: Optional[dict[str, int]] = None
    target_agent_id: str = Field(default="")
    action_text: str = Field(default="")
    speed_seconds_per_round: float = Field(default=8.0, ge=0.5, le=120.0)


class PackageExportRequest(BaseModel):
    world_config: dict[str, Any]
    package_name: str = Field(default="")
    source_label: str = Field(default="macro_ui_export")


class WorldBuilderDraftCreateRequest(BaseModel):
    world_name: str = Field(default="")
    genre: str = Field(default="")
    player_count_target: int = Field(default=4, ge=1, le=50)
    agent_count_target: int = Field(default=40, ge=8, le=120)
    focus: str = Field(default="")
    seed: int = Field(default=42627, ge=1, le=999999999)
    brief: str = Field(default="")


class WorldBuilderDraftReviseRequest(BaseModel):
    feedback: str = Field(default="")


class PixelLiveSessionCreateRequest(BaseModel):
    display_name: str = Field(default="Human Interactor")
    room_id: str = Field(default="")
    speed_seconds_per_round: float = Field(default=8.0, ge=0.5, le=120.0)


class PixelLiveActionRequest(BaseModel):
    session_id: str = Field(default="")
    action_type: str = Field(default="message")
    client_action_id: str = Field(default="")
    action_text: str = Field(default="")
    target_agent_id: str = Field(default="")
    direction: str = Field(default="")
    item_id: str = Field(default="")
    return_item_id: str = Field(default="")
    offer_id: str = Field(default="")
    quantity: int = Field(default=1, ge=1, le=99)
    room_id: str = Field(default="")
    destination_room_id: str = Field(default="")
    coordinates: Optional[dict[str, int]] = None
