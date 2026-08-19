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
from roadrisk.core.context import RunContext
from roadrisk.core.engine import Assessment, assess
from roadrisk.core.errors import RoadRiskError
from roadrisk.core.gates import CheckStatus
from roadrisk.core.ladder import Mode
from roadrisk.core.models import Estimator
from roadrisk.core.registry import (
    FacilityType,
    Region,
    Registry,
    Severity,
    load_registry,
)

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

FacilityOption = Annotated[
    FacilityType,
    typer.Option(
        "--facility-type",
        help="Corridor type. Undeclared admits only unrestricted weights.",
    ),
]
RegionOption = Annotated[
    Region, typer.Option("--region", help="Where the corridor is.")
]
SeverityOption = Annotated[
    Severity,
    typer.Option("--severity", help="Which crashes the panel counts."),
]


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
    facility_type: FacilityOption = FacilityType.ANY,
    region: RegionOption = Region.GLOBAL,
    severity: SeverityOption = Severity.ALL,
    shape: Annotated[
        list[str] | None,
        typer.Option(
            "--shape",
            help=(
                "Run the rung 3 spline on this factor and draw the curve. Repeatable. "
                "A factor whose sign contradicts gets one automatically."
            ),
        ),
    ] = None,
    bayes: Annotated[
        bool,
        typer.Option(
            "--bayes",
            help=(
                "Also fit the Bayesian GLMM: a random intercept per segment, and "
                "credible intervals instead of p-values. Seconds on a narrow "
                "specification; minutes if the approximation is refused."
            ),
        ),
    ] = False,
    priors: Annotated[
        bool,
        typer.Option(
            "--priors",
            help=(
                "Centre each prior on the registry's cited weight instead of on zero, "
                "and report textbook / your data / the mix side by side. Implies "
                "--bayes and costs a second fit."
            ),
        ),
    ] = False,
    spatial: Annotated[
        bool,
        typer.Option(
            "--spatial",
            help=(
                "Also fit a CAR field over the corridor, so neighbouring segments are "
                "correlated rather than strangers. Implies --bayes."
            ),
        ),
    ] = False,
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
    context = RunContext(
        facility_type=facility_type, region=region, severity=severity
    )

    try:
        assessment = assess(
            panel,
            registry=registry,
            context=context,
            shape_factors=shape or (),
            estimator=Estimator.BAYES if (bayes or priors or spatial) else Estimator.NB2,
            use_registry_priors=priors,
            use_spatial=spatial,
        )
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
    table.add_column("Transform")
    table.add_column("Sign", justify="center")
    table.add_column("Drop", justify="right")
    table.add_column("Weights")
    table.add_column("Tiers", justify="center")

    for factor in Registry.in_keep_order(active.factors):
        if factor.weights:
            weights = "\n".join(
                f"{w.value:+.4g} [dim]{w.family.value}"
                f" · {w.facility_type.value} · {w.severity.value}[/dim]"
                for w in factor.weights
            )
        else:
            weights = "[yellow]uncited[/yellow]"
        table.add_row(
            factor.name,
            factor.transform.value,
            factor.expected_sign.value,
            str(factor.drop_priority),
            weights,
            " → ".join(a.tier.value for a in factor.adapters),
        )

    console.print(table)

    sourced = [f for f in active.factors if f.is_sourced]
    total_weights = sum(len(f.weights) for f in active.factors)
    console.print(
        f"[dim]{len(sourced)} of {len(active.factors)} factors cited, "
        f"{total_weights} weights total.[/dim]"
    )

    unsourced = active.unsourced()
    if unsourced:
        console.print(
            Panel(
                f"{len(unsourced)} factor(s) carry no cited weight and cannot enter "
                "Mode B. They are absent from the index, never weighted zero. Each "
                "one's [bold]notes[/bold] records why it is not yet sourced.\n\n"
                + ", ".join(f.name for f in unsourced),
                title="Uncited factors",
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
    unit_dispersion: Annotated[
        float,
        typer.Option(
            "--unit-dispersion",
            help=(
                "How much persistent unobserved character each segment has. Set 0 for "
                "independent rows — unrealistic, and the panel correction then has "
                "nothing to find."
            ),
        ),
    ] = 0.5,
    u_shape: Annotated[
        str | None,
        typer.Option(
            "--u-shape",
            help=(
                "Give this factor a genuinely U-shaped effect instead of a linear one, "
                "so the sign guard fires and the rung 3 spline has something real to "
                "find. Try 'curve_density'."
            ),
        ),
    ] = None,
    facility_type: FacilityOption = FacilityType.ANY,
    region: RegionOption = Region.GLOBAL,
    severity: SeverityOption = Severity.ALL,
    shape: Annotated[
        list[str] | None,
        typer.Option("--shape", help="Run the rung 3 spline on this factor. Repeatable."),
    ] = None,
    bayes: Annotated[
        bool,
        typer.Option(
            "--bayes",
            help=(
                "Also fit the Bayesian GLMM: a random intercept per segment, and "
                "credible intervals instead of p-values."
            ),
        ),
    ] = False,
    priors: Annotated[
        bool,
        typer.Option(
            "--priors",
            help=(
                "Use the registry's cited weights as prior means, and show textbook / "
                "your data / the mix side by side. Implies --bayes."
            ),
        ),
    ] = False,
    spatial: Annotated[
        bool,
        typer.Option(
            "--spatial",
            help=(
                "Also fit a CAR field over the corridor, so neighbouring segments are "
                "correlated rather than strangers. Implies --bayes."
            ),
        ),
    ] = False,
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write the generated panel to CSV.")
    ] = None,
) -> None:
    """Generate a synthetic corridor panel and assess it."""
    from roadrisk.demo import synthetic_panel

    panel = synthetic_panel(
        n_units=units,
        n_periods=periods,
        crash_rows_only=crash_rows_only,
        unit_dispersion=unit_dispersion,
        u_shaped=u_shape,
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

    _render(
        assess(
            panel,
            context=RunContext(
                facility_type=facility_type, region=region, severity=severity
            ),
            shape_factors=shape or (),
            estimator=Estimator.BAYES if (bayes or priors or spatial) else Estimator.NB2,
            use_registry_priors=priors,
            use_spatial=spatial,
        )
    )


@app.command()
def corridor(
    centreline_path: Annotated[
        Path | None,
        typer.Argument(
            metavar="CENTRELINE",
            help="CSV of ordered centreline vertices with latitude/longitude columns.",
        ),
    ] = None,
    crashes_path: Annotated[
        Path | None,
        typer.Option("--crashes", help="Crash CSV with latitude, longitude and period."),
    ] = None,
    demo_corridor: Annotated[
        bool,
        typer.Option("--demo", help="Use a synthetic corridor instead of a file."),
    ] = False,
    ref: Annotated[
        str | None,
        typer.Option(
            "--ref",
            help="Fetch the road from OSM by reference, e.g. 'B9'. Needs --bbox.",
        ),
    ] = None,
    bbox: Annotated[
        str | None,
        typer.Option("--bbox", help="south,west,north,east in degrees. With --ref."),
    ] = None,
    with_osm: Annotated[
        bool,
        typer.Option(
            "--osm/--no-osm",
            help=(
                "Fetch OSM road attributes and conflict-point densities for every unit. "
                "Needs the network; everything else runs offline."
            ),
        ),
    ] = False,
    with_rasters: Annotated[
        bool,
        typer.Option(
            "--rasters/--no-rasters",
            help=(
                "Sample the Copernicus DEM for gradient and ESA WorldCover for roadside "
                'land use. Needs the network and pip install "roadrisk-panel[raster]".'
            ),
        ),
    ] = False,
    with_traffic: Annotated[
        bool,
        typer.Option(
            "--traffic/--no-traffic",
            help=(
                "Estimate a traffic proxy from betweenness on the surrounding road "
                "network. A second, much wider OSM fetch. Never AADT."
            ),
        ),
    ] = False,
    with_mapillary: Annotated[
        bool,
        typer.Option(
            "--mapillary/--no-mapillary",
            help=(
                "Count roadside fixed objects from Mapillary detections. Needs a free "
                "access token in $MAPILLARY_ACCESS_TOKEN."
            ),
        ),
    ] = False,
    cache_dir: Annotated[
        Path | None,
        typer.Option(
            "--cache",
            help=(
                "Remember remote fetches here between runs. A second corridor in the "
                "same region reuses the first one's network fetch. Every hit is "
                "reported with the age of the data it served."
            ),
        ),
    ] = None,
    client_path: Annotated[
        Path | None,
        typer.Option(
            "--client",
            help=(
                "CSV of anything you already measured, one row per unit keyed by "
                "unit_id. It outranks every open source, and where both cover a factor "
                "the units they disagree on are named."
            ),
        ),
    ] = None,
    unit_length_m: Annotated[
        float, typer.Option("--unit-length", help="Target segment length in metres.")
    ] = 500.0,
    tolerance_m: Annotated[
        float, typer.Option("--tolerance", help="Crash snapping tolerance in metres.")
    ] = 30.0,
    n_periods: Annotated[
        int, typer.Option("--periods", help="Number of monthly periods to build.")
    ] = 24,
    facility_type: FacilityOption = FacilityType.ANY,
    region: RegionOption = Region.GLOBAL,
    severity: SeverityOption = Severity.ALL,
    out_dir: Annotated[
        Path | None, typer.Option("--out", "-o", help="Directory for the run record.")
    ] = None,
) -> None:
    """Build a panel from a corridor centreline, then assess it.

    Geography produces the panel; the engine judges it. Zero-crash rows exist because
    road exists, which is what makes Mode A admissible at all.

    CENTRELINE is a CSV of ordered vertices with latitude and longitude columns.
    Export the real road from OpenStreetMap rather than drawing it — run
    'roadrisk centreline-help' for the recipe.
    """
    try:
        from roadrisk.geo import (
            build_corridor_panel,
            elevation_sampler,
            landcover_sampler,
        )
        from roadrisk.geo.adapters.mapillary import HttpMapillaryClient
        from roadrisk.geo.cache import FileCache
        from roadrisk.geo.demo import (
            monthly_periods,
            synthetic_centreline,
            synthetic_crashes,
        )
        from roadrisk.geo.osm import HttpOverpassClient
    except ModuleNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(EXIT_REJECTED) from exc

    periods = monthly_periods(n_periods)

    corridor_name = "corridor"

    if demo_corridor:
        points = synthetic_centreline(length_km=10.0)
        crashes = synthetic_crashes(points, periods, n_crashes=900)
        corridor_name = "demo"
        console.print(
            "[dim]Synthetic corridor — 10 km, tightening bends, and a crash table "
            "with the defects a real police extract has.[/dim]\n"
        )
    elif ref is not None:
        points = _fetch_from_osm(ref, bbox)
        corridor_name = ref
        crashes = (
            pd.read_csv(crashes_path) if crashes_path is not None else None
        )
    elif centreline_path is None:
        from roadrisk.geo.corridor import CENTRELINE_GUIDANCE

        console.print(
            "[red]Supply a CENTRELINE csv, or pass --demo for a synthetic one.[/red]\n"
        )
        console.print(
            Panel(
                # Text(), not a bare string: the Overpass query contains [out:json],
                # which Rich would otherwise swallow as a markup tag.
                Text(CENTRELINE_GUIDANCE),
                title="Where to get a centreline",
                border_style="cyan",
            )
        )
        raise typer.Exit(EXIT_REJECTED)
    else:
        points, crashes = _read_corridor_inputs(centreline_path, crashes_path)
        corridor_name = centreline_path.stem

    client_values = None
    if client_path is not None:
        try:
            client_values = pd.read_csv(client_path)
        except OSError as exc:
            console.print(f"[red]Cannot read {client_path}: {exc}[/red]")
            raise typer.Exit(EXIT_REJECTED) from exc

    if with_osm:
        console.print("[dim]Fetching OSM road attributes along the corridor…[/dim]")
    if with_rasters:
        console.print(
            "[dim]Sampling the Copernicus DEM and ESA WorldCover along the corridor…"
            "[/dim]"
        )
    if with_traffic:
        console.print(
            "[dim]Fetching the surrounding strategic network for the traffic proxy — "
            "this is the largest query the pipeline makes…[/dim]"
        )
    if with_mapillary:
        console.print("[dim]Fetching Mapillary roadside detections…[/dim]")

    try:
        built = build_corridor_panel(
            points,
            periods=periods,
            name=corridor_name,
            crashes=crashes,
            target_length_m=unit_length_m,
            tolerance_m=tolerance_m,
            osm_client=HttpOverpassClient() if with_osm else None,
            elevation=elevation_sampler() if with_rasters else None,
            landcover=landcover_sampler() if with_rasters else None,
            network_client=HttpOverpassClient(timeout_s=240.0) if with_traffic else None,
            mapillary_client=HttpMapillaryClient() if with_mapillary else None,
            cache=FileCache(directory=cache_dir) if cache_dir is not None else None,
            client_values=client_values,
            client_source=(
                f"Supplied by the client in {client_path.name}, one value per unit."
                if client_path is not None
                else None
            ),
            ref=ref,
        )
    except RoadRiskError as exc:
        _print_rejection(exc)
        raise typer.Exit(EXIT_REJECTED) from exc

    _render_corridor(
        built,
        with_osm=with_osm,
        with_rasters=with_rasters,
        with_traffic=with_traffic,
        with_mapillary=with_mapillary,
    )

    assessment = assess(
        built.panel,
        snap=built.snap,
        context=RunContext(
            facility_type=facility_type, region=region, severity=severity
        ),
    )
    _render(assessment)

    if out_dir is not None:
        _write_run(assessment, out_dir)
        built.panel.to_csv(out_dir / "panel.csv", index=False)
        built.provenance.to_csv(out_dir / "provenance.csv", index=False)
        built.confidence.to_csv(out_dir / "confidence.csv", index=False)
        if built.snap_detail is not None:
            built.snap_detail.to_csv(out_dir / "snap_detail.csv", index=False)
        console.print(f"\n[dim]Run record and panel written to {out_dir}[/dim]")


def _fetch_from_osm(ref: str, bbox: str | None) -> list[tuple[float, float]]:
    """Resolve a corridor straight from OSM, reporting what had to be assembled."""
    from roadrisk.geo.osm import BoundingBox, fetch_corridor

    if bbox is None:
        console.print(
            "[red]--ref needs --bbox south,west,north,east[/red]\n"
            "[dim]e.g. --ref B9 --bbox 34.80,32.80,35.05,33.05[/dim]"
        )
        raise typer.Exit(EXIT_REJECTED)

    try:
        south, west, north, east = (float(part) for part in bbox.split(","))
    except ValueError as exc:
        console.print(f"[red]--bbox must be four numbers, got {bbox!r}[/red]")
        raise typer.Exit(EXIT_REJECTED) from exc

    console.print(f"[dim]Fetching ref={ref!r} from OpenStreetMap…[/dim]")
    try:
        fetched = fetch_corridor(
            ref, BoundingBox(south=south, west=west, north=north, east=east)
        )
    except RoadRiskError as exc:
        _print_rejection(exc)
        raise typer.Exit(EXIT_REJECTED) from exc

    table = Table(box=None, show_header=False, pad_edge=False)
    table.add_column(style="dim")
    table.add_column()
    table.add_row("Fragments", str(fetched.n_fragments))
    table.add_row("After merge", str(fetched.n_pieces_after_merge))
    table.add_row("Gaps bridged", str(fetched.gaps_bridged))
    table.add_row("Longest share", f"{fetched.longest_share:.1%}")
    table.add_row("Divided road", "yes" if fetched.divided else "no")
    if fetched.excluded_km:
        table.add_row("Excluded", f"{fetched.excluded_km:.2f} km")
    if fetched.tags.get("name"):
        table.add_row("Name", fetched.tags["name"])
    console.print(table)

    if fetched.warnings:
        console.print(
            Panel(
                Text("\n\n".join(f"• {w}" for w in fetched.warnings)),
                title="Assembly notes",
                border_style="yellow",
            )
        )
    console.print()
    return fetched.points


def _read_corridor_inputs(
    centreline_path: Path,
    crashes_path: Path | None,
) -> tuple[list[tuple[float, float]], pd.DataFrame | None]:
    try:
        frame = pd.read_csv(centreline_path)
    except OSError as exc:
        console.print(f"[red]Cannot read {centreline_path}: {exc}[/red]")
        raise typer.Exit(EXIT_REJECTED) from exc

    missing = [c for c in ("latitude", "longitude") if c not in frame.columns]
    if missing:
        console.print(
            f"[red]{centreline_path} is missing column(s): {', '.join(missing)}[/red]"
        )
        raise typer.Exit(EXIT_REJECTED)

    points = list(
        zip(frame["latitude"].tolist(), frame["longitude"].tolist(), strict=True)
    )

    crashes = None
    if crashes_path is not None:
        try:
            crashes = pd.read_csv(crashes_path)
        except OSError as exc:
            console.print(f"[red]Cannot read {crashes_path}: {exc}[/red]")
            raise typer.Exit(EXIT_REJECTED) from exc

    return points, crashes


def _render_corridor(
    built,
    *,
    with_osm: bool = False,
    with_rasters: bool = False,
    with_traffic: bool = False,
    with_mapillary: bool = False,
) -> None:
    console.print(
        Panel(built.summary(), title="Corridor built", border_style="cyan")
    )

    table = Table(box=None, show_header=False, pad_edge=False)
    table.add_column(style="dim")
    table.add_column()
    table.add_row("Length", f"{built.corridor.length_km:.2f} km")
    table.add_row("Units", f"{built.n_units:,}")
    table.add_row("Projection", f"EPSG:{built.corridor.epsg}")
    table.add_row("Factors derived", f"{len(built.factor_columns)}")
    if built.snap is not None:
        reasons = ", ".join(
            f"{k} {v:,}" for k, v in built.snap.dropped_reasons.items()
        )
        table.add_row(
            "Snapped",
            f"{built.snap.n_snapped:,} of {built.snap.n_supplied:,} "
            f"({built.snap.snap_rate:.1%})",
        )
        table.add_row("Dropped", reasons or "none")
    console.print(table)
    console.print()

    _render_provenance(built)

    offered = []
    if not with_osm:
        offered.append(
            "--osm for the road's own tags and its junction, access, ramp, POI and "
            "building densities"
        )
    if not with_rasters:
        offered.append(
            "--rasters for gradient from the Copernicus DEM and roadside land use from "
            "ESA WorldCover"
        )
    if not with_traffic:
        offered.append("--traffic for a graph-centrality traffic proxy")
    if not with_mapillary:
        offered.append("--mapillary for roadside fixed objects")
    if offered:
        console.print(
            "[dim]Not every source ran. Pass "
            + "; ".join(offered)
            + ".[/dim]\n"
        )

    if built.warnings:
        console.print(
            Panel(
                # Text(), not markup: the under-sampling note embeds an Overpass query
                # containing [out:json], which Rich would parse as a tag and drop.
                Text("\n\n".join(f"• {w}" for w in built.warnings)),
                title="Geometry notes",
                border_style="yellow",
            )
        )
        console.print()


def _render_provenance(built) -> None:
    """Value, source, tier and licence for every factor an adapter produced.

    The brief asks each adapter to return all four. This is where a client auditing a
    number finds out where it came from and what may be done with it.
    """
    provenance = built.provenance
    if not provenance.empty:
        table = Table(
            title="Factor provenance — where every value came from",
            header_style="bold",
            title_justify="left",
        )
        table.add_column("Column")
        table.add_column("Adapter")
        table.add_column("Tier", justify="center")
        table.add_column("Licence")
        table.add_column("Conf.", justify="right")
        table.add_column("Vs")
        table.add_column("Agree", justify="right")
        table.add_column("Source")

        for row in provenance.itertuples():
            table.add_row(
                row.column,
                row.adapter,
                row.tier,
                row.licence,
                _confidence_cell(row.confidence_high, row.confidence_low),
                row.contested_by or Text("—", style="dim"),
                _agreement_cell_geo(row.agreement),
                _cite(row.source, limit=40),
            )
        console.print(table)
        console.print(
            "[dim]Conf. is the share of units at high confidence; per-unit tiers and "
            "coverage are in the run record. 'Vs' names a source that resolved the same "
            "factor and lost on registry priority.[/dim]"
        )
        console.print()

    _render_disagreements(built)

    skipped = built.skipped
    if skipped:
        console.print(
            Panel(
                "\n".join(
                    f"[bold]{factor}[/bold] via {adapter}\n  {reason}."
                    for factor, adapter, reason in skipped
                ),
                title="Looked for, not found — these factors are absent, not zero",
                border_style="yellow",
            )
        )
        console.print()


def _confidence_cell(high: float, low: float) -> Text:
    """High-confidence share, coloured by how much of the column is not."""
    style = "green" if high >= 0.9 else "yellow" if low < 0.25 else "red"
    return Text(f"{high:.0%}", style=style)


def _agreement_cell_geo(score: float | None) -> Text:
    # pandas turns a None into NaN as soon as the column holds one float, so an
    # uncontested factor arrives here as nan rather than None.
    if score is None or pd.isna(score):
        return Text("—", style="dim")
    style = "green" if score >= 0.9 else "yellow" if score >= 0.6 else "bold red"
    return Text(f"{score:.0%}", style=style)


def _render_disagreements(built) -> None:
    """Where two sources cover the same factor and do not match.

    The most useful output in the run: agreement between open sources can be an echo,
    but a disagreement means one of them is definitely wrong about those units.
    """
    disagreements = built.fusion.disagreements
    if not disagreements:
        return

    for agreement in disagreements:
        units = ", ".join(agreement.disagreeing_units)
        console.print(
            Panel(
                f"'{agreement.chosen}' won on registry priority; "
                f"'{agreement.challenger}' disagrees.\n\n"
                f"Compared on {agreement.n_compared} unit(s) both measured, agreeing on "
                f"{agreement.n_agreeing} ({agreement.score:.0%}).\n"
                f"Mean absolute difference {agreement.mean_absolute_difference:.3g}, "
                f"worst {agreement.max_absolute_difference:.3g}"
                + (
                    f", correlation {agreement.correlation:+.2f}"
                    if agreement.correlation is not None
                    else ""
                )
                + f".\n\nUnits that differ: {units}\n\n"
                "These are marked low confidence. One of the two sources is wrong "
                "about them, and nothing here can say which.",
                title=f"⚠  Sources disagree — {agreement.column}",
                border_style="red",
            )
        )
        console.print()


@app.command("centreline-help")
def centreline_help() -> None:
    """How to get a corridor centreline good enough to measure curvature from."""
    try:
        from roadrisk.geo.corridor import CENTRELINE_GUIDANCE
    except ModuleNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(EXIT_REJECTED) from exc

    console.print(
        Panel(
            # Text(), not a bare string: the Overpass query contains [out:json],
            # which Rich would otherwise swallow as a markup tag.
            Text(CENTRELINE_GUIDANCE),
            title="Where to get a centreline",
            border_style="cyan",
        )
    )
    console.print(
        "[dim]Routing straight from two coordinates is Step 2.2b and is not built "
        "yet. Until it is, this export is the same OSM data that step would fetch — "
        "you are just doing it in a browser.[/dim]"
    )


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
        _render_validation(assessment)
        _render_evidence(assessment)
        _render_posterior(assessment)
        _render_spatial(assessment)
        _render_sign_guard(assessment)
        _render_shapes(assessment)
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
        "Context",
        assessment.context.describe()
        + ("" if assessment.context.is_declared else "  [dim](undeclared)[/dim]"),
    )
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
    if fit.is_clustered:
        # Both, side by side. The correction is invisible in the estimates, so the only
        # way a reader can judge its size is to see what they would have been told.
        table.add_column("SE naive", justify="right", style="dim")
        table.add_column("SE panel", justify="right")
        table.add_column("×", justify="right")
    else:
        table.add_column("SE", justify="right")
    table.add_column("z", justify="right")
    table.add_column("p", justify="right")
    table.add_column("95% CI", justify="right")
    table.add_column("Exp.", justify="center")

    if fit.intercept is not None:
        table.add_row(
            Text("(intercept)", style="dim"),
            f"{fit.intercept.estimate:+.4f}",
            *(
                ["—", f"{fit.intercept.std_error:.4f}", "—"]
                if fit.is_clustered
                else [f"{fit.intercept.std_error:.4f}"]
            ),
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
        naive = fit.naive_std_errors.get(coefficient.factor)
        table.add_row(
            Text(coefficient.factor, style=style),
            Text(f"{coefficient.estimate:+.4f}", style=style),
            *(
                [
                    f"{naive:.4f}" if naive is not None else "—",
                    f"{coefficient.std_error:.4f}",
                    _widening_cell(fit.cluster_widening.get(coefficient.factor)),
                ]
                if fit.is_clustered
                else [f"{coefficient.std_error:.4f}"]
            ),
            f"{coefficient.z_value:.2f}",
            f"{coefficient.p_value:.3f}",
            f"[{coefficient.ci_low:+.3f}, {coefficient.ci_high:+.3f}]",
            Text(want, style=style),
        )

    console.print(table)
    _render_panel_correction(fit)

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


def _widening_cell(factor: float | None) -> Text:
    """How much the panel correction widened this interval."""
    if factor is None:
        return Text("—", style="dim")
    style = "bold red" if factor >= 2.0 else "yellow" if factor >= 1.3 else "dim"
    return Text(f"{factor:.2f}", style=style)


def _render_panel_correction(fit) -> None:
    """What rung 2 did to the certainty, and what it could not do.

    The panel correction is invisible in the coefficients — they do not move — so if it
    is not said here it is not said anywhere.
    """
    if not fit.notes:
        return

    console.print(
        Panel(
            "\n\n".join(fit.notes),
            title=(
                f"Panel correction — standard errors clustered over "
                f"{fit.n_clusters} unit(s)"
                if fit.is_clustered
                else "Panel correction — NOT applied"
            ),
            border_style="cyan" if fit.is_clustered else "red",
        )
    )
    console.print()


def _render_validation(assessment: Assessment) -> None:
    """Out-of-sample validation. Printed on every Mode A run, pass or fail."""
    report = assessment.validation
    if report is None:
        return

    if not report.available:
        console.print(
            Panel(
                report.refusal or "",
                title="Out-of-sample validation — not run",
                border_style="yellow",
            )
        )
        console.print()
        return

    table = Table(
        title="Out-of-sample validation — held-out stretches of this corridor",
        header_style="bold",
        title_justify="left",
    )
    table.add_column("Scheme")
    table.add_column("Observed", justify="right")
    table.add_column("Predicted", justify="right")
    table.add_column("Ratio", justify="right")
    table.add_column("MAD", justify="right")

    for calibration in (report.spatial, report.random):
        if calibration is None:
            continue
        ratio = calibration.factor
        style = "green" if calibration.calibrated else "red"
        table.add_row(
            calibration.scheme,
            f"{calibration.observed:,.0f}",
            f"{calibration.predicted:,.0f}",
            Text(f"{ratio:.2f}" if ratio else "—", style=style),
            f"{calibration.mean_absolute_deviation:.3f}",
        )
    console.print(table)

    if report.optimism is not None:
        console.print(
            f"[dim]Random folds look {report.optimism:+.3f} crashes per cell better "
            "than contiguous ones — adjacent segments share their character, so a "
            "random fold leaves a segment's own neighbours in the training set.[/dim]"
        )

    drifting = report.drifting_factors
    if drifting:
        lines = []
        for curve in drifting:
            lines.extend([curve.describe(), "", curve.render(), ""])
        console.print(
            Panel(
                "\n".join(lines).rstrip(),
                title=f"⚠  CURE drift — {len(drifting)} factor(s) mis-specified",
                border_style="red",
            )
        )
    else:
        console.print(
            Panel(
                "Cumulative residuals stay inside their bounds for every factor. The "
                "model is not systematically wrong anywhere along any factor's range.",
                title="CURE — clean",
                border_style="green",
            )
        )
    for note in report.notes:
        console.print(f"[dim]{note}[/dim]")
    console.print()


def _render_evidence(assessment: Assessment) -> None:
    """Textbook, corridor and mixture side by side, with the designated answer named."""
    evidence = assessment.evidence
    if evidence is None:
        return

    table = Table(
        title="Three answers per factor — and the one this run designates",
        header_style="bold",
        title_justify="left",
    )
    table.add_column("Factor", no_wrap=True)
    table.add_column("Textbook", justify="right", no_wrap=True, min_width=8)
    table.add_column("Your data", justify="right", no_wrap=True, min_width=15)
    table.add_column("The mix", justify="right", no_wrap=True, min_width=15)
    table.add_column("%bk", justify="right", no_wrap=True, min_width=4)
    table.add_column("Reading", min_width=18)

    def interval(mean, low, high) -> str:
        if mean is None:
            return "—"
        return f"{mean:+.3f}\n[{low:+.2f}, {high:+.2f}]"

    for item in evidence.factors:
        if item.contradicts_textbook:
            style = "red"
        elif item.prior_dominates or item.indirectly_shifted:
            style = "yellow"
        else:
            style = "green" if item.is_cited else "dim"
        share = f"{item.prior_share:.0%}" if item.prior_share is not None else "—"
        table.add_row(
            item.factor,
            f"{item.textbook:+.3f}" if item.textbook is not None else "—",
            interval(item.data_mean, item.data_low, item.data_high),
            interval(item.mix_mean, item.mix_low, item.mix_high),
            Text(share, style=style),
            Text(item.label(), style=style),
        )

    console.print(table)
    console.print(
        "[dim]%bk — how much of the mixed answer came from the published weight rather "
        "than from this corridor.[/dim]"
    )
    console.print(
        Panel(
            evidence.reason,
            title=f"Designated answer — {evidence.answer.value.upper()}",
            border_style="cyan",
        )
    )
    for note in evidence.notes:
        console.print(f"[dim]{note}[/dim]")
    console.print()


def _render_posterior(assessment: Assessment) -> None:
    """The Bayesian rung — credible intervals, and no p-value column anywhere."""
    posterior = assessment.posterior
    if posterior is None:
        return

    if not posterior.converged:
        console.print(
            Panel(
                "\n".join([*posterior.descent, "", posterior.failure_reason or ""]),
                title="Bayesian rung — refused",
                subtitle="[dim]the NB2 fit above is unaffected[/dim]",
                border_style="yellow",
            )
        )
        console.print()
        return

    table = Table(
        title=(
            f"{posterior.specification} — {int(posterior.hdi_probability * 100)}% "
            "credible intervals"
        ),
        header_style="bold",
        title_justify="left",
    )
    table.add_column("Factor")
    table.add_column("Posterior mean", justify="right")
    table.add_column("SD", justify="right")
    table.add_column(f"{int(posterior.hdi_probability * 100)}% credible", justify="right")
    table.add_column("P(direction)", justify="right")

    by_name = {f.name: f for f in assessment.available_factors}
    for summary in posterior.coefficients:
        factor = by_name.get(summary.name)
        expected = factor.expected_sign.as_int if factor else summary.sign
        probability = summary.probability_of_sign(expected)
        # Not a significance star. It is the posterior's own answer to "does this point
        # the way the registry says", which is the question the sign guard asks.
        style = "green" if probability >= 0.95 else "yellow" if probability >= 0.8 else "red"
        table.add_row(
            summary.name,
            f"{summary.mean:+.4f}",
            f"{summary.sd:.4f}",
            f"[{summary.hdi_low:+.3f}, {summary.hdi_high:+.3f}]",
            Text(f"{probability:.2f}", style=style),
        )

    console.print(table)

    if posterior.sigma_u is not None:
        console.print(
            f"[bold]Between-segment SD[/bold] σ_u = {posterior.sigma_u.mean:.3f} "
            f"[{posterior.sigma_u.hdi_low:.3f}, {posterior.sigma_u.hdi_high:.3f}] "
            "on the log rate — the persistent character rungs 1 and 2 could not "
            "measure at all."
        )
    console.print(f"[dim]{' · '.join(posterior.descent)}[/dim]")
    console.print()


def _render_spatial(assessment: Assessment) -> None:
    """What the corridor said about whether its segments cluster."""
    report = assessment.spatial
    if report is None:
        fit = assessment.posterior_spatial
        if fit is not None and not fit.converged:
            console.print(
                Panel(
                    fit.failure_reason or "",
                    title="Spatial field — refused",
                    border_style="yellow",
                )
            )
            console.print()
        return

    border = "green" if report.spatial else "yellow" if not report.identified else "cyan"
    console.print(
        Panel(
            report.describe(),
            title=f"Spatial field — ρ = {report.rho.mean:.2f}",
            border_style=border,
        )
    )
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

        if finding.shape is not None:
            lines.extend(["", *_shape_lines(finding.shape)])

        console.print(
            Panel(
                "\n".join(lines),
                title=f"⚠  Sign contradiction — {finding.factor}",
                border_style="red",
            )
        )
    console.print()


def _shape_lines(diagnostic) -> list[str]:
    """The rung 3 spline, as the reader should meet it: the plot, then the reading."""
    if not diagnostic.available:
        return [f"Rung 3 spline: not run — {diagnostic.refusal}"]

    header = f"Rung 3 spline — the curve {diagnostic.shape.describe()}"
    if diagnostic.explains_contradiction:
        header += "  [bold]← this explains the sign[/bold]"
    lines = [header, ""]
    if diagnostic.curve is not None:
        lines.append(diagnostic.curve.render())
        lines.append("")
    lines.append(diagnostic.verdict)
    lines.extend(f"[dim]{note}[/dim]" for note in diagnostic.notes)
    return lines


def _render_shapes(assessment: Assessment) -> None:
    """Splines the caller asked for by name, rather than ones a reversal forced."""
    contradicting = {
        f.factor
        for f in (
            assessment.sign_guard.contradictions if assessment.sign_guard else []
        )
    }
    requested = [s for s in assessment.shapes if s.factor not in contradicting]
    if not requested:
        return

    for diagnostic in requested:
        console.print(
            Panel(
                "\n".join(_shape_lines(diagnostic)),
                title=f"Shape diagnostic — {diagnostic.factor}",
                subtitle="[dim]reference only — never a client number[/dim]",
                border_style="cyan",
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
    weights.add_column("From")
    weights.add_column("Applies to")
    weights.add_column("Agree", justify="center")
    weights.add_column("Source")

    for term in weights_ordered(index.terms):
        weights.add_row(
            Text(term.factor, style="yellow" if term.has_concerns else None),
            f"{term.weight:+.4g}",
            term.family,
            Text(
                "all crash types" if term.applies_to_all_crash_types else term.scope.value,
                style="dim" if term.applies_to_all_crash_types else "cyan",
            ),
            _agreement_cell(term),
            _cite(term.weight_source, limit=36),
        )
    console.print(weights)
    console.print(
        "[dim]Citations truncated for display — full text in the registry and in "
        "assessment.json. A yellow factor name means the weight carries a concern.[/dim]"
    )
    console.print()
    _render_crash_types(index)

    for term in index.disagreements:
        agreement = term.agreement
        assert agreement is not None  # noqa: S101 - guaranteed by .disagreements
        console.print(
            Panel(
                agreement.note
                + "\n\n"
                + ", ".join(
                    f"{family} = {value:+.4f}"
                    for family, value in zip(
                        agreement.families, agreement.values, strict=True
                    )
                ),
                title=f"⚠  Sources disagree on direction — {term.factor}",
                border_style="red",
            )
        )
        console.print()

    concerned = index.concerns
    if concerned:
        lines: list[str] = []
        for term in concerned:
            for concern in term.concerns:
                lines.append(f"[bold]{term.factor}[/bold] · {concern.code}")
                lines.append(f"  {concern.message}")
        console.print(
            Panel(
                "\n".join(lines),
                title="Weight concerns — reasons to trust these terms less",
                border_style="yellow",
            )
        )
        console.print()

    if index.skipped_unsourced or index.skipped_inadmissible:
        parts: list[str] = []
        if index.skipped_unsourced:
            parts.append(
                f"[bold]No cited weight[/bold] ({len(index.skipped_unsourced)}): "
                + ", ".join(index.skipped_unsourced)
            )
        if index.skipped_inadmissible:
            parts.append(
                f"[bold]Cited, but not valid for this run[/bold] "
                f"({len(index.skipped_inadmissible)}): "
                + ", ".join(index.skipped_inadmissible)
                + "\nA weight restricted to another facility type or crash severity is "
                "not transferable, and the engine will not stretch it."
            )
        parts.append(
            "These factors are [bold]absent[/bold] from the index, not weighted zero."
        )
        console.print(
            Panel(
                "\n\n".join(parts),
                title="Available but not scored",
                border_style="yellow",
            )
        )
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


def _render_crash_types(index) -> None:
    """Show the decomposition, because a combined score hides which problem it is."""
    table = Table(
        title="Crash-type decomposition — where the risk sits",
        header_style="bold",
        title_justify="left",
    )
    table.add_column("Crash type")
    table.add_column("Share", justify="right")
    table.add_column("Mean score", justify="right")
    table.add_column("Terms entering it")

    for bucket, mean_score in index.bucket_mean_scores.items():
        entering = index.terms_for(bucket)
        scoped = [t.factor for t in entering if not t.applies_to_all_crash_types]
        detail = (
            f"{len(entering)} ("
            + (", ".join(scoped) + " scoped here" if scoped else "all total-scope")
            + ")"
        )
        table.add_row(
            bucket.value,
            f"{index.crash_mix.share(bucket):.1%}",
            f"{mean_score:+.4f}",
            detail,
        )

    console.print(table)
    note = f"Shares: {_cite(index.crash_mix.source, limit=110)}"
    if index.context.uses_default_crash_mix:
        note += (
            "\nThis is the DEFAULT distribution — an HSM figure carrying the same "
            "regional transfer problem as any other. Supplying a local one is cheap."
        )
    console.print(f"[dim]{note}[/dim]")
    console.print()


def weights_ordered(terms: list) -> list:
    """Largest absolute contribution first — the terms driving the ranking."""
    return sorted(terms, key=lambda t: abs(t.weight), reverse=True)


def _agreement_cell(term) -> Text:
    agreement = term.agreement
    if agreement is None:
        return Text("single", style="dim")
    if not agreement.comparable:
        return Text("scope≠", style="yellow")
    if agreement.signs_conflict:
        return Text("CONFLICT", style="bold red")
    score = agreement.score or 0.0
    style = "green" if score >= 0.7 else "yellow"
    return Text(f"{score:.2f}", style=style)


def _cite(source: str, limit: int = 72) -> str:
    """Collapse a folded YAML citation to one line, short enough for a table cell."""
    collapsed = " ".join(source.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


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
