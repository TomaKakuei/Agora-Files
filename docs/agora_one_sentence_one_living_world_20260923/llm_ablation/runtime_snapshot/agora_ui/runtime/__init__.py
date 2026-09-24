from .defaults import compile_orchestration_config
from .engine import BaseComponent, PhaseTraceComponent, RuntimeEngine, RuntimeExecutionContext
from .operations import OPERATION_REGISTRY


def build_runtime_engine() -> RuntimeEngine:
    component_registry = {
        "base": lambda component_id, spec: BaseComponent(component_id=component_id, config=spec),
        "phase_trace": lambda component_id, spec: PhaseTraceComponent(component_id=component_id, config=spec),
    }
    return RuntimeEngine(operation_registry=OPERATION_REGISTRY, component_registry=component_registry)
