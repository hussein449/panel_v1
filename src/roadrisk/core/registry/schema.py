"""Declarative factor registry.

The generalisation the product rests on: *a factor is a declaration, not code*. Adding
"pavement friction" or "lighting" must never require touching the engine. The engine
reads this registry and builds the model specification from it.

Both modes read the same registry, which is what makes them comparable — Mode B applies
``default_weight``, Mode A estimates a coefficient for the same transformed column.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Transform(StrEnum):
    """How a raw column is mapped before it enters the model."""

    IDENTITY = "identity"
    LN = "ln"
    LN1P = "ln1p"
    ZSCORE = "zscore"


class Sign(StrEnum):
    """The direction a factor is expected to push risk. The guard rail."""

    POSITIVE = "+"
    NEGATIVE = "-"

    @property
    def as_int(self) -> int:
        return 1 if self is Sign.POSITIVE else -1


class Tier(StrEnum):
    """Who pays to obtain the value.

    A — open, global, scriptable, free.
    B — open, but needs vision models or graph compute.
    C — free-tier APIs, licence-limited, opt-in per project.
    D — cannot be derived; the client must measure and supply it.
    """

    A = "A"
    B = "B"
    C = "C"
    D = "D"


class Licence(StrEnum):
    """Licence attached to a value, carried through to the report.

    ODbL and CC-BY-SA both impose share-alike on a redistributed derived *database*.
    The report is fine with attribution; the dataset is not. Hence this travels with
    every value rather than being assumed per project.

    ``CC-BY-4.0`` is attribution without share-alike — a materially lighter obligation
    than the two above and a materially heavier one than public domain. It is separate
    because collapsing it into either would misstate what the client must do.
    """

    ODBL = "ODbL"
    CC_BY_SA = "CC-BY-SA"
    CC_BY = "CC-BY-4.0"
    PUBLIC_DOMAIN = "public-domain"
    PROPRIETARY = "proprietary"
    CLIENT = "client"


class WeightFamily(StrEnum):
    """Which body of evidence a weight comes from.

    Preference order for selection is declared in ``roadrisk.core.weights`` — iRAP
    first, because it is global and cross-sectional by construction, which is what
    Mode B actually does.
    """

    IRAP = "irap"
    HSM = "hsm"
    ELVIK = "elvik"


class FacilityType(StrEnum):
    """The road type a weight was estimated on, or that a corridor is.

    ``ANY`` on a weight means the source does not restrict by facility. ``ANY`` on a
    run means the corridor type was not declared, in which case only unrestricted
    weights are admissible — the engine will not guess.
    """

    RURAL_TWO_LANE = "rural_two_lane"
    RURAL_MULTILANE = "rural_multilane"
    URBAN_ARTERIAL = "urban_arterial"
    ANY = "any"


class Region(StrEnum):
    """Where a weight was estimated, or where a corridor is.

    Region granularity, not country, because published weights are estimated on
    regional or national datasets and never on "Cyprus" specifically. A Cyprus
    corridor declares ``europe`` and gets European evidence where it exists, global
    evidence otherwise, and North American evidence only as a last resort — with the
    reach reported.

    Stage 2 will resolve this from the corridor's admin boundary automatically; the
    GADM and OSM-relation adapters are already declared for that.
    """

    NORTH_AMERICA = "north_america"
    EUROPE = "europe"
    AUSTRALASIA = "australasia"
    ASIA = "asia"
    AFRICA = "africa"
    MIDDLE_EAST = "middle_east"
    LATIN_AMERICA = "latin_america"
    GLOBAL = "global"


class Severity(StrEnum):
    """Which crashes a weight predicts.

    This is not decoration. The Elvik Power Model exponent is 1.6 for injury crashes
    and 4.1 for fatal ones — applying the wrong one is a factor-of-two error, and
    before this existed the registry silently assumed injury.
    """

    ALL = "all"
    INJURY = "injury"
    FSI = "fsi"
    FATAL = "fatal"


class CrashScope(StrEnum):
    """Which crash types a weight covers.

    HSM CMFs are stated for *total* segment crashes. iRAP risk factors are stated per
    crash type — its curvature factor covers run-off and head-on only, and its street
    lighting factor covers intersection crashes only.

    Scope does two jobs. It stops the engine scoring a like-for-like agreement between
    weights measuring different quantities, and it decides which crash-type bucket a
    weight enters when Mode B decomposes the score
    (see :mod:`roadrisk.core.crashmix`).

    ``TOTAL`` is a marker, not a type: a total-scope weight enters *every* bucket.
    The remaining four partition all crashes exactly once, so shares over them sum
    to one and nothing is double-counted or lost.
    """

    TOTAL = "total"
    RUN_OFF_HEAD_ON = "run_off_head_on"
    INTERSECTION = "intersection"
    PEDESTRIAN = "pedestrian"
    OTHER = "other"


class Weight(BaseModel):
    """One published weight for one factor, with the context it is valid in.

    A weight used to be a bare number plus a citation. That was the root cause of
    every caveat in the first sourcing pass: nothing recorded the facility type, the
    region, the severity or the crash scope a number was estimated for, so the engine
    applied US rural two-lane injury-crash coefficients to any corridor anywhere and
    said nothing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: float
    source: str = Field(min_length=1, description="Citation. Never optional.")
    family: WeightFamily

    facility_type: FacilityType = FacilityType.ANY
    region: Region = Region.GLOBAL
    severity: Severity = Severity.ALL
    scope: CrashScope = CrashScope.TOTAL

    fit_r2: float | None = Field(
        default=None,
        description="Linearisation quality where the weight was fitted; None if exact.",
    )
    assumes: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "Run conditions this weight was derived under, checked against the actual "
            "run. e.g. {'segment_length_km': 0.5} or {'reference_aadt': 10000}."
        ),
    )
    caveat: str | None = Field(
        default=None,
        description=(
            "A limitation intrinsic to this weight, true on every run regardless of "
            "context. Always surfaced as a concern — this is how a known-imperfect "
            "weight stays usable without becoming quietly trusted."
        ),
    )
    notes: str | None = None

    @property
    def sign(self) -> int:
        if self.value > 0:
            return 1
        return -1 if self.value < 0 else 0

    @property
    def is_exact(self) -> bool:
        return self.fit_r2 is None


