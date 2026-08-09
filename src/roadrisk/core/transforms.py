"""Apply the transforms declared in the registry.

Every transform is guarded. A factor declared ``ln`` that receives a zero is a data
problem in the adapter that produced it, and it surfaces here with the factor named
rather than as a silent ``-inf`` propagating into the fit.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from roadrisk.core.errors import TransformError
from roadrisk.core.registry import Factor, Transform

_MAX_EXAMPLES = 5
_CONSTANT_RELATIVE_TOLERANCE = 1e-12


def apply_transform(
    values: pd.Series,
    transform: Transform,
    *,
    factor: str,
) -> pd.Series:
    """Map a raw column onto the scale the model expects.

    Args:
        values: Raw column, as supplied.
        transform: The transform declared for this factor.
        factor: Factor name, used only for error messages.

    Raises:
        TransformError: The values cannot carry the declared transform.
    """
    numeric = pd.to_numeric(values, errors="coerce")

    if numeric.isna().any():
        bad = values.index[numeric.isna()]
        raise TransformError(
            f"factor '{factor}': {len(bad)} null or non-numeric value(s) at row index "
            f"{_examples(bad)}. An adapter must either resolve a value or leave the "
            "whole column absent — partial columns are not supported, because a "
            "silently dropped row changes the exposure denominator."
        )

    if not np.isfinite(numeric).all():
        bad = values.index[~np.isfinite(numeric)]
        raise TransformError(
            f"factor '{factor}': non-finite value(s) at row index {_examples(bad)}. "
            "Unbounded quantities such as curve radius on a tangent must be capped by "
            "the adapter, and the cap recorded."
        )

    numeric = numeric.astype(float)

    if transform is Transform.IDENTITY:
        return numeric

    if transform is Transform.LN:
        if (numeric <= 0).any():
            bad = values.index[numeric <= 0]
            raise TransformError(
                f"factor '{factor}' declares transform 'ln' but {len(bad)} value(s) are "
                f"zero or negative, first at row index {_examples(bad)}. Use 'ln1p' if "
                "zero is a legitimate observation for this quantity."
            )
        return np.log(numeric)

    if transform is Transform.LN1P:
        if (numeric < 0).any():
            bad = values.index[numeric < 0]
            raise TransformError(
                f"factor '{factor}' declares transform 'ln1p' but {len(bad)} value(s) "
                f"are negative, first at row index {_examples(bad)}"
            )
        return np.log1p(numeric)

    if transform is Transform.ZSCORE:
        std = float(numeric.std(ddof=0))
        scale = max(1.0, float(numeric.abs().mean()))
        # Tolerant rather than exact: a genuinely constant column leaves a residual
        # standard deviation around 1e-15 from floating point summation, not zero.
        if not np.isfinite(std) or std <= _CONSTANT_RELATIVE_TOLERANCE * scale:
            raise TransformError(
                f"factor '{factor}' declares transform 'zscore' but the column is "
                "constant — it carries no information and cannot be standardised."
            )
        return (numeric - float(numeric.mean())) / std

    raise TransformError(f"factor '{factor}': unsupported transform '{transform}'")


def build_design(panel: pd.DataFrame, factors: list[Factor]) -> pd.DataFrame:
    """Build the transformed design matrix for a set of factors.

    Columns are named by factor ``name``, not by input ``column``, so that everything
    downstream — coefficients, VIF, the sign guard, the report — speaks in registry
    terms rather than in whatever the client happened to call the column.

    No intercept is added here; the model layer owns that.
    """
    if not factors:
        return pd.DataFrame(index=panel.index)

    data = {
        factor.name: apply_transform(
            panel[factor.column], factor.transform, factor=factor.name
        )
        for factor in factors
    }
    return pd.DataFrame(data, index=panel.index)


def _examples(index: pd.Index) -> str:
    shown = list(index[:_MAX_EXAMPLES])
    suffix = ", ..." if len(index) > _MAX_EXAMPLES else ""
    return f"{shown}{suffix}"


__all__ = ["apply_transform", "build_design"]
