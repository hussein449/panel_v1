"""Reading a run's indexed columns out of its payload.

Shared by every backend, deliberately. The alternative is each implementation lifting
its own columns, which is two chances to lift them differently and no test that would
notice — a Postgres row saying Mode A while its payload says Mode B is the kind of
defect that only surfaces in a list view, months later, in front of a client.

**The columns are derived, never supplied.** No caller passes a mode or a fingerprint;
there is nowhere to pass one. That is what makes them guaranteed to agree with the
payload rather than merely expected to.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from roadrisk.contract import Run as RunPayload
from roadrisk.contract import finite
from roadrisk.store.base import PayloadRejected


def storable(payload: Any) -> Any:
    """The payload as it will actually be stored.

    `build_run` already replaces non-finite floats with null, so for a payload from the
    normal path this changes nothing. It is applied again because a payload assembled by
    hand, or read back from a file written before that was true, has not been through
    it — and `Infinity` is not JSON, so `jsonb` refuses it outright and the insert fails
    with a parser error rather than anything a caller can act on.
    """
    return finite(payload)


def read_run_columns(payload: Any) -> dict[str, Any]:
    """Validate a payload against the contract and lift out what gets indexed.

    Args:
        payload: A run payload, as produced by `roadrisk.report.build_run` or read back
            from a stored `run.json`.

    Raises:
        PayloadRejected: The payload does not conform to `roadrisk.contract`. The
            message names the failing paths, because "invalid payload" is not something
            anyone can act on.

    Returns:
        The indexed columns, ready to splat into a
        :class:`~roadrisk.store.records.Run`.
    """
    if not isinstance(payload, dict):
        raise PayloadRejected(
            f"A run payload must be a JSON object, not {type(payload).__name__}."
        )

    try:
        parsed = RunPayload.model_validate(payload)
    except ValidationError as exc:
        where = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()[:5]
        )
        more = "" if exc.error_count() <= 5 else f" (and {exc.error_count() - 5} more)"
        raise PayloadRejected(
            "This run payload does not match the stored contract, so it is refused "
            f"rather than kept in a shape nothing can read back: {where}{more}"
        ) from exc

    west, south, east, north = _extent(parsed)

    return {
        "schema_version": parsed.schema_version,
        "engine_version": parsed.engine_version,
        "fingerprint": parsed.assessment.manifest.fingerprint,
        "mode": parsed.assessment.mode,
        "rung": parsed.assessment.rung,
        "extent_west": west,
        "extent_south": south,
        "extent_east": east,
        "extent_north": north,
    }


def _extent(
    parsed: RunPayload,
) -> tuple[float | None, float | None, float | None, float | None]:
    """The box the assessed road actually occupies, in degrees.

    **Step 2.9's other half, reached from the opposite direction.** The geometry has been
    persisted since 5.1b — it is inside `payload`, which is how a stored run re-renders
    months later with no refit. What could not be done was *finding* it: every listing
    was by tenant and project, so "which runs cover this place" had no query behind it.
    Four numbers lifted on insert give it one, and they follow the rule every other lifted
    column follows — written from the payload, never supplied by a caller, so a row cannot
    describe a different road than the one it holds.

    Read from the stitched centreline rather than from the corridor *request*: a bounding
    box somebody typed is what was asked for, and this is what was assessed. They are not
    the same box, and the second is the one worth indexing.

    All four are null together, for a run with no geometry — a panel supplied directly has
    rows and no road. Null is not an empty box: it means *this run is not anywhere*, and a
    spatial filter has to miss it rather than match it.
    """
    corridor = parsed.corridor
    if corridor is None:
        return (None, None, None, None)

    points: list[Any] = list(corridor.corridor.geometry)
    if not points:
        # A corridor whose centreline did not survive but whose units did. Rare, and the
        # extent is the same either way, so it is worth four lines rather than discarding
        # the geography of a run that has some.
        points = [
            point for unit in corridor.segmentation.units for point in unit.geometry
        ]
    if not points:
        return (None, None, None, None)

    longitudes = [point[0] for point in points]
    latitudes = [point[1] for point in points]
    return (min(longitudes), min(latitudes), max(longitudes), max(latitudes))