class Adapter(BaseModel):
    """One way of obtaining a factor.

    Adapters are ordered within a factor: the first that resolves wins. Client-supplied
    data is simply the highest-priority adapter — same code path, no special case.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    tier: Tier
    licence: Licence
    notes: str | None = None


class Factor(BaseModel):
    """A single declared model term."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1)
    column: str = Field(min_length=1)
    transform: Transform
    expected_sign: Sign
    missing_behaviour: str = Field(min_length=1)
    adapters: list[Adapter] = Field(min_length=1)

    drop_priority: int = Field(
        description="Descent order when the ladder must shed terms. Lower is dropped first."
    )
    weights: list[Weight] = Field(
        default_factory=list,
        description=(
            "Published weights for this factor, each carrying the context it is valid "
            "in. Empty means uncited, and an uncited factor never enters Mode B."
        ),
    )
    notes: str | None = None

    @property
    def is_sourced(self) -> bool:
        """True when this factor carries at least one cited weight."""
        return bool(self.weights)

    def weights_from(self, family: WeightFamily) -> list[Weight]:
        return [w for w in self.weights if w.family is family]

    @model_validator(mode="after")
    def _weights_agree_with_expected_sign(self) -> Factor:
        """A weight contradicting its own declared sign is a registry bug, not a finding.

        This runs per weight, so one bad source cannot slip in behind a good one.
        """
        for weight in self.weights:
            if weight.sign == 0 or weight.sign == self.expected_sign.as_int:
                continue
            raise ValueError(
                f"factor '{self.name}' declares expected_sign "
                f"'{self.expected_sign.value}' but the weight from "
                f"{weight.family.value} is {weight.value}. Fix one of them — the "
                "registry must not ship a contradiction with itself."
            )
        return self

    @model_validator(mode="after")
    def _weights_are_distinguishable(self) -> Factor:
        """Two weights matching the same context would make selection arbitrary."""
        seen: set[tuple[str, str, str, str]] = set()
        for weight in self.weights:
            key = (
                weight.family.value,
                weight.facility_type.value,
                weight.region.value,
                weight.severity.value,
            )
            if key in seen:
                raise ValueError(
                    f"factor '{self.name}' has two weights with identical "
                    f"family/facility/region/severity {key}. Selection would be "
                    "arbitrary — differentiate them or remove one."
                )
            seen.add(key)
        return self


