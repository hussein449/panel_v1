"""Factor registry — the declarative core of the engine."""

from roadrisk.core.registry.loader import (
    DEFAULT_REGISTRY_PATH,
    load_registry,
    parse_registry,
)
from roadrisk.core.registry.schema import (
    Adapter,
    CrashScope,
    FacilityType,
    Factor,
    Licence,
    Region,
    Registry,
    Severity,
    Sign,
    Tier,
    Transform,
    Weight,
    WeightFamily,
)

__all__ = [
    "DEFAULT_REGISTRY_PATH",
    "Adapter",
    "CrashScope",
    "FacilityType",
    "Factor",
    "Licence",
    "Region",
    "Registry",
    "Severity",
    "Sign",
    "Tier",
    "Transform",
    "Weight",
    "WeightFamily",
    "load_registry",
    "parse_registry",
]
