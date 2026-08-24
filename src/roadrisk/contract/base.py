"""The base every payload model inherits, and the one setting that matters.

``extra="forbid"`` is what makes this package a *contract* rather than a description.
A permissive model accepts any payload that happens to contain the fields it knows
about, which means the engine can grow a field, the report can start relying on it, and
nothing ever notices that the two descriptions of the payload have diverged. Forbidding
extras inverts that: a new key in ``as_dict()`` fails the conformance test until it is
declared here, so the contract cannot silently fall behind what it describes.

The cost is real and is the point — adding a field to the engine is now a two-file
change. Step 4.7 is the argument for paying it: ``posterior.coefficients`` is a mapping,
the page had it typed as a list, every row silently fell back to its frequentist
interval under a *credible interval* heading, and it survived three steps of review
because nothing anywhere compared the two descriptions.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Payload(BaseModel):
    """A JSON object in the run payload.

    Frozen because a contract model is a read of something already computed. Nothing
    downstream should be editing a payload in place and re-serialising it: the run
    record is the record.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
