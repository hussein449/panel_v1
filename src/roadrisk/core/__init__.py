"""Core engine — a plain library.

Nothing in here imports the API, worker, CLI or report layers, and nothing in here
touches a network or a database. A corridor can be assessed from a script with only
the core dependencies installed, which is what keeps the method testable independently
of the product around it.
"""

from roadrisk.core.context import RunContext
from roadrisk.core.contract import ContractReport, prepare_panel
from roadrisk.core.crashmix import DEFAULT_CRASH_MIX, CrashMix, uniform_mix
from roadrisk.core.diagnostics import (
    DispersionReport,
    Family,
    VIFReport,
    compute_dispersion,
    compute_vif,
)
from roadrisk.core.engine import Assessment, assess
from roadrisk.core.errors import (
    ContractViolation,
    RegistryError,
    RoadRiskError,
    TransformError,
    WeightNotSourced,
)
from roadrisk.core.gates import (
    CheckResult,
    CheckStatus,
    FailureType,
    GateReport,
    SnapReport,
)
from roadrisk.core.ladder import LadderResult, Mode, Rung, walk_ladder
from roadrisk.core.models import Coefficient, FitResult, IndexResult
from roadrisk.core.registry import (
    FacilityType,
    Factor,
    Region,
    Registry,
    Severity,
    Sign,
    Weight,
    WeightFamily,
    load_registry,
)
from roadrisk.core.runlog import RunLog, RunManifest
from roadrisk.core.signguard import SignGuardReport, run_sign_guard
from roadrisk.core.weights import Agreement, WeightSelection, select_weight

__all__ = [
    "DEFAULT_CRASH_MIX",
    "Agreement",
    "Assessment",
    "CheckResult",
    "CrashMix",
    "CheckStatus",
    "Coefficient",
    "ContractReport",
    "ContractViolation",
    "DispersionReport",
    "FacilityType",
    "FailureType",
    "Family",
    "Factor",
    "FitResult",
    "GateReport",
    "IndexResult",
    "LadderResult",
    "Mode",
    "Region",
    "RegistryError",
    "Registry",
    "RoadRiskError",
    "Rung",
    "RunContext",
    "RunLog",
    "RunManifest",
    "Severity",
    "Sign",
    "SignGuardReport",
    "SnapReport",
    "TransformError",
    "VIFReport",
    "Weight",
    "WeightFamily",
    "WeightNotSourced",
    "WeightSelection",
    "assess",
    "compute_dispersion",
    "compute_vif",
    "load_registry",
    "prepare_panel",
    "run_sign_guard",
    "select_weight",
    "uniform_mix",
    "walk_ladder",
]
