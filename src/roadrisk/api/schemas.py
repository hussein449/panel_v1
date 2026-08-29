"""What crosses the wire, and what is deliberately reused rather than described again.

**Reused.** :mod:`roadrisk.store.records` already describes a project, a corridor, a job
and a run as frozen Pydantic models that forbid extras, and :mod:`roadrisk.contract`
already describes the payload. Those *are* the response shapes. Writing API-side copies
would be the 5.1a defect with new names — two descriptions of one object, drifting in
silence until a client renders the wrong thing under the right heading.

**Not reused, and each one for a reason:**

* **Create bodies carry no `tenant_id`.** It comes from the header. A body that could
  carry one would let a client file rows under somebody else's tenant, and because
  every model here forbids extras, sending one is a 422 rather than a surprise.
* **`ArtefactOut` replaces `uri` with `href`.** The stored URI is a path on the
  server's disk. A client needs a URL it can fetch, not the layout of our filesystem.
* **`RunSummary` drops the payload.** A run is around 300 kB. A listing of fifty is not
  fifteen megabytes.
* **`JobSpec` is written down at all.** It is what goes into `job.params`, so 5.1d and
  5.2a read it back rather than re-deriving what a submission meant.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from roadrisk.core.models import Estimator
from roadrisk.core.registry import (
    FacilityType,
    Licence,
    Region,
    Severity,
    Sign,
    Tier,
    Transform,
)
from roadrisk.store import ArtefactKind, Run

Name = Annotated[str, Field(min_length=1, max_length=200)]


class Body(BaseModel):
    """A request body. Forbids extras, for the reason in the module docstring."""

    model_config = ConfigDict(extra="forbid")


# -- projects ------------------------------------------------------------------


class ProjectCreate(Body):
    """A body of work — usually one road authority's network, or one study."""

    name: Name
    #: Whole currency units. Null is uncapped, which 5.2b's runner reads before the
    #: call that would breach it.
    spend_cap: float | None = Field(default=None, ge=0.0)


class ProjectPatch(Body):
    """Only the fields actually sent are applied.

    Which is why `spend_cap` being null has to mean *clear it* and an absent
    `spend_cap` has to mean *leave it*. Pydantic distinguishes those through
    ``exclude_unset``; a bag of optional arguments on the store would not, which is why
    :meth:`roadrisk.store.Store.update_project` takes a whole record instead.
    """

    name: Name | None = None
    spend_cap: float | None = Field(default=None, ge=0.0)


# -- corridors -----------------------------------------------------------------


BBox = Annotated[
    tuple[float, float, float, float],
    Field(description="south, west, north, east, in degrees."),
]


