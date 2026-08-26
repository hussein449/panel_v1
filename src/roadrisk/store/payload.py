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

    return {
        "schema_version": parsed.schema_version,
        "engine_version": parsed.engine_version,
        "fingerprint": parsed.assessment.manifest.fingerprint,
        "mode": parsed.assessment.mode,
        "rung": parsed.assessment.rung,
    }
