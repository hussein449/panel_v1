"""The envelope — what a whole run looks like on the wire and on disk.

This is what `roadrisk.report.build_run` assembles, what the report page is handed, what
the API returns and what 5.1b stores. One shape, four consumers, and the conformance
test is what keeps it one shape.
"""

from __future__ import annotations

from roadrisk.contract.assessment import Assessment
from roadrisk.contract.base import Payload
from roadrisk.contract.corridor import Corridor

#: The payload's own version, carried on every run.
#:
#: It is not the engine version and does not move with it. It moves when the *shape*
#: changes, so that a consumer reading a run written months ago can tell whether it
#: still knows how to read it — which is the whole basis on which 5.1b promises that a
#: stored run re-renders without a refit.
#:
#: Bump the minor for an additive change, the major for one that removes or retypes a
#: field. Nothing enforces that; it is a promise to the people downstream.
SCHEMA_VERSION = "1.0"


class Limitation(Payload):
    """One thing this assessment cannot tell you, and why.

    Assembled from what the run actually did — never written into the layout, so it
    cannot go stale and cannot be quietly edited out. Removing it is a code change with
    a failing test attached.
    """

    code: str
    #: `material` changes what you may conclude · `caveat` qualifies it · `context`
    #: informs. Severity is about what the limitation costs the reader, not about how
    #: bad it sounds.
    severity: str
    title: str
    detail: str


class Run(Payload):
    """A complete run: the engine's half, the geography's half when there is one.

    `corridor` is absent for a panel assessed directly. That is not a degraded run — the
    engine's whole shape is that it judges a panel, and where the panel came from is a
    separate question.
    """

    assessment: Assessment
    corridor: Corridor | None
    limitations: list[Limitation]
    generated_at: str
    engine_version: str
    #: Absent on runs written before this field existed, which is why it is optional
    #: rather than required. A run with no `schema_version` is a 1.0 run.
    schema_version: str | None = None