class CorridorBody(Body):
    """The parameters that fetch and segment a road — not the resolved geometry.

    Geometry belongs to a run: the OSM extract behind a corridor changes, and two runs
    of the same road a month apart are two different centrelines that must not be
    conflated. What is stable is the request.
    """

    name: Name
    ref: str | None = Field(
        default=None,
        max_length=64,
        description="Road reference as OSM knows it, e.g. 'B9'. Null for a "
        "client-supplied centreline, or when the road is identified by 'osm_name'.",
    )
    osm_name: str | None = Field(
        default=None,
        max_length=200,
        description=(
            "The road's OSM 'name' tag, for a road that carries no reference — most "
            "residential and urban streets. Matched exactly, including case and "
            "punctuation. A name is not unique the way a reference is, so a box "
            "holding two roads of this name is refused as fragmented rather than "
            "welded into one corridor."
        ),
    )
    bbox: BBox | None = None
    unit_length_m: float = Field(default=500.0, gt=0.0, le=100_000.0)

    @model_validator(mode="after")
    def _one_selector_at_most(self) -> CorridorBody:
        """A road is identified one way, or not at all.

        Both set is not a doubly-identified road; it is a row where nothing can say
        which query produced the centreline, and two runs of it a month apart could
        resolve different roads. Migration 0004 refuses it in the database as well —
        this exists so the refusal names the field while the row does not yet exist.
        """
        if self.ref is not None and self.osm_name is not None:
            raise ValueError(
                "give 'ref' or 'osm_name', not both: a road is identified by its "
                "reference or by its name, and a corridor carrying both cannot say "
                "which query produced its centreline."
            )
        return self

    @model_validator(mode="after")
    def _a_selector_needs_somewhere_to_look(self) -> CorridorBody:
        """Overpass answers an unbounded query with the planet, then times out.

        Which surfaces a minute later in a worker as an infrastructure failure, when it
        is really a submission that could never have worked.
        """
        if (self.ref is not None or self.osm_name is not None) and self.bbox is None:
            raise ValueError(
                "a road selected by 'ref' or 'osm_name' needs a 'bbox' to look in. "
                "Without one the query covers the planet and the mirror times out "
                "rather than answering."
            )
        return self

    @model_validator(mode="after")
    def _box_is_the_right_way_up(self) -> CorridorBody:
        """A box the database would accept and no fetch could ever use.

        Migration 0001 already refuses a half-specified box — four columns or none. It
        cannot refuse an inverted or out-of-range one, because a `CHECK` that knew
        north from south would be encoding geography in the schema. So it is refused
        here, at submit, rather than discovered as an empty Overpass result later.
        """
        if self.bbox is None:
            return self
        south, west, north, east = self.bbox
        if not (-90.0 <= south <= 90.0 and -90.0 <= north <= 90.0):
            raise ValueError("latitudes must be between -90 and 90 (south, north).")
        if not (-180.0 <= west <= 180.0 and -180.0 <= east <= 180.0):
            raise ValueError("longitudes must be between -180 and 180 (west, east).")
        if south >= north:
            raise ValueError(f"south ({south}) must be below north ({north}).")
        if west >= east:
            raise ValueError(
                f"west ({west}) must be left of east ({east}). A box crossing the "
                "antimeridian has to be split into two."
            )
        return self


class CorridorCreate(CorridorBody):
    """Created under the project in the path. `project_id` is never in the body."""


class CorridorPatch(Body):
    """See :class:`ProjectPatch`. `project_id` is not editable — see the store."""

    name: Name | None = None
    ref: str | None = Field(default=None, max_length=64)
    osm_name: str | None = Field(default=None, max_length=200)
    bbox: BBox | None = None
    unit_length_m: float | None = Field(default=None, gt=0.0, le=100_000.0)


# -- jobs ----------------------------------------------------------------------


class JobOptions(Body):
    """The assessment's own options — exactly the CLI's, and nothing invented here.

    Everything absent has the same default the command line has, so a job submitted
    with no options at all is the run `roadrisk corridor` would have done.

    What is deliberately **not** here: any way to force a mode, a rung or a term. The
    engine decides those from data adequacy, `assess` exposes no argument for them, and
    a test in `tests/test_engine.py` asserts it never grows one. A caller who could
    overrule the ladder would overrule it.
    """

    facility_type: FacilityType = FacilityType.ANY
    region: Region = Region.GLOBAL
    severity: Severity = Severity.ALL

    estimator: Estimator = Estimator.NB2
    use_registry_priors: bool = False
    use_spatial: bool = False

    shape_factors: list[str] = Field(
        default_factory=list,
        description="Factors to put a rung 3 spline on. Validated against "
        "`factors.yaml` at submit — a name no factor has is a typo, and finding it in "
        "a run log a quarter of an hour later helps nobody.",
    )

    #: Which fetches the pipeline is allowed to make. Named rather than four booleans
    #: so that a fifth source is an added value and not a changed shape.
    #:
    #: `imagery` is that fifth value arriving exactly as the line above intended. It uses
    #: the same free Mapillary token as `mapillary` and is deliberately not folded into
    #: it: `mapillary` counts poles beside the road and fills a factor column, while
    #: `imagery` asks whether a vehicle has ever been *on* the road and produces a
    #: sentence. One control for both would make a reader who wanted the second pay for
    #: the first, and would carry a label describing half of what it did.
    adapters: list[
        Literal["osm", "rasters", "traffic", "mapillary", "imagery"]
    ] = Field(default_factory=list)

    unit_length_m: float | None = Field(default=None, gt=0.0, le=100_000.0)
    tolerance_m: float = Field(default=30.0, gt=0.0, le=1000.0)
    n_periods: int = Field(default=24, ge=1, le=600)


