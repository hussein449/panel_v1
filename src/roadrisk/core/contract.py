"""The input contract.

Inherited from the M51 panel unchanged, because it works and is already validated in
code. Six required columns; everything else in the registry is optional and each
absent column drops exactly one term.

Exposure is ``length_km * duration_hours``, and ``ln(exposure)`` enters the model as an
offset — not as a coefficient. It is structural. The ladder may never drop it.

Failures here are HARD: the job is rejected. They are not downgraded to Mode B, because
a panel that breaks the contract cannot be ranked either.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from roadrisk.core.errors import ContractViolation

UNIT_COLUMN = "unit_id"
PERIOD_COLUMN = "period"
TIME_SLOT_COLUMN = "time_slot"
CRASH_COLUMN = "n_crashes"
LENGTH_COLUMN = "length_km"
DURATION_COLUMN = "duration_hours"

EXPOSURE_COLUMN = "exposure"
LOG_EXPOSURE_COLUMN = "log_exposure"

KEY_COLUMNS: tuple[str, ...] = (UNIT_COLUMN, PERIOD_COLUMN, TIME_SLOT_COLUMN)
POSITIVE_COLUMNS: tuple[str, ...] = (LENGTH_COLUMN, DURATION_COLUMN)
REQUIRED_COLUMNS: tuple[str, ...] = (*KEY_COLUMNS, CRASH_COLUMN, *POSITIVE_COLUMNS)

RESERVED_COLUMNS: tuple[str, ...] = (EXPOSURE_COLUMN, LOG_EXPOSURE_COLUMN)

_MAX_EXAMPLES = 5


@dataclass(frozen=True)
class ContractReport:
    """What the panel actually contains, once it has been accepted."""

    n_rows: int
    n_units: int
    n_periods: int
    n_time_slots: int
    total_crashes: int
    zero_crash_rows: int
    exposure_total: float
    optional_columns: list[str] = field(default_factory=list)

    @property
    def zero_crash_share(self) -> float:
        return self.zero_crash_rows / self.n_rows if self.n_rows else 0.0

    @property
    def crash_rows(self) -> int:
        return self.n_rows - self.zero_crash_rows


def prepare_panel(panel: pd.DataFrame) -> tuple[pd.DataFrame, ContractReport]:
    """Validate a panel against the contract and return it ready to model.

    The returned frame is a copy with ``n_crashes`` cast to integer and the derived
    ``exposure`` / ``log_exposure`` columns added. The caller's frame is untouched.

    Raises:
        ContractViolation: Any HARD contract failure. The job is rejected.
    """
    _require_non_empty(panel)
    _require_columns(panel)
    _reject_reserved_columns(panel)

    prepared = panel.copy()
    _validate_keys(prepared)
    _validate_crashes(prepared)
    _validate_positive(prepared)
    _reject_duplicate_keys(prepared)

    prepared[CRASH_COLUMN] = prepared[CRASH_COLUMN].astype("int64")
    prepared[EXPOSURE_COLUMN] = (
        prepared[LENGTH_COLUMN].astype(float) * prepared[DURATION_COLUMN].astype(float)
    )

    exposure = prepared[EXPOSURE_COLUMN]
    if not np.isfinite(exposure).all() or (exposure <= 0).any():
        raise ContractViolation(
            "derived exposure (length_km * duration_hours) must be strictly positive and "
            "finite on every row. Check for overflow or extreme values in either column."
        )
    prepared[LOG_EXPOSURE_COLUMN] = np.log(exposure)

    return prepared, _summarise(prepared)


def _summarise(panel: pd.DataFrame) -> ContractReport:
    optional = [
        c
        for c in panel.columns
        if c not in REQUIRED_COLUMNS and c not in RESERVED_COLUMNS
    ]
    return ContractReport(
        n_rows=int(len(panel)),
        n_units=int(panel[UNIT_COLUMN].nunique()),
        n_periods=int(panel[PERIOD_COLUMN].nunique()),
        n_time_slots=int(panel[TIME_SLOT_COLUMN].nunique()),
        total_crashes=int(panel[CRASH_COLUMN].sum()),
        zero_crash_rows=int((panel[CRASH_COLUMN] == 0).sum()),
        exposure_total=float(panel[EXPOSURE_COLUMN].sum()),
        optional_columns=sorted(optional),
    )


# ---- individual checks -------------------------------------------------------


def _require_non_empty(panel: pd.DataFrame) -> None:
    if not isinstance(panel, pd.DataFrame):
        raise ContractViolation(
            f"panel must be a pandas DataFrame, got {type(panel).__name__}"
        )
    if len(panel) == 0:
        raise ContractViolation("panel is empty — there is nothing to assess")


def _require_columns(panel: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in panel.columns]
    if missing:
        raise ContractViolation(
            "panel is missing required column(s): "
            + ", ".join(missing)
            + f". Required: {', '.join(REQUIRED_COLUMNS)}."
        )


def _reject_reserved_columns(panel: pd.DataFrame) -> None:
    clashing = [c for c in RESERVED_COLUMNS if c in panel.columns]
    if clashing:
        raise ContractViolation(
            "panel supplies reserved column(s) the engine derives itself: "
            + ", ".join(clashing)
            + ". Rename or remove them so the offset is unambiguous."
        )


def _validate_keys(panel: pd.DataFrame) -> None:
    for column in KEY_COLUMNS:
        null_rows = panel.index[panel[column].isna()]
        if len(null_rows):
            raise ContractViolation(
                f"'{column}' has {len(null_rows)} null value(s); identifiers must be "
                f"complete. First offending row index: {_examples(null_rows)}"
            )


def _validate_crashes(panel: pd.DataFrame) -> None:
    crashes = panel[CRASH_COLUMN]

    if crashes.isna().any():
        raise ContractViolation(
            f"'{CRASH_COLUMN}' has {int(crashes.isna().sum())} null value(s). A missing "
            "crash count is not the same as zero — supply 0 explicitly where a segment "
            "genuinely had no crashes."
        )

    numeric = pd.to_numeric(crashes, errors="coerce")
    if numeric.isna().any():
        bad = panel.index[numeric.isna()]
        raise ContractViolation(
            f"'{CRASH_COLUMN}' contains non-numeric value(s) at row index "
            f"{_examples(bad)}"
        )

    if (numeric < 0).any():
        bad = panel.index[numeric < 0]
        raise ContractViolation(
            f"'{CRASH_COLUMN}' contains negative value(s) at row index {_examples(bad)}"
        )

    if not np.allclose(numeric, numeric.round()):
        bad = panel.index[~np.isclose(numeric, numeric.round())]
        raise ContractViolation(
            f"'{CRASH_COLUMN}' must be whole counts; fractional value(s) at row index "
            f"{_examples(bad)}. A count model cannot consume a rate — supply counts and "
            "let the exposure offset do the normalising."
        )

    panel[CRASH_COLUMN] = numeric.round()


def _validate_positive(panel: pd.DataFrame) -> None:
    for column in POSITIVE_COLUMNS:
        numeric = pd.to_numeric(panel[column], errors="coerce")

        if numeric.isna().any():
            bad = panel.index[numeric.isna()]
            raise ContractViolation(
                f"'{column}' has {len(bad)} null or non-numeric value(s) at row index "
                f"{_examples(bad)}. Exposure cannot be derived with gaps."
            )

        if not np.isfinite(numeric).all():
            bad = panel.index[~np.isfinite(numeric)]
            raise ContractViolation(
                f"'{column}' contains non-finite value(s) at row index {_examples(bad)}"
            )

        if (numeric <= 0).any():
            bad = panel.index[numeric <= 0]
            raise ContractViolation(
                f"'{column}' must be strictly positive on every row; "
                f"{len(bad)} row(s) are zero or negative, first at index "
                f"{_examples(bad)}. Exposure of zero makes ln(exposure) undefined."
            )

        panel[column] = numeric.astype(float)


def _reject_duplicate_keys(panel: pd.DataFrame) -> None:
    duplicated = panel.duplicated(subset=list(KEY_COLUMNS), keep=False)
    if duplicated.any():
        n = int(duplicated.sum())
        examples = (
            panel.loc[duplicated, list(KEY_COLUMNS)]
            .drop_duplicates()
            .head(_MAX_EXAMPLES)
            .to_dict("records")
        )
        raise ContractViolation(
            f"{n} row(s) share a (unit_id, period, time_slot) key. A panel cell must be "
            f"unique — duplicates double-count exposure and inflate significance. "
            f"Examples: {examples}"
        )


def _examples(index: pd.Index) -> str:
    shown = list(index[:_MAX_EXAMPLES])
    suffix = ", ..." if len(index) > _MAX_EXAMPLES else ""
    return f"{shown}{suffix}"


__all__ = [
    "CRASH_COLUMN",
    "DURATION_COLUMN",
    "EXPOSURE_COLUMN",
    "KEY_COLUMNS",
    "LENGTH_COLUMN",
    "LOG_EXPOSURE_COLUMN",
    "PERIOD_COLUMN",
    "REQUIRED_COLUMNS",
    "RESERVED_COLUMNS",
    "TIME_SLOT_COLUMN",
    "UNIT_COLUMN",
    "ContractReport",
    "prepare_panel",
]
