"""Command-line interface.

The CLI is the first surface where the product's rules become visible: the mode banner
is unmissable, the refusal receipt explains exactly what data would unlock Mode A, and
a sign contradiction is impossible to scroll past. The web panel later renders the same
information — this is where the shape of it gets decided.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import pandas as pd
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from roadrisk import __version__
from roadrisk.core.engine import Assessment, assess
from roadrisk.core.errors import RoadRiskError
from roadrisk.core.gates import CheckStatus
from roadrisk.core.ladder import Mode
from roadrisk.core.registry import Registry, load_registry

app = typer.Typer(
    add_completion=False,
    help="Modular road risk assessment panel.",
    rich_markup_mode="rich",
)
console = Console()

EXIT_REJECTED = 2

_STATUS_STYLE = {
    CheckStatus.PASSED: "green",
    CheckStatus.FAILED: "red",
    CheckStatus.SKIPPED: "yellow",
}


@app.command("assess")
def assess_panel(
    panel_path: Annotated[
        Path, typer.Argument(metavar="PANEL", help="Panel CSV satisfying the input contract.")
    ],
    registry_path: Annotated[
        Path | None,
        typer.Option("--registry", "-r", help="Factor registry YAML. Defaults to the shipped one."),
    ] = None,
    out_dir: Annotated[
        Path | None,
        typer.Option("--out", "-o", help="Directory to write the run record into."),
    ] = None,
    as_json: Annotated[
        bool, typer.Option("--json", help="Print the assessment as JSON and nothing else.")
    ] = False,
) -> None:
    """Assess a panel. The engine picks the mode; there is no override."""
    try:
        panel = pd.read_csv(panel_path)
    except OSError as exc:
        console.print(f"[red]Cannot read {panel_path}: {exc}[/red]")
        raise typer.Exit(EXIT_REJECTED) from exc

    registry = _load(registry_path)

    try:
        assessment = assess(panel, registry=registry)
    except RoadRiskError as exc:
        _print_rejection(exc)
        raise typer.Exit(EXIT_REJECTED) from exc

    if as_json:
        console.print_json(json.dumps(assessment.as_dict(), default=str))
    else:
        _render(assessment)

    if out_dir is not None:
        _write_run(assessment, out_dir)
        if not as_json:
            console.print(f"\n[dim]Run record written to {out_dir}[/dim]")


@app.command()
def registry(
    registry_path: Annotated[
        Path | None, typer.Option("--registry", "-r", help="Factor registry YAML.")
    ] = None,
) -> None:
    """Show the declared factors, their expected signs and their weight status."""
    active = _load(registry_path)

    table = Table(title=f"Factor registry v{active.version}", header_style="bold")
    table.add_column("Factor")
    table.add_column("Column")
    table.add_column("Transform")
    table.add_column("Sign", justify="center")
    table.add_column("Drop", justify="right")
    table.add_column("Weight")
    table.add_column("Tiers", justify="center")
    table.add_column("Licences")

    for factor in Registry.in_keep_order(active.factors):
        weight = (
            f"{factor.default_weight:+.4g}"
            if factor.is_sourced
            else Text("unsourced", style="yellow")
        )
        licences = sorted({a.licence.value for a in factor.adapters})
        table.add_row(
            factor.name,
            factor.column,
            factor.transform.value,
            factor.expected_sign.value,
            str(factor.drop_priority),
            weight,
            " → ".join(a.tier.value for a in factor.adapters),
            ", ".join(licences),
        )

    console.print(table)

    unsourced = active.unsourced()
    if unsourced:
        console.print(
            Panel(
                f"{len(unsourced)} of {len(active.factors)} factors have no cited weight, "
                "so Mode B cannot score. Set both [bold]default_weight[/bold] and "
                "[bold]weight_source[/bold] to enable it.\n\n"
                + ", ".join(f.name for f in unsourced),
                title="Mode B not yet available",
                border_style="yellow",
            )
        )


@app.command()
def demo(
    units: Annotated[int, typer.Option(help="Number of corridor segments.")] = 120,
    periods: Annotated[int, typer.Option(help="Number of periods.")] = 24,
    crash_rows_only: Annotated[
        bool,
        typer.Option("--crash-rows-only", help="Drop zero-crash rows, to see Mode A refuse."),
    ] = False,
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write the generated panel to CSV.")
    ] = None,
) -> None:
    """Generate a synthetic corridor panel and assess it."""
    from roadrisk.demo import synthetic_panel

    panel = synthetic_panel(
        n_units=units, n_periods=periods, crash_rows_only=crash_rows_only
    )
    console.print(
        f"[dim]Synthetic panel — {len(panel):,} rows, "
        f"{panel['n_crashes'].sum():,} crashes, "
        f"{int((panel['n_crashes'] == 0).sum()):,} zero-crash rows[/dim]\n"
    )

    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        panel.to_csv(out, index=False)
        console.print(f"[dim]Panel written to {out}[/dim]\n")

    _render(assess(panel))


@app.command()
def version() -> None:
    """Print the engine version."""
    console.print(__version__)


# ---- rendering ---------------------------------------------------------------


def _render(assessment: Assessment) -> None:
    _render_banner(assessment)
    _render_panel_summary(assessment)
    _render_checks(assessment)
    _render_receipts(assessment)

    if assessment.is_mode_a:
        _render_coefficients(assessment)
        _render_sign_guard(assessment)
    else:
        _render_index(assessment)

    _render_footer(assessment)


def _render_banner(assessment: Assessment) -> None:
    if assessment.mode is Mode.A:
        console.print(
            Panel(
                Text(f"🟢 {assessment.banner}", style="bold green"),
                subtitle=f"rung {assessment.rung.value}",
                border_style="green",
            )
        )
    else:
        console.print(
            Panel(
                Text(f"🟡 {assessment.banner}", style="bold yellow"),
                subtitle="no counts, no confidence intervals",
                border_style="yellow",
            )
        )


def _render_panel_summary(assessment: Assessment) -> None:
    contract = assessment.contract
    table = Table(box=None, show_header=False, pad_edge=False)
    table.add_column(style="dim")
    table.add_column()
    table.add_row("Rows", f"{contract.n_rows:,}")
    table.add_row("Units", f"{contract.n_units:,}")
    table.add_row("Periods × slots", f"{contract.n_periods} × {contract.n_time_slots}")
    table.add_row("Crashes", f"{contract.total_crashes:,}")
    table.add_row(
        "Zero-crash rows",
        f"{contract.zero_crash_rows:,} ({contract.zero_crash_share:.1%})",
    )
    table.add_row("Exposure", f"{contract.exposure_total:,.0f} km-hours")
    table.add_row("Registry", f"v{assessment.registry_version}")
    table.add_row(
        "Factors",
        f"{len(assessment.available_factors)} available, "
        f"{len(assessment.missing_factors)} absent, "
        f"{len(assessment.factor_names)} in the model",
    )
    console.print(table)
    console.print()


def _render_checks(assessment: Assessment) -> None:
    _checks_table("Validation gates — before fitting", assessment.gates.checks)
    if assessment.ladder.fit_checks:
        _checks_table(
            "Validation gates — at fit, once the specification was known",
            assessment.ladder.fit_checks,
        )


def _checks_table(title: str, checks: list) -> None:
    table = Table(title=title, header_style="bold", title_justify="left")
    table.add_column("#", justify="right")
    table.add_column("Check")
    table.add_column("Type")
    table.add_column("Status")
    table.add_column("Observed")

    for check in checks:
        table.add_row(
            str(check.number),
            check.name,
            check.failure_type.value,
            Text(check.status.value, style=_STATUS_STYLE[check.status]),
            check.observed or "—",
        )
    console.print(table)
    console.print()


def _render_receipts(assessment: Assessment) -> None:
    if assessment.refusal_receipt:
        console.print(
            Panel(
                assessment.refusal_receipt,
                title="Refusal receipt",
                border_style="yellow",
            )
        )
    if assessment.descent_receipt:
        console.print(
            Panel(
                assessment.descent_receipt,
                title="Descent receipt",
                border_style="cyan",
            )
        )
    if assessment.index_refusal:
        console.print(
            Panel(
                assessment.index_refusal,
                title="Mode B could not score",
                border_style="red",
            )
        )


def _render_coefficients(assessment: Assessment) -> None:
    fit = assessment.fit
    if fit is None:
        return

    expected = {f.name: f.expected_sign.value for f in assessment.ladder.factors}
    table = Table(
        title=f"{fit.specification} — coefficients",
        header_style="bold",
        title_justify="left",
    )
    table.add_column("Factor")
    table.add_column("β", justify="right")
    table.add_column("SE", justify="right")
    table.add_column("z", justify="right")
    table.add_column("p", justify="right")
    table.add_column("95% CI", justify="right")
    table.add_column("Exp.", justify="center")

    if fit.intercept is not None:
        table.add_row(
            Text("(intercept)", style="dim"),
            f"{fit.intercept.estimate:+.4f}",
            f"{fit.intercept.std_error:.4f}",
            f"{fit.intercept.z_value:.2f}",
            f"{fit.intercept.p_value:.3f}",
            f"[{fit.intercept.ci_low:+.3f}, {fit.intercept.ci_high:+.3f}]",
            "—",
        )

    for coefficient in fit.coefficients:
        want = expected.get(coefficient.factor, "?")
        agrees = (want == "+" and coefficient.sign > 0) or (
            want == "-" and coefficient.sign < 0
        )
        style = "green" if agrees else "bold red"
        table.add_row(
            Text(coefficient.factor, style=style),
            Text(f"{coefficient.estimate:+.4f}", style=style),
            f"{coefficient.std_error:.4f}",
            f"{coefficient.z_value:.2f}",
            f"{coefficient.p_value:.3f}",
            f"[{coefficient.ci_low:+.3f}, {coefficient.ci_high:+.3f}]",
            Text(want, style=style),
        )

    console.print(table)

    stats = []
    if fit.alpha is not None:
        stats.append(f"α = {fit.alpha:.3f}")
    if fit.pearson_dispersion is not None:
        stats.append(f"Pearson dispersion = {fit.pearson_dispersion:.2f}")
    if fit.aic is not None:
        stats.append(f"AIC = {fit.aic:,.1f}")
    if assessment.ladder.reference_poisson is not None:
        reference = assessment.ladder.reference_poisson
        if reference.pearson_dispersion is not None:
            stats.append(
                f"Poisson reference dispersion = {reference.pearson_dispersion:.2f}"
            )
    if stats:
        console.print(f"[dim]{'  ·  '.join(stats)}[/dim]")
    console.print()


def _render_sign_guard(assessment: Assessment) -> None:
    guard = assessment.sign_guard
    if guard is None:
        return

    if guard.clean:
        console.print(
            Panel(
                f"All {len(guard.findings)} fitted coefficient(s) point the direction "
                "the registry declares.",
                title="Sign guard — clean",
                border_style="green",
            )
        )
        console.print()
        return

    for finding in guard.contradictions:
        lines = [finding.verdict, ""]
        if finding.univariate_estimate is not None:
            lines.append(
                f"Fitted alone: {finding.univariate_estimate:+.3f}  "
                f"(multivariable: {finding.estimate:+.3f})"
            )
        for refit in finding.pairwise:
            marker = "←" if refit.differs_from_full_fit else " "
            estimate = (
                f"{refit.estimate:+.3f}" if refit.estimate is not None else "did not fit"
            )
            lines.append(
                f"  {marker} alongside {refit.partner} (r = {refit.correlation:+.3f}): "
                f"{estimate}"
            )
        louo = finding.leave_one_out
        if louo and louo.n_refits:
            lines.append(
                f"Leave-one-unit-out over {louo.n_refits} of {louo.n_units} units"
                + (" (capped)" if louo.capped else "")
                + f": {louo.estimate_min:+.3f} to {louo.estimate_max:+.3f}, "
                f"{louo.n_sign_flips} sign flip(s)"
            )

        console.print(
            Panel(
                "\n".join(lines),
                title=f"⚠  Sign contradiction — {finding.factor}",
                border_style="red",
            )
        )
    console.print()


def _render_index(assessment: Assessment) -> None:
    index = assessment.index
    if index is None:
        return

    weights = Table(
        title=f"{index.specification} — terms",
        header_style="bold",
        title_justify="left",
    )
    weights.add_column("Factor")
    weights.add_column("Weight", justify="right")
    weights.add_column("Source")
    for term in index.terms:
        weights.add_row(term.factor, f"{term.weight:+.4g}", term.weight_source)
    console.print(weights)
    console.print()

    ranking = Table(
        title="Highest-risk units (ranking only — not a crash prediction)",
        header_style="bold",
        title_justify="left",
    )
    ranking.add_column("Rank", justify="right")
    ranking.add_column("Unit")
    ranking.add_column("Score", justify="right")
    ranking.add_column("Percentile", justify="right")
    for row in index.unit_ranking.head(10).itertuples():
        ranking.add_row(
            str(row.rank), str(row.unit_id), f"{row.score:.4f}", f"{row.percentile:.1%}"
        )
    console.print(ranking)
    console.print()


def _render_footer(assessment: Assessment) -> None:
    manifest = assessment.manifest
    warnings = len([e for e in assessment.log if e.level.value in {"warning", "flag"}])
    console.print(
        f"[dim]run fingerprint {manifest.fingerprint[:16]}  ·  "
        f"engine v{manifest.engine_version}  ·  registry v{manifest.registry_version}  ·  "
        f"{len(assessment.log)} log events, {warnings} warning(s)[/dim]"
    )


def _print_rejection(exc: RoadRiskError) -> None:
    console.print(
        Panel(
            str(exc),
            title=f"Job rejected — {type(exc).__name__}",
            border_style="red",
        )
    )


def _load(path: Path | None) -> Registry:
    try:
        return load_registry(path)
    except RoadRiskError as exc:
        _print_rejection(exc)
        raise typer.Exit(EXIT_REJECTED) from exc


def _write_run(assessment: Assessment, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "assessment.json").write_text(
        json.dumps(assessment.as_dict(), indent=2, default=str), encoding="utf-8"
    )
    if assessment.index is not None:
        assessment.index.unit_ranking.to_csv(out_dir / "ranking.csv", index=False)


if __name__ == "__main__":  # pragma: no cover
    app()