PanelRows = list[dict[str, Any]]
CrashRows = list[dict[str, Any]]

#: What a crash row must carry to be snapped onto a corridor. The same three the CLI's
#: `--crashes` CSV requires, and for the same reason: a coordinate to project onto the
#: centreline and a period to file the result under.
CRASH_COLUMNS = ("latitude", "longitude", "period")


def _check_crash_rows(rows: CrashRows) -> CrashRows:
    """Refuse a crash table at submit, naming what is wrong with it.

    **Why this is here rather than in the pipeline.** A crash table that cannot be
    snapped produces a run with no crashes on it — which is not an error anywhere
    downstream. It is a Mode B ranking, produced confidently, from a corridor whose
    crash data silently went nowhere. That is exactly the failure this project refuses
    to ship, so the table is checked before a job exists and the refusal names the
    column, in keeping with the contract the README sets out for a 422.
    """
    if not rows:
        raise ValueError(
            "'crashes' was given but is empty. Omit it entirely to assess the road "
            "without a crash table — the engine will say so and score Mode B."
        )

    missing = sorted(set(CRASH_COLUMNS) - set(rows[0]))
    if missing:
        raise ValueError(
            f"crash rows are missing column(s): {', '.join(missing)}. Every row needs "
            f"{', '.join(CRASH_COLUMNS)} — a coordinate to put it on the road, and a "
            "period to count it in."
        )

    for index, row in enumerate(rows):
        for column in ("latitude", "longitude"):
            value = row.get(column)
            if not isinstance(value, int | float) or isinstance(value, bool):
                raise ValueError(
                    f"crash row {index} has {column}={value!r}, which is not a number. "
                    "Coordinates are decimal degrees."
                )
        latitude, longitude = row["latitude"], row["longitude"]
        if not -90.0 <= latitude <= 90.0:
            raise ValueError(
                f"crash row {index} has latitude={latitude}, which is not on Earth. "
                "Latitude and longitude may be the wrong way round."
            )
        if not -180.0 <= longitude <= 180.0:
            raise ValueError(
                f"crash row {index} has longitude={longitude}, which is not on Earth."
            )
        if not str(row.get("period", "")).strip():
            raise ValueError(
                f"crash row {index} has an empty period. A crash with no period cannot "
                "be counted in one."
            )
    return rows


