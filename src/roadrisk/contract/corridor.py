"""The geography half of the payload — `CorridorPanel.as_dict()`, as types.

Present only when the panel came from geography. A panel handed straight to the engine
has none, and the report renders without the map, the provenance and the licensing
rather than inventing them.

Geometry travels in WGS84 as `(longitude, latitude)` — GeoJSON's order — because the
corridor map is part of the report rather than a separate product, and a consumer that
has to reproject is a consumer that will get it wrong.
"""

from __future__ import annotations

from roadrisk.contract.base import Payload

#: One WGS84 vertex, `(longitude, latitude)`. Six decimal places is about 0.1 m at the
#: equator — finer than any centreline this tool consumes, and it keeps a 200-unit
#: corridor's geometry from dominating the payload it travels in.
Vertex = tuple[float, float]


class CorridorGeometry(Payload):
    """The stitched centreline, and what was wrong with it.

    `self_intersecting` is not cosmetic: a corridor that crosses itself cannot be
    linearly referenced unambiguously, because one point on the ground has two
    chainages.
    """

    name: str
    length_m: float
    length_km: float
    epsg: int
    self_intersecting: bool
    warnings: list[str]
    geometry: list[Vertex]


class SegmentUnit(Payload):
    """One segmentation unit, with its chainage extent and its own geometry."""

    unit_id: str
    index: int
    start_m: float
    end_m: float
    length_m: float
    midpoint_m: float
    geometry: list[Vertex]


class Segmentation(Payload):
    """The units the corridor was cut into.

    Chainage is continuous and exhaustive: no gaps, no overlaps, and the unit lengths
    sum to the corridor.
    """

    n_units: int
    target_length_m: float
    total_length_km: float
    units: list[SegmentUnit]


class PanelShape(Payload):
    """The panel the geometry produced, before the engine saw it."""

    rows: int
    units: int
    total_crashes: int
    zero_crash_rows: int
    factor_columns: list[str]


class SnapReport(Payload):
    """Where the supplied crashes went.

    Every drop is counted with a reason. This is what activates gate check 6 — a
    corridor most of whose crashes did not land on it is not a corridor this tool can
    speak about.
    """

    n_supplied: int
    n_snapped: int
    n_dropped: int
    snap_rate: float
    dropped_reasons: dict[str, int]


class AdapterSkip(Payload):
    """A factor an adapter was asked for and declined to produce, and why.

    A missing tag is not a zero. Reading an absent `lit` tag as *unlit* would
    manufacture a lighting effect out of mapper attention, pointing exactly the way the
    registry expects it to.
    """

    factor: str
    adapter: str
    reason: str


class AdapterRun(Payload):
    """What one adapter resolved and what it refused."""

    name: str
    resolved: list[str]
    skipped: list[AdapterSkip]
    notes: list[str]


class ProvenanceRow(Payload):
    """One factor's winning source, and how far it reaches.

    Tier and licence travel from the **registry**, not from the module that produced the
    value: an adapter cannot promote itself to Tier A or invent a licence, because it
    never gets to state either.
    """

    factor: str
    column: str
    adapter: str
    tier: str
    licence: str
    coverage: float
    confidence_high: float
    confidence_low: float
    contested_by: str
    agreement: float | None
    source: str


class ConfidenceRow(Payload):
    """One factor on one unit, with a one-word reason for its tier.

    `carried` is imputed from a neighbour · `contradicted` means a second source
    materially disagrees here · `thin_coverage` rests on under half the unit ·
    `inferred` was derived by us rather than stated by anyone · `measured` is measured.
    """

    unit_id: str
    factor: str
    column: str
    adapter: str
    tier: str
    value: float | None
    confidence: str
    reason: str


class Disagreement(Payload):
    """Two sources that both measured a factor and did not match.

    Asymmetric evidence, and the confidence tier treats it that way: agreement is weak,
    because open datasets copy from each other and agreement can be an echo.
    Disagreement is strong evidence that one of the two is wrong, so it pulls the units
    it names to low confidence, and nothing here can say which source is at fault.
    """

    factor: str
    column: str
    chosen: str
    challenger: str
    n_compared: int
    n_agreeing: int
    score: float | None
    mean_absolute_difference: float | None
    max_absolute_difference: float | None
    correlation: float | None
    disagreeing_units: list[str]
    note: str


class Obligation(Payload):
    """What one licence requires of whoever received this report.

    `share_alike_database` is the one that changes with delivery: crediting a source in
    a report is one obligation, redistributing a derived database is another, and they
    are kept apart because only the second one is contagious.
    """

    licence: str
    credit_required: bool
    share_alike_database: bool
    note: str
    factors: list[str]
    adapters: list[str]
    credits: list[str]
    recognised: bool


class Attribution(Payload):
    """What the client owes the people whose data this used.

    `unrecognised` is not empty-by-default optimism — a licence this collector does not
    know how to classify is listed rather than assumed permissive.
    """

    credit_required: bool
    share_alike_database: bool
    credit_lines: list[str]
    database_warning: str | None
    unrecognised: list[str]
    obligations: list[Obligation]


class CacheAge(Payload):
    """One source, and how old the answer served for it was."""

    source: str
    age_days: float
    fetched_on: str


class CacheReport(Payload):
    """What the cache served, and how stale it was.

    A cache must never make a run look fresher than it is. Every hit is counted, the age
    of the oldest thing used goes into the run's warnings, and past a fortnight the note
    stops being a date and becomes an instruction to clear the cache.
    """

    used: bool
    hits: int
    misses: int
    oldest_days: float
    notes: list[str]
    ages: list[CacheAge]


class Corridor(Payload):
    """The geography half of a run."""

    corridor: CorridorGeometry
    segmentation: Segmentation
    panel: PanelShape
    snap: SnapReport | None
    adapters: list[AdapterRun]
    provenance: list[ProvenanceRow]
    confidence: list[ConfidenceRow]
    contested: list[str]
    disagreements: list[Disagreement]
    attribution: Attribution
    cache: CacheReport
    fusion_notes: list[str]
    warnings: list[str]
    #: The centreline, the crashes, or both were invented rather than measured.
    #:
    #: Optional rather than required, because runs stored before step 5.1d do not carry
    #: it at all — and an absent flag means the run predates the question, not that the
    #: answer is no. `collect_limitations` says only what it knows.
    synthetic: bool | None = None
