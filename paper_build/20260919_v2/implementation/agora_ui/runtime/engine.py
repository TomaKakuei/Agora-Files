from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol


OperationHandler = Callable[["RuntimeExecutionContext", dict[str, Any]], None]


class RuntimeComponent(Protocol):
    component_id: str

    def on_phase_start(self, ctx: "RuntimeExecutionContext", phase: dict[str, Any]) -> None:
        ...

    def on_phase_end(self, ctx: "RuntimeExecutionContext", phase: dict[str, Any]) -> None:
        ...

    def get_state(self) -> dict[str, Any]:
        ...

    def set_state(self, payload: dict[str, Any]) -> None:
        ...


@dataclass
class EventBus:
    events: list[dict[str, Any]] = field(default_factory=list)

    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        self.events.append({"topic": topic, "payload": dict(payload)})

    def topic(self, topic: str) -> list[dict[str, Any]]:
        return [dict(item["payload"]) for item in self.events if item.get("topic") == topic]

    def get_state(self) -> dict[str, Any]:
        return {"events": [dict(item) for item in self.events]}

    def set_state(self, payload: dict[str, Any]) -> None:
        raw = payload.get("events", [])
        self.events = [dict(item) for item in raw if isinstance(item, dict)]


@dataclass
class BaseComponent:
    component_id: str
    config: dict[str, Any] = field(default_factory=dict)

    def on_phase_start(self, ctx: "RuntimeExecutionContext", phase: dict[str, Any]) -> None:
        return None

    def on_phase_end(self, ctx: "RuntimeExecutionContext", phase: dict[str, Any]) -> None:
        return None

    def get_state(self) -> dict[str, Any]:
        return {}

    def set_state(self, payload: dict[str, Any]) -> None:
        return None


@dataclass
class PhaseTraceComponent(BaseComponent):
    transitions: list[dict[str, Any]] = field(default_factory=list)

    def on_phase_start(self, ctx: "RuntimeExecutionContext", phase: dict[str, Any]) -> None:
        self.transitions.append({"phase_id": str(phase.get("phase_id", "")), "event": "start"})

    def on_phase_end(self, ctx: "RuntimeExecutionContext", phase: dict[str, Any]) -> None:
        self.transitions.append({"phase_id": str(phase.get("phase_id", "")), "event": "end"})

    def get_state(self) -> dict[str, Any]:
        return {"transitions": [dict(item) for item in self.transitions]}

    def set_state(self, payload: dict[str, Any]) -> None:
        raw = payload.get("transitions", [])
        self.transitions = [dict(item) for item in raw if isinstance(item, dict)]


@dataclass
class RuntimeExecutionContext:
    args: Any
    config_path: Path
    config: dict[str, Any]
    plan: dict[str, Any]
    store: dict[str, Any] = field(default_factory=dict)
    event_bus: EventBus = field(default_factory=EventBus)
    components: dict[str, RuntimeComponent] = field(default_factory=dict)

    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        self.event_bus.publish(topic, payload)

    def set(self, key: str, value: Any) -> Any:
        self.store[key] = value
        return value

    def get(self, key: str, default: Any = None) -> Any:
        return self.store.get(key, default)

    def require(self, key: str) -> Any:
        if key not in self.store:
            raise KeyError(f"runtime context missing required key: {key}")
        return self.store[key]

    def component_state(self) -> dict[str, Any]:
        return {component_id: component.get_state() for component_id, component in self.components.items()}


class RuntimeEngine:
    def __init__(
        self,
        *,
        operation_registry: dict[str, OperationHandler],
        component_registry: dict[str, Callable[[str, dict[str, Any]], RuntimeComponent]],
    ) -> None:
        self._operation_registry = dict(operation_registry)
        self._component_registry = dict(component_registry)

    def initialize_components(self, ctx: RuntimeExecutionContext) -> None:
        component_specs = ctx.plan.get("components", [])
        for spec in component_specs:
            if not isinstance(spec, dict):
                continue
            component_id = str(spec.get("component_id", "")).strip()
            kind = str(spec.get("kind", "")).strip()
            if not component_id or not kind:
                continue
            factory = self._component_registry.get(kind)
            if factory is None:
                raise KeyError(f"unknown runtime component kind: {kind}")
            ctx.components[component_id] = factory(component_id, dict(spec))

    def execute(self, ctx: RuntimeExecutionContext) -> None:
        self.initialize_components(ctx)
        for phase in ctx.plan.get("phases", []):
            if isinstance(phase, dict):
                self._execute_phase(ctx, phase)

    def _execute_phase(self, ctx: RuntimeExecutionContext, phase: dict[str, Any]) -> None:
        if not self._condition_allows(ctx, phase):
            return
        ctx.publish("phase_start", {"phase_id": str(phase.get("phase_id", ""))})
        for component in ctx.components.values():
            component.on_phase_start(ctx, phase)
        self._execute_node(ctx, phase)
        for component in ctx.components.values():
            component.on_phase_end(ctx, phase)
        ctx.publish("phase_end", {"phase_id": str(phase.get("phase_id", ""))})

    def _execute_node(self, ctx: RuntimeExecutionContext, node: dict[str, Any]) -> None:
        if not self._condition_allows(ctx, node):
            return
        iterable_name = str(node.get("for_each", "")).strip()
        if iterable_name:
            iterable = ctx.get(iterable_name, [])
            if not isinstance(iterable, list):
                return
            item_as = str(node.get("item_as", "item")).strip() or "item"
            previous_value = ctx.store.get(item_as, None)
            had_previous = item_as in ctx.store
            for index, item in enumerate(iterable):
                ctx.store[item_as] = item
                ctx.store[f"{item_as}_index"] = index
                for step in node.get("steps", []):
                    if isinstance(step, dict):
                        self._execute_node(ctx, step)
            ctx.store.pop(f"{item_as}_index", None)
            if had_previous:
                ctx.store[item_as] = previous_value
            else:
                ctx.store.pop(item_as, None)
            return
        operation_name = str(node.get("operation", "")).strip()
        if operation_name:
            handler = self._operation_registry.get(operation_name)
            if handler is None:
                raise KeyError(f"unknown runtime operation: {operation_name}")
            handler(ctx, node)
            return
        for step in node.get("steps", []):
            if isinstance(step, dict):
                self._execute_node(ctx, step)

    def _condition_allows(self, ctx: RuntimeExecutionContext, node: dict[str, Any]) -> bool:
        when = node.get("when")
        if when is None:
            return True
        if isinstance(when, bool):
            return when
        if isinstance(when, str):
            return bool(ctx.get(when))
        if isinstance(when, dict):
            key = str(when.get("store_key", "")).strip()
            if not key:
                return True
            expected = when.get("equals", True)
            return ctx.get(key) == expected
        return True