class Registry(BaseModel):
    """The complete set of declared factors, plus provenance of the file it came from."""

    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1)
    factors: list[Factor] = Field(min_length=1)

    # Populated by the loader, not by the YAML.
    source_path: str | None = None
    sha256: str | None = None

    @field_validator("factors")
    @classmethod
    def _unique_names_and_columns(cls, factors: list[Factor]) -> list[Factor]:
        for attr in ("name", "column"):
            seen: dict[str, int] = {}
            for f in factors:
                value = getattr(f, attr)
                seen[value] = seen.get(value, 0) + 1
            duplicates = sorted(v for v, n in seen.items() if n > 1)
            if duplicates:
                raise ValueError(f"duplicate factor {attr}(s): {', '.join(duplicates)}")
        return factors

    @field_validator("factors")
    @classmethod
    def _unique_drop_priority(cls, factors: list[Factor]) -> list[Factor]:
        """Descent must be deterministic — ties would make it arbitrary."""
        priorities = [f.drop_priority for f in factors]
        if len(set(priorities)) != len(priorities):
            clashing = sorted({p for p in priorities if priorities.count(p) > 1})
            raise ValueError(
                f"drop_priority must be unique so descent is deterministic; "
                f"repeated value(s): {clashing}"
            )
        return factors

    # ---- lookup -------------------------------------------------------------

    def by_name(self, name: str) -> Factor:
        for f in self.factors:
            if f.name == name:
                return f
        raise KeyError(f"no factor named '{name}' in registry {self.version}")

    @property
    def names(self) -> list[str]:
        return [f.name for f in self.factors]

    @property
    def columns(self) -> list[str]:
        return [f.column for f in self.factors]

    def available(self, present_columns: object) -> list[Factor]:
        """Factors whose input column is present in the supplied panel.

        Returned in descent order, most-droppable first, so callers never have to
        re-sort and accidentally introduce a different order.
        """
        columns = set(present_columns)  # type: ignore[arg-type]
        return self.in_drop_order([f for f in self.factors if f.column in columns])

    def missing(self, present_columns: object) -> list[Factor]:
        """Factors whose column is absent. Each one drops exactly one term."""
        columns = set(present_columns)  # type: ignore[arg-type]
        return self.in_drop_order([f for f in self.factors if f.column not in columns])

    @staticmethod
    def in_drop_order(factors: list[Factor]) -> list[Factor]:
        """Least important first — the order the ladder sheds terms in."""
        return sorted(factors, key=lambda f: f.drop_priority)

    @staticmethod
    def in_keep_order(factors: list[Factor]) -> list[Factor]:
        """Most important first — the order the ladder retains terms in."""
        return sorted(factors, key=lambda f: f.drop_priority, reverse=True)

    def unsourced(self) -> list[Factor]:
        """Factors Mode B cannot legitimately use."""
        return [f for f in self.factors if not f.is_sourced]


__all__ = [
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
]