class JobSubmission(Body):
    """One request to assess something. Exactly one of `corridor_id`, `panel` or `demo`.

    Three ways in. Two of them are the command line's: `roadrisk corridor` builds a
    panel from geography, `roadrisk assess` judges one you already have, and neither is
    the degraded case. The third is the demonstration, which exists so that this API can
    be tried end to end without a road, a crash extract or a network.
    """

    project_id: UUID
    corridor_id: UUID | None = None
    panel: PanelRows | None = Field(
        default=None,
        description="Rows of a panel you already built, as objects. Validated against "
        "the input contract before the job exists, so a panel that could never be "
        "assessed never becomes a queued job.",
    )
    crashes: CrashRows | None = Field(
        default=None,
        description=(
            "The crash table for this road, as objects with 'latitude', 'longitude' "
            "and 'period' — the CLI's `--crashes` CSV, in JSON. Optional, and the "
            "single most consequential thing you can supply: **without it the engine "
            "has no counts to fit and the run can only be Mode B.** Legal only "
            "alongside 'corridor_id'. Validated here, so a table that could never be "
            "snapped is a 422 naming the column rather than a confident ranking built "
            "from crash data that went nowhere."
        ),
    )
    demo: bool = Field(
        default=False,
        description=(
            "Assess a synthetic 10 km corridor with an invented crash table. Needs no "
            "network and no data. **The resulting report says on its own face that "
            "there is no real road in it** — the flag travels into the payload and the "
            "limitations page reports it as material, so a demonstration cannot be "
            "mistaken for an assessment by whoever you send it to."
        ),
    )
    params: JobOptions = Field(default_factory=JobOptions)

    @property
    def source(self) -> Literal["corridor", "panel", "demo"]:
        if self.demo:
            return "demo"
        return "panel" if self.panel is not None else "corridor"

    @model_validator(mode="after")
    def _exactly_one_source(self) -> JobSubmission:
        chosen = [
            name
            for name, given in (
                ("corridor_id", self.corridor_id is not None),
                ("panel", self.panel is not None),
                ("demo", self.demo),
            )
            if given
        ]
        if len(chosen) != 1:
            raise ValueError(
                "give exactly one of 'corridor_id' (build the panel from geography), "
                "'panel' (assess one you already have) or 'demo': true (a synthetic "
                f"corridor that needs nothing). Got {chosen or 'none of them'}."
            )
        return self

    @model_validator(mode="after")
    def _a_demo_fetches_nothing(self) -> JobSubmission:
        """Adapters over a synthetic corridor would query the sea.

        The demo centreline is invented, so its coordinates are not a road: an OSM
        ribbon query along it returns nothing and a DEM sample returns whatever is at
        those coordinates, which is unrelated to anything in the report. Refused at
        submit rather than producing a corridor whose provenance table is full of
        sources that were asked about somewhere else entirely.
        """
        if self.demo and self.params.adapters:
            raise ValueError(
                "a demo corridor cannot use adapters "
                f"({', '.join(sorted(self.params.adapters))}): its centreline is "
                "invented, so a query along it would be asking real sources about a "
                "road that does not exist."
            )
        return self

    @model_validator(mode="after")
    def _crashes_belong_to_a_corridor(self) -> JobSubmission:
        """Crashes are snapped onto a centreline, so there has to be one.

        A panel already carries `n_crashes` per row — supplying both would be two
        answers to one question, with nothing to say which wins. A demo invents its own
        crash table along an invented road, so a real one has nowhere to land.
        """
        if self.crashes is None:
            return self
        if self.corridor_id is None:
            raise ValueError(
                "'crashes' needs 'corridor_id': a crash table is snapped onto a "
                "centreline, and "
                + (
                    "a demo corridor's centreline is invented, so real crashes have "
                    "no road to land on."
                    if self.demo
                    else "a panel you supply already carries 'n_crashes' per row."
                )
            )
        _check_crash_rows(self.crashes)
        return self


class JobSpec(Body):
    """What is stored in `job.params`, and what 5.1d reads back to execute it.

    Written down as a model rather than left as a loose dictionary because a job has to
    be re-runnable identically — that is what makes the manifest's fingerprint checkable
    against anything. A dictionary nobody has described is a dictionary that grows a key
    somebody forgot to read.
    """

    source: Literal["corridor", "panel", "demo"]
    options: JobOptions
    #: Present only for a panel job. Stored as submitted, not as prepared: `exposure`
    #: and `log_exposure` are derived, and keeping the derivation would freeze a copy of
    #: the contract inside a row.
    panel: PanelRows | None = None
    #: Present only for a corridor job that was given one. Stored as submitted for the
    #: same reason as `panel`: snapping is the pipeline's job, and a row that kept its
    #: result would freeze a copy of the tolerance the run was made with.
    crashes: CrashRows | None = None


# -- runs and artefacts --------------------------------------------------------


