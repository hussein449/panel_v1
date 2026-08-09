"""Exception hierarchy for the core engine.

The distinction that matters: a :class:`ContractViolation` rejects the job, a failed
gate does not. Gates that fail send the run down the ladder — that is a result, not an
error, and it is returned rather than raised.
"""

from __future__ import annotations


class RoadRiskError(Exception):
    """Base class for every error raised by the core engine."""


class RegistryError(RoadRiskError):
    """The factor registry is malformed, inconsistent, or internally contradictory."""


class ContractViolation(RoadRiskError):
    """The input panel breaks the input contract.

    This is a HARD failure: the job is rejected. It is never downgraded to Mode B,
    because a panel that breaks the contract cannot be scored either.
    """


class TransformError(RoadRiskError):
    """A declared transform cannot be applied to the data supplied."""


class WeightNotSourced(RoadRiskError):
    """Mode B was asked to score using a weight that carries no citation.

    A number the client cannot trace to either their own data or a named reference is
    a liability. The engine refuses rather than printing it.
    """


__all__ = [
    "ContractViolation",
    "RegistryError",
    "RoadRiskError",
    "TransformError",
    "WeightNotSourced",
]
