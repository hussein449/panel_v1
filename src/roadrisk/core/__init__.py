"""Core engine — a plain library.

Nothing in here imports the API, worker, CLI or report layers, and nothing in here
touches a network or a database. A corridor can be assessed from a script with only
the core dependencies installed, which is what keeps the method testable independently
of the product around it.
"""

from roadrisk.core.contract import ContractReport, prepare_panel
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
from roadrisk.core.registry import Factor, Registry, Sign, load_registry
from roadrisk.core.runlog import RunLog, RunManifest
from roadrisk.core.signguard import SignGuardReport, run_sign_guard

__all__ = [
    "Assessment",
    "CheckResult",
    "CheckStatus",
    "Coefficient",
    "ContractReport",
    "ContractViolation",
    "DispersionReport",
    "FailureType",
    "Family",
    "Factor",
    "FitResult",
    "GateReport",
    "IndexResult",
    "LadderResult",
    "Mode",
    "RegistryError",
    "Registry",
    "RoadRiskError",
    "Rung",
    "RunLog",
    "RunManifest",
    "Sign",
    "SignGuardReport",
    "SnapReport",
    "TransformError",
    "VIFReport",
    "WeightNotSourced",
    "assess",
    "compute_dispersion",
    "compute_vif",
    "load_registry",
    "prepare_panel",
    "run_sign_guard",
    "walk_ladder",
]