class RunSummary(BaseModel):
    """A run without its payload. What a listing is made of.

    Every field is one the store lifted out of the payload on insert, so a summary
    cannot describe a different run than the one it points at.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    tenant_id: UUID
    project_id: UUID
    job_id: UUID | None
    corridor_id: UUID | None
    schema_version: str | None
    engine_version: str
    fingerprint: str
    mode: str
    rung: str
    created_at: datetime | None

    #: Where the assessed road is, in degrees, lifted from the centreline on insert like
    #: everything else here. Null — all four together — on a run with no geometry: a
    #: panel supplied directly has rows and no road.
    extent_west: float | None
    extent_south: float | None
    extent_east: float | None
    extent_north: float | None

    @classmethod
    def of(cls, run: Run) -> RunSummary:
        return cls(**run.model_dump(exclude={"payload"}))


class ArtefactOut(BaseModel):
    """A file belonging to a run, as a client may see it.

    `uri` is not here. It is a path on the server's disk and a client has no use for
    one; `href` is the URL that serves the bytes, and `sha256` is what they should hash
    to when they arrive.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    run_id: UUID
    kind: ArtefactKind
    size_bytes: int
    sha256: str
    created_at: datetime | None
    href: str


# -- registry ------------------------------------------------------------------


class AdapterOut(BaseModel):
    """One way of obtaining a factor, with what it costs and what it obliges."""

    model_config = ConfigDict(extra="forbid")

    name: str
    tier: Tier
    licence: Licence
    #: What the licence actually requires of the client. Two booleans rather than one:
    #: crediting a source in a report and republishing the panel as a dataset are
    #: different acts under different terms.
    credit_required: bool
    share_alike_database: bool
    obligation: str
    notes: str | None = None


class FactorOut(BaseModel):
    """A declared model term, exactly as `factors.yaml` declares it."""

    model_config = ConfigDict(extra="forbid")

    name: str
    label: str
    column: str
    transform: Transform
    expected_sign: Sign
    drop_priority: int
    #: False means the factor carries no cited weight, so it never enters Mode B. It is
    #: not silently weighted zero, and the report names it.
    sourced: bool
    weight_count: int
    missing_behaviour: str
    adapters: list[AdapterOut]
    notes: str | None = None


class TierOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Tier
    meaning: str


class LicenceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Licence
    credit_required: bool
    share_alike_database: bool
    obligation: str


class RegistryOut(BaseModel):
    """The whole registry as served, including what it hashed to.

    `sha256` is the file's, computed by the loader. A client comparing it against the
    one inside a run's manifest can tell whether that run was assessed under the
    registry this API is now serving — which is the only honest way to answer "is this
    still current".
    """

    model_config = ConfigDict(extra="forbid")

    version: str
    sha256: str | None
    #: The file's name, never its path. Where it sits on this server is not a client's
    #: business and is not stable across deployments.
    source: str
    factor_count: int
    sourced_count: int
    tiers: list[TierOut]
    licences: list[LicenceOut]
    factors: list[FactorOut]


# -- meta ----------------------------------------------------------------------


class Health(BaseModel):
    """What this deployment is, said plainly rather than left to be discovered.

    `runner` is null until 5.1d and that is the honest answer: a job posted here today
    is accepted, stored and queued, and nothing will pick it up. Reporting `"ok"` and
    letting a client watch a job sit in `queued` forever would be a working service
    that lies.
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]
    engine_version: str
    schema_version: str
    registry_version: str
    #: What executes jobs, by name — `in-process` for a pool inside this process,
    #: `inline` for one that runs before the request returns. Null means nothing does,
    #: and a job posted here will sit in `queued` for ever.
    runner: str | None
    #: How identity is established. Null means the tenant header is taken at its word —
    #: see 5.4a.
    auth: str | None
    #: False when no artefact root is configured, so downloads are refused.
    artefacts_available: bool


__all__ = [
    "AdapterOut",
    "ArtefactOut",
    "BBox",
    "Body",
    "CorridorBody",
    "CorridorCreate",
    "CorridorPatch",
    "FactorOut",
    "Health",
    "JobOptions",
    "JobSpec",
    "JobSubmission",
    "LicenceOut",
    "PanelRows",
    "ProjectCreate",
    "ProjectPatch",
    "RegistryOut",
    "RunSummary",
    "TierOut",
]
