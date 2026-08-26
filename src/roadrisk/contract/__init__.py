"""Step 5.1a — the JSON contract, as types.

`Assessment.as_dict()` has called itself *"the shape the API and the report template
consume"* since step 1.8. This package is where that shape stops being a docstring and
becomes something a machine checks.

**It is the bottom layer.** Nothing here imports anything else in `roadrisk`, and
everything else may import it: the engine produces payloads that must conform, the
report renders them, the API returns them and the worker stores them. A contract that
depended on any of its consumers would not be a contract.

**Why it is duplication, deliberately.** `as_dict()` decides what travels; this decides
what is *allowed* to travel; and `tests/test_contract.py` fails when the two disagree.
One description would be less code and no guarantee. The case for the guarantee is step
4.7: `posterior.coefficients` is a mapping, the page had it typed as a list, every
coefficient silently fell back to its frequentist interval under a *credible interval*
heading, and it survived three steps of review because nothing compared the two
descriptions of the same object.

**And it is the source of the TypeScript.** `web/src/types.ts` was hand-maintained,
which was reasonable while one renderer read one file and becomes two descriptions in
two languages the moment there is an API. It is generated from these models now, by
`tools/generate_types.py`, and a test asserts the committed file is what the generator
produces.
"""

from __future__ import annotations

from roadrisk.contract.assessment import (
    ApproximationReport,
    Assessment,
    Blackspot,
    Calibration,
    Check,
    Coefficient,
    Concern,
    ConvergenceReport,
    CrashMix,
    Cure,
    Evidence,
    EvidenceFactor,
    EvidenceInterval,
    FactorCorrelation,
    FactorSummary,
    Fit,
    Index,
    IndexRankingRow,
    IndexTerm,
    LeaveOneOut,
    LogRecord,
    Manifest,
    MissingFactor,
    PairwiseFit,
    PanelSummary,
    Posterior,
    PosteriorSummary,
    Prediction,
    Ranking,
    Receipts,
    Reference,
    ResampleReport,
    RunContext,
    Shape,
    SignGuard,
    SignGuardFinding,
    Spatial,
    SplineCurve,
    UnitRisk,
    Validation,
    WeightAgreement,
)
from roadrisk.contract.base import Payload
from roadrisk.contract.corridor import (
    AdapterRun,
    AdapterSkip,
    Attribution,
    CacheAge,
    CacheReport,
    ConfidenceRow,
    Corridor,
    CorridorGeometry,
    Disagreement,
    Obligation,
    PanelShape,
    ProvenanceRow,
    Segmentation,
    SegmentUnit,
    SnapReport,
    Vertex,
)
from roadrisk.contract.jsonsafe import finite, non_finite_paths
from roadrisk.contract.run import SCHEMA_VERSION, Limitation, Run

__all__ = [
    "SCHEMA_VERSION",
    "AdapterRun",
    "AdapterSkip",
    "ApproximationReport",
    "Assessment",
    "Attribution",
    "Blackspot",
    "CacheAge",
    "CacheReport",
    "Calibration",
    "Check",
    "Coefficient",
    "Concern",
    "ConfidenceRow",
    "ConvergenceReport",
    "Corridor",
    "CorridorGeometry",
    "CrashMix",
    "Cure",
    "Disagreement",
    "Evidence",
    "EvidenceFactor",
    "EvidenceInterval",
    "FactorCorrelation",
    "FactorSummary",
    "Fit",
    "Index",
    "IndexRankingRow",
    "IndexTerm",
    "LeaveOneOut",
    "Limitation",
    "LogRecord",
    "Manifest",
    "MissingFactor",
    "Obligation",
    "PairwiseFit",
    "PanelShape",
    "PanelSummary",
    "Payload",
    "Posterior",
    "PosteriorSummary",
    "Prediction",
    "ProvenanceRow",
    "Ranking",
    "Receipts",
    "Reference",
    "ResampleReport",
    "Run",
    "RunContext",
    "SegmentUnit",
    "Segmentation",
    "Shape",
    "SignGuard",
    "SignGuardFinding",
    "SnapReport",
    "Spatial",
    "SplineCurve",
    "UnitRisk",
    "Validation",
    "Vertex",
    "WeightAgreement",
    "finite",
    "non_finite_paths",
]
