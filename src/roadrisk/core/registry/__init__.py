"""Factor registry — the declarative core of the engine."""

from roadrisk.core.registry.loader import (
    DEFAULT_REGISTRY_PATH,
    load_registry,
    parse_registry,
)
from roadrisk.core.registry.schema import (
    LICENCE_POLICY,
    TIER_MEANING,
    Adapter,
    CrashScope,
    FacilityType,
    Factor,
    Licence,
    LicencePolicy,
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
    "LICENCE_POLICY",
    "TIER_MEANING",
    "Adapter",
    "CrashScope",
    "FacilityType",
    "Factor",
    "Licence",
    "LicencePolicy",
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
