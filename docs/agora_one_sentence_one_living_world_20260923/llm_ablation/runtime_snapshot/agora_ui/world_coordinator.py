"""Validation boundary for open-ended actions proposed by humans or agents."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .adjudicator_schemas import AgentRuntimeProfileSpec, AgentStateBundleSpec


class ProposedEffectSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["speech", "transfer", "create_item", "status"]
    source_agent_id: str = ""
    target_agent_id: str = ""
    item_id: str = ""
    quantity: int = Field(default=1, ge=1, le=99)
    item_name: str = ""
    item_description: str = ""
    input_item_ids: list[str] = Field(default_factory=list)
    status_effect: str = ""
    duration_steps: int = Field(default=1, ge=1, le=20)
    content: str = ""


class OpenActionProposalSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_name: str
    action_text: str
    target_agent_id: str = ""
    rationale: str = ""
    target_response: Literal["accept", "reject", "counter", "not_required", "unknown"] = "unknown"
    effects: list[ProposedEffectSpec] = Field(default_factory=list, max_length=8)


class CoordinatorDecisionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["approved", "rejected", "revise"]
    reason: str
    proposal: OpenActionProposalSpec
    checks: dict[str, bool] = Field(default_factory=dict)


def _inventory_quantity(agent: AgentRuntimeProfileSpec, item_id: str) -> int:
    return sum(item.quantity for item in agent.inventory if item.item_id == item_id)


def evaluate_open_action(
    proposal_payload: dict[str, Any],
    *,
    actor: AgentRuntimeProfileSpec,
    target: AgentRuntimeProfileSpec,
    state: AgentStateBundleSpec,
    config: dict[str, Any],
) -> CoordinatorDecisionSpec:
    proposal = OpenActionProposalSpec.model_validate(proposal_payload)
    agents = {agent.agent_id: agent for agent in state.agents}
    custom_rules = config.get("world_rules", {}).get("custom_action_rules", {})
    allowed_effect_kinds = {
        str(value).strip()
        for value in custom_rules.get(
            "open_proposal_effects",
            ["speech", "transfer", "create_item", "status"],
        )
        if str(value).strip()
    }
    checks = {
        "proposal_enabled": bool(custom_rules.get("open_proposals_enabled", True)),
        "effect_kinds_allowed": all(effect.kind in allowed_effect_kinds for effect in proposal.effects),
        "actor_exists": actor.agent_id in agents,
        "target_exists": not proposal.target_agent_id or proposal.target_agent_id in agents,
        "target_matches_context": not proposal.target_agent_id or proposal.target_agent_id == target.agent_id,
        "same_room_for_physical_effects": True,
        "ownership_and_inputs": True,
        "consent_for_exchange": True,
        "bounded_creation": True,
    }
    physical = any(effect.kind in {"transfer", "create_item", "status"} for effect in proposal.effects)
    if physical and actor.room_id != target.room_id:
        checks["same_room_for_physical_effects"] = False

    needs_consent = False
    for effect in proposal.effects:
        source_id = effect.source_agent_id or actor.agent_id
        source = agents.get(source_id)
        if effect.kind == "transfer":
            if source is None or _inventory_quantity(source, effect.item_id) < effect.quantity:
                checks["ownership_and_inputs"] = False
            if source_id != actor.agent_id or effect.target_agent_id == actor.agent_id:
                needs_consent = True
        elif effect.kind == "create_item":
            if effect.quantity > 3 or not effect.item_name.strip() or not effect.item_description.strip():
                checks["bounded_creation"] = False
            if any(_inventory_quantity(actor, item_id) < 1 for item_id in effect.input_item_ids):
                checks["ownership_and_inputs"] = False
    if needs_consent and proposal.target_response != "accept":
        checks["consent_for_exchange"] = False

    if not proposal.action_name.strip() or not proposal.action_text.strip():
        return CoordinatorDecisionSpec(status="revise", reason="action_name and action_text are required", proposal=proposal, checks=checks)
    if not proposal.effects:
        return CoordinatorDecisionSpec(status="revise", reason="proposal must describe at least one bounded effect", proposal=proposal, checks=checks)
    if all(checks.values()):
        return CoordinatorDecisionSpec(status="approved", reason="proposal satisfies world-state, proximity, ownership, consent, and bounded-effect checks", proposal=proposal, checks=checks)
    failed = [name for name, passed in checks.items() if not passed]
    return CoordinatorDecisionSpec(status="rejected", reason="failed coordinator checks: " + ", ".join(failed), proposal=proposal, checks=checks)


def proposal_route(decision: CoordinatorDecisionSpec) -> dict[str, Any]:
    proposal = decision.proposal
    slug = re.sub(r"[^a-z0-9]+", "_", proposal.action_name.lower()).strip("_")[:48] or "open_action"
    return {
        "route_id": f"proposed_{slug}",
        "kind": "custom",
        "action": proposal.action_name[:80],
        "story_verb": proposal.action_name.lower()[:96],
        "selection_guidance": proposal.rationale[:240],
        "status_effect": f"proposed_{slug}",
        "duration_steps": 1,
        "open_action_proposal": proposal.model_dump(),
        "coordinator_decision": decision.model_dump(),
    }
