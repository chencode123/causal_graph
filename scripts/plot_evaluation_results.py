from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Dict, Iterable, List

import matplotlib.pyplot as plt
import numpy as np
from scipy.stats import gaussian_kde


CASE_SCORE_FILENAME = "case_scores.csv"
WL_COL = "structural_similarity"
EXACT_COL = "normalized_graph_edit_distance"
WL_ACCEPT_COL = "structural_similarity_accept_all_vs_updated"
EXACT_ACCEPT_COL = "normalized_graph_edit_distance_accept_all_vs_updated"

FONT_FAMILY = ["Arial", "Times New Roman", "DejaVu Sans"]
BASE_FONT_SIZE = 10
TITLE_FONT_SIZE = 12
LABEL_FONT_SIZE = 10
TICK_FONT_SIZE = 9


def parse_args() -> argparse.Namespace:
    """Parse arguments for plotting evaluation results."""
    parser = argparse.ArgumentParser(
        description=(
            "Generate publication-quality evaluation figures from a results "
            "directory containing case_scores.csv."
        )
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        required=True,
        help="Timestamped evaluation output directory.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory where figures will be written. Defaults to <results-dir>/figures.",
    )
    return parser.parse_args()


def read_csv_rows(path: Path) -> List[Dict[str, str]]:
    """Read CSV rows into a list of dictionaries."""
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        return list(csv.DictReader(fp))


def to_float(value: str) -> float | None:
    """Convert a CSV string value to float when possible."""
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def filter_ok_case_rows(rows: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    """Keep only successful case rows with numeric metrics."""
    return [row for row in rows if str(row.get("status", "")).strip().lower() == "ok"]


def has_numeric_metric(rows: Iterable[Dict[str, str]], key: str) -> bool:
    """Return True when at least one row contains a numeric value for key."""
    return any(to_float(row.get(key, "")) is not None for row in rows)


def ensure_output_dir(output_dir: Path) -> Path:
    """Create the output directory if needed."""
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def clear_existing_figures(output_dir: Path) -> None:
    """Remove previously generated figure files from the output directory."""
    for pattern in ("figure_*.png", "figure_*.svg"):
        for path in output_dir.glob(pattern):
            path.unlink()


def set_plot_style() -> None:
    """Apply a clean journal-style plotting configuration."""
    plt.style.use("default")
    plt.rcParams.update(
        {
            "figure.dpi": 150,
            "savefig.dpi": 300,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.facecolor": "white",
            "savefig.bbox": "tight",
            "font.family": "sans-serif",
            "font.sans-serif": FONT_FAMILY,
            "font.size": BASE_FONT_SIZE,
            "axes.titlesize": TITLE_FONT_SIZE,
            "axes.labelsize": LABEL_FONT_SIZE,
            "xtick.labelsize": TICK_FONT_SIZE,
            "ytick.labelsize": TICK_FONT_SIZE,
            "legend.fontsize": 9,
            "axes.linewidth": 0.8,
            "xtick.major.width": 0.8,
            "ytick.major.width": 0.8,
            "xtick.direction": "out",
            "ytick.direction": "out",
            "axes.grid": False,
            "legend.frameon": False,
        }
    )


def style_axes(ax: plt.Axes) -> None:
    """Apply thin spines and remove visual clutter."""
    ax.grid(False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_linewidth(0.8)
    ax.spines["bottom"].set_linewidth(0.8)
    ax.tick_params(length=4, width=0.8)


def save_figure(fig: plt.Figure, output_dir: Path, stem: str) -> None:
    """Save one figure as both PNG and SVG and close it."""
    fig.tight_layout()
    fig.savefig(output_dir / f"{stem}.png")
    fig.savefig(output_dir / f"{stem}.svg")
    plt.close(fig)


def select_complete_rows(rows: Iterable[Dict[str, str]], keys: List[str]) -> List[Dict[str, float]]:
    """Keep rows where all requested fields are numeric."""
    selected: List[Dict[str, float]] = []
    for row in rows:
        numeric_row: Dict[str, float] = {}
        valid = True
        for key in keys:
            value = to_float(row.get(key, ""))
            if value is None:
                valid = False
                break
            numeric_row[key] = value
        if valid:
            selected.append(numeric_row)
    return selected


def grouped_summary_by_step(
    case_rows: List[Dict[str, str]],
    x_key: str,
    y_key: str,
    y_transform=None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Summarize a metric by step using median and interquartile range."""
    grouped: Dict[int, List[float]] = {}
    for row in case_rows:
        x_value = to_float(row.get(x_key, ""))
        y_value = to_float(row.get(y_key, ""))
        if x_value is None or y_value is None:
            continue
        step = int(round(x_value))
        metric_value = y_transform(y_value) if y_transform is not None else y_value
        grouped.setdefault(step, []).append(float(metric_value))

    steps = np.asarray(sorted(grouped), dtype=float)
    medians = np.asarray([np.median(grouped[int(step)]) for step in steps], dtype=float)
    q1 = np.asarray([np.percentile(grouped[int(step)], 25) for step in steps], dtype=float)
    q3 = np.asarray([np.percentile(grouped[int(step)], 75) for step in steps], dtype=float)
    return steps, medians, q1, q3


def fit_line(x: np.ndarray, y: np.ndarray) -> tuple[float, float] | None:
    """Fit a least-squares line to the provided data."""
    if x.size < 2:
        return None
    slope, intercept = np.polyfit(x, y, deg=1)
    return float(slope), float(intercept)


def add_regression_line(ax: plt.Axes, x: np.ndarray, y: np.ndarray, color: str) -> tuple[float, float] | None:
    """Add a regression line and return its parameters."""
    params = fit_line(x, y)
    if params is None:
        return None
    slope, intercept = params
    x_line = np.linspace(x.min(), x.max(), 200)
    y_line = slope * x_line + intercept
    ax.plot(x_line, y_line, linestyle="--", linewidth=1.2, color=color)
    return params


def compute_r_squared(x: np.ndarray, y: np.ndarray) -> float | None:
    """Compute R-squared for a simple linear fit."""
    params = fit_line(x, y)
    if params is None:
        return None
    slope, intercept = params
    predictions = slope * x + intercept
    residual_sum = float(np.sum((y - predictions) ** 2))
    total_sum = float(np.sum((y - np.mean(y)) ** 2))
    if np.isclose(total_sum, 0.0):
        return None
    return 1.0 - (residual_sum / total_sum)


def annotate_regression_stats(
    ax: plt.Axes,
    slope: float | None,
    intercept: float | None,
    r_squared: float | None,
) -> None:
    """Annotate a small regression summary in the top-left corner."""
    if slope is None or intercept is None:
        return
    lines = [f"y = {slope:.3f}x + {intercept:.3f}"]
    if r_squared is not None:
        lines.append(f"$R^2$ = {r_squared:.3f}")
    ax.text(
        0.03,
        0.97,
        "\n".join(lines),
        transform=ax.transAxes,
        va="top",
        ha="left",
        fontsize=8.5,
        color="#333333",
        bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.8, "pad": 2.0},
    )


def metric_arrays(
    case_rows: List[Dict[str, str]],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Extract core numeric arrays used across figures."""
    selected = select_complete_rows(
        case_rows,
        [
            "generated_node_count",
            "generated_edge_count",
            "verified_construction_steps",
            EXACT_COL,
            WL_COL,
        ],
    )
    node_count = np.asarray([row["generated_node_count"] for row in selected], dtype=float)
    edge_count = np.asarray([row["generated_edge_count"] for row in selected], dtype=float)
    construction_steps = np.asarray([row["verified_construction_steps"] for row in selected], dtype=float)
    normalized_ged = np.asarray([row[EXACT_COL] for row in selected], dtype=float)
    wl_similarity = np.asarray([row[WL_COL] for row in selected], dtype=float)
    return node_count, edge_count, construction_steps, normalized_ged, wl_similarity


def ged_operation_totals(case_rows: List[Dict[str, str]]) -> tuple[List[str], np.ndarray]:
    """Aggregate the six GED operation counts across all successful cases."""
    operation_specs = [
        ("Node insertion", "ged_node_insertion_count"),
        ("Node deletion", "ged_node_deletion_count"),
        ("Node substitution", "ged_node_substitution_count"),
        ("Edge insertion", "ged_edge_insertion_count"),
        ("Edge deletion", "ged_edge_deletion_count"),
        ("Edge substitution", "ged_edge_substitution_count"),
    ]
    labels = [label for label, _ in operation_specs]
    totals = np.asarray(
        [
            sum(to_float(row.get(column, "")) or 0.0 for row in case_rows)
            for _, column in operation_specs
        ],
        dtype=float,
    )
    return labels, totals


def plot_node_edge_relationship(case_rows: List[Dict[str, str]], output_dir: Path) -> None:
    """Create a scatter plot for node count versus edge count."""
    selected = select_complete_rows(case_rows, ["generated_node_count", "generated_edge_count"])
    fig, ax = plt.subplots(figsize=(6.8, 5.2))
    style_axes(ax)

    if selected:
        x = np.asarray([row["generated_node_count"] for row in selected], dtype=float)
        y = np.asarray([row["generated_edge_count"] for row in selected], dtype=float)
        ax.scatter(x, y, s=34, alpha=0.7, color="#35608D", linewidths=0.0)
        add_regression_line(ax, x, y, color="#4A4A4A")

    ax.set_xlabel("Number of Nodes")
    ax.set_ylabel("Number of Edges")
    ax.set_title("Relationship Between Node Count and Edge Count")
    save_figure(fig, output_dir, "figure_1_node_edge_relationship")


def plot_performance_trends(case_rows: List[Dict[str, str]], output_dir: Path) -> None:
    """Create grouped median trend lines with a frequency histogram."""
    fig, ax = plt.subplots(figsize=(7.2, 5.2))
    style_axes(ax)
    hist_ax = ax.twinx()
    hist_ax.grid(False)
    hist_ax.spines["top"].set_visible(False)
    hist_ax.spines["left"].set_visible(False)
    hist_ax.spines["right"].set_linewidth(0.8)
    hist_ax.tick_params(length=4, width=0.8, colors="#777777")

    exact_steps, exact_medians, exact_q1, exact_q3 = grouped_summary_by_step(
        case_rows,
        "verified_construction_steps",
        EXACT_COL,
        y_transform=lambda value: 1.0 - value,
    )
    wl_steps, wl_medians, wl_q1, wl_q3 = grouped_summary_by_step(
        case_rows,
        "verified_construction_steps",
        WL_COL,
    )
    exact_accept_steps, exact_accept_medians, _, _ = grouped_summary_by_step(
        case_rows,
        "verified_construction_steps",
        EXACT_ACCEPT_COL,
        y_transform=lambda value: 1.0 - value,
    )
    wl_accept_steps, wl_accept_medians, _, _ = grouped_summary_by_step(
        case_rows,
        "verified_construction_steps",
        WL_ACCEPT_COL,
    )
    frequency_rows = select_complete_rows(case_rows, ["verified_construction_steps"])
    if frequency_rows:
        all_steps = np.asarray(
            [row["verified_construction_steps"] for row in frequency_rows],
            dtype=float,
        )
        rounded_steps = np.rint(all_steps).astype(int)
        unique_steps, counts = np.unique(rounded_steps, return_counts=True)
        hist_ax.bar(
            unique_steps,
            counts,
            width=0.85,
            color="#D9D9D9",
            alpha=0.6,
            edgecolor="none",
            zorder=0,
        )
        hist_ax.set_ylabel("Case Count", color="#666666")
        hist_ax.set_ylim(0, max(counts) * 1.2)

    if exact_steps.size > 0:
        ax.plot(
            exact_steps,
            exact_medians,
            color="#C44E52",
            linewidth=1.7,
            marker="o",
            markersize=3.2,
            label="1 - Normalized GED",
        )

    if wl_steps.size > 0:
        ax.plot(
            wl_steps,
            wl_medians,
            color="#4C72B0",
            linewidth=1.7,
            linestyle="--",
            marker="s",
            markersize=3.2,
            label="WL Kernel Similarity",
        )
    if exact_accept_steps.size > 0:
        ax.plot(
            exact_accept_steps,
            exact_accept_medians,
            color="#DD8452",
            linewidth=1.5,
            marker="^",
            markersize=3.0,
            label="1 - Normalized GED (Accept-all vs Updated)",
        )
    if wl_accept_steps.size > 0:
        ax.plot(
            wl_accept_steps,
            wl_accept_medians,
            color="#55A868",
            linewidth=1.5,
            linestyle=":",
            marker="d",
            markersize=3.0,
            label="WL Similarity (Accept-all vs Updated)",
        )

    ax.set_xlabel("Construction Steps")
    ax.set_ylabel("Similarity Score")
    ax.set_title("Performance Trends Across Construction Complexity")
    ax.set_ylim(0.0, 1.05)
    ax.set_zorder(2)
    ax.patch.set_alpha(0.0)
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ax.legend(loc="best")
    save_figure(fig, output_dir, "figure_2_performance_trends")


def plot_similarity_density(case_rows: List[Dict[str, str]], output_dir: Path) -> None:
    """Create a dual-density plot for two structural similarity metrics."""
    selected = select_complete_rows(case_rows, [EXACT_COL, WL_COL])
    selected_accept = select_complete_rows(case_rows, [EXACT_ACCEPT_COL, WL_ACCEPT_COL])
    fig, ax = plt.subplots(figsize=(6.8, 5.2))
    style_axes(ax)

    if selected:
        exact_similarity = 1.0 - np.asarray([row[EXACT_COL] for row in selected], dtype=float)
        wl_similarity = np.asarray([row[WL_COL] for row in selected], dtype=float)
        all_series = [exact_similarity, wl_similarity]
        if selected_accept:
            exact_similarity_accept = 1.0 - np.asarray(
                [row[EXACT_ACCEPT_COL] for row in selected_accept],
                dtype=float,
            )
            wl_similarity_accept = np.asarray(
                [row[WL_ACCEPT_COL] for row in selected_accept],
                dtype=float,
            )
            all_series.extend([exact_similarity_accept, wl_similarity_accept])
        else:
            exact_similarity_accept = np.asarray([], dtype=float)
            wl_similarity_accept = np.asarray([], dtype=float)
        lower_bound = max(0.0, min(series.min() for series in all_series if series.size > 0) - 0.05)
        upper_bound = min(1.0, max(series.max() for series in all_series if series.size > 0) + 0.05)
        x_grid = np.linspace(lower_bound, upper_bound, 400)

        if exact_similarity.size >= 2 and not np.allclose(exact_similarity.min(), exact_similarity.max()):
            exact_kde = gaussian_kde(exact_similarity)
            exact_density = exact_kde(x_grid)
            ax.plot(x_grid, exact_density, color="#C44E52", linewidth=1.6, label="1 - Normalized GED")
            ax.fill_between(x_grid, exact_density, color="#C44E52", alpha=0.18)

        if wl_similarity.size >= 2 and not np.allclose(wl_similarity.min(), wl_similarity.max()):
            wl_kde = gaussian_kde(wl_similarity)
            wl_density = wl_kde(x_grid)
            ax.plot(x_grid, wl_density, color="#4C72B0", linewidth=1.6, label="WL Kernel Similarity")
            ax.fill_between(x_grid, wl_density, color="#4C72B0", alpha=0.18)
        if exact_similarity_accept.size >= 2 and not np.allclose(
            exact_similarity_accept.min(),
            exact_similarity_accept.max(),
        ):
            exact_accept_kde = gaussian_kde(exact_similarity_accept)
            exact_accept_density = exact_accept_kde(x_grid)
            ax.plot(
                x_grid,
                exact_accept_density,
                color="#DD8452",
                linewidth=1.4,
                linestyle="--",
                label="1 - Normalized GED (Accept-all vs Updated)",
            )
        if wl_similarity_accept.size >= 2 and not np.allclose(
            wl_similarity_accept.min(),
            wl_similarity_accept.max(),
        ):
            wl_accept_kde = gaussian_kde(wl_similarity_accept)
            wl_accept_density = wl_accept_kde(x_grid)
            ax.plot(
                x_grid,
                wl_accept_density,
                color="#55A868",
                linewidth=1.4,
                linestyle="--",
                label="WL Similarity (Accept-all vs Updated)",
            )

        ax.set_xlim(lower_bound, upper_bound)

    ax.set_xlabel("Similarity Score")
    ax.set_ylabel("Density")
    ax.set_title("Distribution of Structural Performance Metrics")
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ax.legend(loc="best")
    save_figure(fig, output_dir, "figure_3_similarity_density")


def plot_ged_vs_wl(case_rows: List[Dict[str, str]], output_dir: Path) -> None:
    """Create side-by-side GED-vs-WL scatter plots for both comparison modes."""
    fig, axes = plt.subplots(1, 2, figsize=(12.2, 5.2), sharey=True)

    def draw_panel(ax: plt.Axes, x_col: str, y_col: str, title: str) -> None:
        style_axes(ax)
        selected_rows = [
            row
            for row in case_rows
            if to_float(row.get(x_col, "")) is not None
            and to_float(row.get(y_col, "")) is not None
        ]
        if not selected_rows:
            ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
            ax.set_title(title)
            ax.set_xlabel("1 - Normalized GED")
            return

        normalized_ged = np.asarray([to_float(row.get(x_col, "")) for row in selected_rows], dtype=float)
        x = 1.0 - normalized_ged
        y = np.asarray([to_float(row.get(y_col, "")) for row in selected_rows], dtype=float)
        outlier_mask = y <= np.quantile(y, 0.1)
        regular_mask = ~outlier_mask

        if np.any(regular_mask):
            ax.scatter(x[regular_mask], y[regular_mask], s=30, alpha=0.7, color="#4C72B0", linewidths=0.0)
        if np.any(outlier_mask):
            ax.scatter(x[outlier_mask], y[outlier_mask], s=34, alpha=0.7, color="#C44E52", linewidths=0.0)

        params = add_regression_line(ax, x, y, color="#4A4A4A")
        r_squared = compute_r_squared(x, y)
        if params is not None:
            annotate_regression_stats(ax, params[0], params[1], r_squared)

        ax.set_title(title)
        ax.set_xlabel("1 - Normalized GED")

    draw_panel(axes[0], EXACT_COL, WL_COL, "Generated vs Updated")
    draw_panel(axes[1], EXACT_ACCEPT_COL, WL_ACCEPT_COL, "Accept-all vs Updated")
    axes[0].set_ylabel("WL Kernel Similarity")
    axes[0].set_ylim(0.0, 1.05)
    axes[1].set_ylim(0.0, 1.05)
    fig.suptitle("Relationship Between GED-Based and WL Similarity", y=1.02)
    save_figure(fig, output_dir, "figure_4_ged_vs_wl")


def plot_max_path_length_distribution(case_rows: List[Dict[str, str]], output_dir: Path) -> None:
    """Plot the distribution of maximum causal chain depth."""
    selected = select_complete_rows(case_rows, ["max_path_length"])
    fig, ax = plt.subplots(figsize=(6.8, 5.2))
    style_axes(ax)

    if selected:
        values = np.asarray([row["max_path_length"] for row in selected], dtype=float)
        bins = min(12, max(4, len(np.unique(values))))
        ax.hist(values, bins=bins, color="#4C72B0", alpha=0.75, edgecolor="white", linewidth=0.6)

    ax.set_xlabel("Max Path Length")
    ax.set_ylabel("Case Count")
    ax.set_title("Distribution of Maximum Causal Chain Depth")
    save_figure(fig, output_dir, "figure_5_max_path_length_distribution")


def plot_ged_operation_share(case_rows: List[Dict[str, str]], output_dir: Path) -> None:
    """Plot the global proportion of the six GED operation categories."""
    labels, totals = ged_operation_totals(case_rows)
    fig, ax = plt.subplots(figsize=(7.0, 5.8))
    color_map = ["#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B3", "#937860"]

    positive_mask = totals > 0
    if np.any(positive_mask):
        filtered_labels = [label for label, keep in zip(labels, positive_mask) if keep]
        filtered_totals = totals[positive_mask]
        total_sum = float(filtered_totals.sum())

        def autopct(pct: float) -> str:
            absolute = int(round(total_sum * pct / 100.0))
            return f"{pct:.1f}%\n(n={absolute})"

        wedges, _, autotexts = ax.pie(
            filtered_totals,
            labels=filtered_labels,
            colors=[color for color, keep in zip(color_map, positive_mask) if keep],
            startangle=90,
            counterclock=False,
            autopct=autopct,
            pctdistance=0.72,
            labeldistance=1.08,
            wedgeprops={"linewidth": 0.8, "edgecolor": "white"},
            textprops={"fontsize": 9},
        )
        for text in autotexts:
            text.set_color("#222222")
            text.set_fontsize(8.5)
        ax.axis("equal")
    else:
        ax.text(0.5, 0.5, "No GED operations available", ha="center", va="center", fontsize=11)
        ax.set_axis_off()

    ax.set_title("Proportion of GED Edit Operations")
    save_figure(fig, output_dir, "figure_6_ged_operation_share")


def grouped_boxplot_data(
    case_rows: List[Dict[str, str]],
    x_key: str,
    y_key: str,
    y_transform=None,
) -> tuple[List[str], List[List[float]]]:
    """Group continuous values by a discrete x-axis field for boxplots."""
    grouped: Dict[int, List[float]] = {}
    for row in case_rows:
        x_value = to_float(row.get(x_key, ""))
        y_value = to_float(row.get(y_key, ""))
        if x_value is None or y_value is None:
            continue
        bucket = int(round(x_value))
        metric_value = y_transform(y_value) if y_transform is not None else y_value
        grouped.setdefault(bucket, []).append(float(metric_value))

    labels = [str(key) for key in sorted(grouped)]
    series = [grouped[int(label)] for label in labels]
    return labels, series


def styled_boxplot(ax: plt.Axes, labels: List[str], series: List[List[float]], color: str) -> None:
    """Draw a clean publication-style boxplot."""
    if not series:
        return
    boxplot = ax.boxplot(
        series,
        tick_labels=labels,
        patch_artist=True,
        widths=0.6,
        medianprops={"color": "#222222", "linewidth": 1.2},
        whiskerprops={"color": "#555555", "linewidth": 0.9},
        capprops={"color": "#555555", "linewidth": 0.9},
        boxprops={"edgecolor": "#555555", "linewidth": 0.9},
        flierprops={
            "marker": "o",
            "markerfacecolor": "#999999",
            "markeredgecolor": "#999999",
            "markersize": 3,
            "alpha": 0.5,
        },
    )
    for patch in boxplot["boxes"]:
        patch.set_facecolor(color)
        patch.set_alpha(0.5)


def grouped_boxplot_by_label(
    case_rows: List[Dict[str, str]],
    label_key: str,
    value_key: str,
    y_transform=None,
) -> tuple[List[str], List[List[float]]]:
    """Group values by a categorical label for boxplots."""
    grouped: Dict[str, List[float]] = {}
    for row in case_rows:
        label = str(row.get(label_key, "")).strip()
        value = to_float(row.get(value_key, ""))
        if not label or value is None:
            continue
        metric_value = y_transform(value) if y_transform is not None else value
        grouped.setdefault(label, []).append(float(metric_value))

    labels = sorted(grouped, key=lambda item: (-len(grouped[item]), item))
    series = [grouped[label] for label in labels]
    return labels, series


def signed_node_difference_arrays(
    case_rows: List[Dict[str, str]],
    x_left_key: str,
    x_right_key: str,
    y_key: str,
    y_transform=None,
) -> tuple[np.ndarray, np.ndarray]:
    """Extract signed node-count difference and one metric array."""
    selected = select_complete_rows(case_rows, [x_left_key, x_right_key, y_key])
    if not selected:
        return np.asarray([], dtype=float), np.asarray([], dtype=float)
    x = np.asarray(
        [row[x_left_key] - row[x_right_key] for row in selected],
        dtype=float,
    )
    y = np.asarray([row[y_key] for row in selected], dtype=float)
    if y_transform is not None:
        y = y_transform(y)
    return x, y


def grouped_summary_by_signed_difference(
    x: np.ndarray,
    y: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Summarize one metric by exact signed node-count difference using median."""
    grouped: Dict[int, List[float]] = {}
    for x_value, y_value in zip(x, y):
        diff = int(round(float(x_value)))
        grouped.setdefault(diff, []).append(float(y_value))
    diffs = np.asarray(sorted(grouped), dtype=float)
    medians = np.asarray([np.median(grouped[int(diff)]) for diff in diffs], dtype=float)
    return diffs, medians


def signed_difference_bucket_label(value: int) -> str:
    """Map a signed node-count difference to a stable display bucket."""
    if value <= -4:
        return "<= -4"
    if value >= 4:
        return ">= +4"
    if value > 0:
        return f"+{value}"
    return str(value)


def grouped_boxplot_by_signed_difference_bucket(
    case_rows: List[Dict[str, str]],
    x_left_key: str,
    x_right_key: str,
    value_key: str,
    y_transform=None,
) -> tuple[List[str], List[List[float]]]:
    """Group values by signed node-difference buckets that preserve direction."""
    bucket_order = ["<= -4", "-3", "-2", "-1", "0", "+1", "+2", "+3", ">= +4"]
    grouped: Dict[str, List[float]] = {}
    for row in case_rows:
        left_count = to_float(row.get(x_left_key, ""))
        right_count = to_float(row.get(x_right_key, ""))
        value = to_float(row.get(value_key, ""))
        if left_count is None or right_count is None or value is None:
            continue
        diff = int(round(left_count - right_count))
        bucket = signed_difference_bucket_label(diff)
        metric_value = y_transform(value) if y_transform is not None else value
        grouped.setdefault(bucket, []).append(float(metric_value))

    labels = [label for label in bucket_order if label in grouped]
    series = [grouped[label] for label in labels]
    return labels, series


def signed_count_difference_arrays(
    case_rows: List[Dict[str, str]],
    x_left_key: str,
    x_right_key: str,
    y_key: str,
    y_transform=None,
) -> tuple[np.ndarray, np.ndarray]:
    """Extract a signed count difference and one metric array."""
    return signed_node_difference_arrays(
        case_rows,
        x_left_key,
        x_right_key,
        y_key,
        y_transform=y_transform,
    )


def plot_max_path_vs_wl(case_rows: List[Dict[str, str]], output_dir: Path) -> None:
    """Plot WL similarity grouped by maximum path length for both comparison modes."""
    fig, axes = plt.subplots(2, 1, figsize=(7.2, 7.0), sharex=True)

    labels, series = grouped_boxplot_data(case_rows, "max_path_length", WL_COL)
    style_axes(axes[0])
    styled_boxplot(axes[0], labels, series, color="#4C72B0")
    axes[0].set_ylabel("WL Kernel Similarity")
    axes[0].set_title("Generated vs Updated")
    axes[0].set_ylim(0.0, 1.05)

    labels_accept, series_accept = grouped_boxplot_data(case_rows, "max_path_length", WL_ACCEPT_COL)
    style_axes(axes[1])
    styled_boxplot(axes[1], labels_accept, series_accept, color="#55A868")
    axes[1].set_ylabel("WL Kernel Similarity")
    axes[1].set_title("Accept-all vs Updated")
    axes[1].set_xlabel("Max Path Length")
    axes[1].set_ylim(0.0, 1.05)

    fig.suptitle("WL Similarity Across Maximum Causal Chain Depth", y=1.02)
    save_figure(fig, output_dir, "figure_7_max_path_vs_wl")


def plot_max_path_vs_exact_similarity(case_rows: List[Dict[str, str]], output_dir: Path) -> None:
    """Plot GED-based similarity grouped by maximum path length for both comparison modes."""
    fig, axes = plt.subplots(2, 1, figsize=(7.2, 7.0), sharex=True)

    labels, series = grouped_boxplot_data(
        case_rows,
        "max_path_length",
        EXACT_COL,
        y_transform=lambda value: 1.0 - value,
    )
    style_axes(axes[0])
    styled_boxplot(axes[0], labels, series, color="#C44E52")
    axes[0].set_ylabel("1 - Normalized GED")
    axes[0].set_title("Generated vs Updated")
    axes[0].set_ylim(0.0, 1.05)

    labels_accept, series_accept = grouped_boxplot_data(
        case_rows,
        "max_path_length",
        EXACT_ACCEPT_COL,
        y_transform=lambda value: 1.0 - value,
    )
    style_axes(axes[1])
    styled_boxplot(axes[1], labels_accept, series_accept, color="#DD8452")
    axes[1].set_ylabel("1 - Normalized GED")
    axes[1].set_title("Accept-all vs Updated")
    axes[1].set_xlabel("Max Path Length")
    axes[1].set_ylim(0.0, 1.05)

    fig.suptitle("GED-Based Similarity Across Maximum Causal Chain Depth", y=1.02)
    save_figure(fig, output_dir, "figure_8_max_path_vs_exact_similarity")


def plot_similarity_by_hazard_consequence(case_rows: List[Dict[str, str]], output_dir: Path) -> None:
    """Plot structural similarity metrics grouped by hazard consequence type."""
    fig, axes = plt.subplots(2, 2, figsize=(12.0, 8.2), sharex="col")

    wl_labels, wl_series = grouped_boxplot_by_label(case_rows, "hazard_consequence_type", WL_COL)
    wl_accept_labels, wl_accept_series = grouped_boxplot_by_label(
        case_rows, "hazard_consequence_type", WL_ACCEPT_COL
    )
    exact_labels, exact_series = grouped_boxplot_by_label(
        case_rows,
        "hazard_consequence_type",
        EXACT_COL,
        y_transform=lambda value: 1.0 - value,
    )
    exact_accept_labels, exact_accept_series = grouped_boxplot_by_label(
        case_rows,
        "hazard_consequence_type",
        EXACT_ACCEPT_COL,
        y_transform=lambda value: 1.0 - value,
    )

    style_axes(axes[0, 0])
    styled_boxplot(axes[0, 0], wl_labels, wl_series, color="#4C72B0")
    axes[0, 0].set_ylabel("WL Kernel Similarity")
    axes[0, 0].set_title("Generated vs Updated")
    axes[0, 0].set_ylim(0.0, 1.05)

    style_axes(axes[0, 1])
    styled_boxplot(axes[0, 1], wl_accept_labels, wl_accept_series, color="#55A868")
    axes[0, 1].set_title("Accept-all vs Updated")
    axes[0, 1].set_ylim(0.0, 1.05)

    style_axes(axes[1, 0])
    styled_boxplot(axes[1, 0], exact_labels, exact_series, color="#C44E52")
    axes[1, 0].set_ylabel("1 - Normalized GED")
    axes[1, 0].set_xlabel("Hazard Consequence Type")
    axes[1, 0].set_ylim(0.0, 1.05)
    axes[1, 0].tick_params(axis="x", rotation=25)

    style_axes(axes[1, 1])
    styled_boxplot(axes[1, 1], exact_accept_labels, exact_accept_series, color="#DD8452")
    axes[1, 1].set_xlabel("Hazard Consequence Type")
    axes[1, 1].set_ylim(0.0, 1.05)
    axes[1, 1].tick_params(axis="x", rotation=25)

    fig.suptitle("Similarity Score by Hazard Consequence Type", y=1.02)

    save_figure(fig, output_dir, "figure_9_similarity_by_hazard_consequence")


def plot_signed_node_difference_trends(
    case_rows: List[Dict[str, str]],
    output_dir: Path,
    *,
    x_left_key: str,
    x_right_key: str,
    wl_key: str,
    ged_key: str,
    x_axis_label: str,
    title_prefix: str,
    stem: str,
) -> None:
    """Plot signed node-count difference against similarity with side-specific trend lines."""

    def draw_panel(
        ax: plt.Axes,
        *,
        y_key: str,
        y_label: str,
        title: str,
        color_points: str,
        color_negative: str,
        color_positive: str,
        y_transform=None,
    ) -> None:
        style_axes(ax)
        x, y = signed_node_difference_arrays(
            case_rows,
            x_left_key,
            x_right_key,
            y_key,
            y_transform=y_transform,
        )
        if x.size == 0:
            ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
            ax.set_ylabel(y_label)
            ax.set_title(title)
            return

        ax.scatter(x, y, s=24, alpha=0.42, color=color_points, linewidths=0.0)
        ax.axvline(0.0, color="#666666", linestyle="--", linewidth=1.0, alpha=0.85)

        diff_values, medians = grouped_summary_by_signed_difference(x, y)
        negative_mask = diff_values < 0
        zero_mask = diff_values == 0
        positive_mask = diff_values > 0

        if np.any(negative_mask):
            ax.plot(
                diff_values[negative_mask],
                medians[negative_mask],
                color=color_negative,
                linewidth=2.0,
                marker="o",
                markersize=3.5,
                label="Negative side trend",
            )
        if np.any(zero_mask):
            ax.scatter(
                diff_values[zero_mask],
                medians[zero_mask],
                s=40,
                color="#333333",
                zorder=3,
                label="Zero difference",
            )
        if np.any(positive_mask):
            ax.plot(
                diff_values[positive_mask],
                medians[positive_mask],
                color=color_positive,
                linewidth=2.0,
                marker="o",
                markersize=3.5,
                label="Positive side trend",
            )

        x_span = max(abs(x.min()), abs(x.max()), 1.0)
        ax.set_xlim(-x_span - 0.5, x_span + 0.5)
        ax.set_ylim(0.0, 1.05)
        ax.set_ylabel(y_label)
        ax.set_title(title)
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            ax.legend(loc="best")

    fig, axes = plt.subplots(2, 1, figsize=(7.4, 7.4), sharex=True)
    draw_panel(
        axes[0],
        y_key=wl_key,
        y_label="WL Kernel Similarity",
        title=f"{title_prefix} vs WL Kernel Similarity",
        color_points="#9BB9D4",
        color_negative="#355C7D",
        color_positive="#4C72B0",
    )
    draw_panel(
        axes[1],
        y_key=ged_key,
        y_label="1 - Normalized GED",
        title=f"{title_prefix} vs 1 - Normalized GED",
        color_points="#E6B3B6",
        color_negative="#A23B45",
        color_positive="#C44E52",
        y_transform=lambda values: 1.0 - values,
    )
    axes[1].set_xlabel(x_axis_label)
    fig.suptitle(f"Directional Trend of Similarity vs {title_prefix}", y=1.02)
    save_figure(fig, output_dir, stem)


def plot_node_difference_vs_similarity_density(
    case_rows: List[Dict[str, str]],
    output_dir: Path,
    *,
    x_left_key: str,
    x_right_key: str,
    wl_key: str,
    ged_key: str,
    x_axis_label: str,
    title_prefix: str,
    stem: str,
) -> None:
    """Plot signed node-count difference against WL and normalized GED as 2D densities."""

    def draw_density_panel(
        ax: plt.Axes,
        *,
        y_key: str,
        y_label: str,
        color: str,
        title: str,
        y_transform=None,
    ) -> None:
        style_axes(ax)
        selected = select_complete_rows(
            case_rows,
            [x_left_key, x_right_key, y_key],
        )
        if not selected:
            ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
            ax.set_ylabel(y_label)
            ax.set_title(title)
            return

        x = np.asarray(
            [row[x_left_key] - row[x_right_key] for row in selected],
            dtype=float,
        )
        y = np.asarray([row[y_key] for row in selected], dtype=float)
        if y_transform is not None:
            y = y_transform(y)

        ax.scatter(x, y, s=24, alpha=0.45, color=color, linewidths=0.0, zorder=2)
        ax.axvline(0.0, color="#666666", linestyle="--", linewidth=1.0, alpha=0.85, zorder=1)

        can_fit_kde = (
            x.size >= 3
            and not np.allclose(x.min(), x.max())
            and not np.allclose(y.min(), y.max())
        )
        if can_fit_kde:
            try:
                values = np.vstack([x, y])
                kde = gaussian_kde(values)
                x_pad = max(0.5, 0.08 * max(abs(x.min()), abs(x.max()), 1.0))
                x_grid = np.linspace(x.min() - x_pad, x.max() + x_pad, 220)
                y_grid = np.linspace(max(0.0, y.min() - 0.05), min(1.0, y.max() + 0.05), 220)
                xx, yy = np.meshgrid(x_grid, y_grid)
                positions = np.vstack([xx.ravel(), yy.ravel()])
                density = kde(positions).reshape(xx.shape)
                ax.contourf(xx, yy, density, levels=10, cmap="Blues", alpha=0.35, zorder=0)
                ax.contour(xx, yy, density, levels=6, colors=color, linewidths=0.8, alpha=0.75, zorder=1)
            except np.linalg.LinAlgError:
                pass

        x_span = max(abs(x.min()), abs(x.max()), 1.0)
        ax.set_xlim(-x_span - 0.5, x_span + 0.5)
        ax.set_ylim(0.0, 1.05)
        ax.set_ylabel(y_label)
        ax.set_title(title)

    fig, axes = plt.subplots(2, 1, figsize=(7.4, 7.4), sharex=True)
    draw_density_panel(
        axes[0],
        y_key=wl_key,
        y_label="WL Kernel Similarity",
        color="#4C72B0",
        title=f"{title_prefix} vs WL Kernel Similarity",
    )
    draw_density_panel(
        axes[1],
        y_key=ged_key,
        y_label="1 - Normalized GED",
        color="#C44E52",
        title=f"{title_prefix} vs 1 - Normalized GED",
        y_transform=lambda values: 1.0 - values,
    )
    axes[1].set_xlabel(x_axis_label)
    fig.suptitle(f"Similarity Metrics vs {title_prefix}", y=1.02)
    save_figure(fig, output_dir, stem)


def plot_signed_node_difference_boxplots(
    case_rows: List[Dict[str, str]],
    output_dir: Path,
    *,
    x_left_key: str,
    x_right_key: str,
    wl_key: str,
    ged_key: str,
    x_axis_label: str,
    title_prefix: str,
    stem: str,
) -> None:
    """Plot similarity grouped by signed node-difference buckets."""
    fig, axes = plt.subplots(2, 1, figsize=(8.0, 7.2), sharex=True)

    wl_labels, wl_series = grouped_boxplot_by_signed_difference_bucket(
        case_rows,
        x_left_key,
        x_right_key,
        wl_key,
    )
    style_axes(axes[0])
    styled_boxplot(axes[0], wl_labels, wl_series, color="#4C72B0")
    axes[0].axvline(wl_labels.index("0") + 1, color="#666666", linestyle="--", linewidth=1.0, alpha=0.85) if "0" in wl_labels else None
    axes[0].set_ylabel("WL Kernel Similarity")
    axes[0].set_title(f"WL Kernel Similarity by {title_prefix} Bucket")
    axes[0].set_ylim(0.0, 1.05)

    ged_labels, ged_series = grouped_boxplot_by_signed_difference_bucket(
        case_rows,
        x_left_key,
        x_right_key,
        ged_key,
        y_transform=lambda value: 1.0 - value,
    )
    style_axes(axes[1])
    styled_boxplot(axes[1], ged_labels, ged_series, color="#C44E52")
    axes[1].axvline(ged_labels.index("0") + 1, color="#666666", linestyle="--", linewidth=1.0, alpha=0.85) if "0" in ged_labels else None
    axes[1].set_ylabel("1 - Normalized GED")
    axes[1].set_title(f"1 - Normalized GED by {title_prefix} Bucket")
    axes[1].set_xlabel(x_axis_label)
    axes[1].set_ylim(0.0, 1.05)

    fig.suptitle(f"Directional Distribution Across {title_prefix} Buckets", y=1.02)
    save_figure(fig, output_dir, stem)


def draw_raincloud_panel(
    ax: plt.Axes,
    labels: List[str],
    series: List[List[float]],
    *,
    violin_color: str,
    box_color: str,
    point_color: str,
    y_label: str,
    title: str,
) -> None:
    """Draw a raincloud-style panel using violin, box, and jittered raw points."""
    style_axes(ax)
    if not series:
        ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
        ax.set_ylabel(y_label)
        ax.set_title(title)
        return

    positions = np.arange(1, len(labels) + 1, dtype=float)
    violin = ax.violinplot(
        series,
        positions=positions,
        widths=0.9,
        showmeans=False,
        showmedians=False,
        showextrema=False,
    )
    for body in violin["bodies"]:
        body.set_facecolor(violin_color)
        body.set_edgecolor("none")
        body.set_alpha(0.28)

    boxplot = ax.boxplot(
        series,
        positions=positions,
        widths=0.28,
        patch_artist=True,
        showfliers=False,
        medianprops={"color": "#222222", "linewidth": 1.2},
        whiskerprops={"color": "#555555", "linewidth": 0.9},
        capprops={"color": "#555555", "linewidth": 0.9},
        boxprops={"edgecolor": "#555555", "linewidth": 0.9},
    )
    for patch in boxplot["boxes"]:
        patch.set_facecolor(box_color)
        patch.set_alpha(0.65)

    rng = np.random.default_rng(42)
    for index, values in enumerate(series, start=1):
        x_jitter = rng.uniform(-0.13, 0.13, size=len(values))
        ax.scatter(
            np.full(len(values), float(index)) + x_jitter,
            values,
            s=18,
            alpha=0.55,
            color=point_color,
            linewidths=0.0,
            zorder=3,
        )

    ax.set_xticks(positions, labels)
    ax.set_ylabel(y_label)
    ax.set_title(title)
    ax.set_ylim(0.0, 1.05)

    if "0" in labels:
        ax.axvline(labels.index("0") + 1, color="#666666", linestyle="--", linewidth=1.0, alpha=0.85)

    for xpos, values in zip(positions, series):
        ax.text(
            xpos,
            1.02,
            f"n={len(values)}",
            ha="center",
            va="bottom",
            fontsize=8,
            color="#444444",
        )


def plot_signed_node_difference_raincloud(
    case_rows: List[Dict[str, str]],
    output_dir: Path,
) -> None:
    """Plot a raincloud view for generated-vs-updated signed node-difference buckets."""
    fig, axes = plt.subplots(2, 1, figsize=(8.2, 7.6), sharex=True)

    wl_labels, wl_series = grouped_boxplot_by_signed_difference_bucket(
        case_rows,
        "generated_node_count",
        "updated_node_count",
        WL_COL,
    )
    draw_raincloud_panel(
        axes[0],
        wl_labels,
        wl_series,
        violin_color="#8FB3D9",
        box_color="#4C72B0",
        point_color="#355C7D",
        y_label="WL Kernel Similarity",
        title="Raincloud: WL by Signed Node-Difference Bucket",
    )

    ged_labels, ged_series = grouped_boxplot_by_signed_difference_bucket(
        case_rows,
        "generated_node_count",
        "updated_node_count",
        EXACT_COL,
        y_transform=lambda value: 1.0 - value,
    )
    draw_raincloud_panel(
        axes[1],
        ged_labels,
        ged_series,
        violin_color="#E7A7AC",
        box_color="#C44E52",
        point_color="#A23B45",
        y_label="1 - Normalized GED",
        title="Raincloud: 1 - Normalized GED by Signed Node-Difference Bucket",
    )
    axes[1].set_xlabel("Signed Node Count Difference Bucket (Generated - Updated)")
    fig.suptitle("Raincloud Distribution Across Signed Node-Difference Buckets", y=1.02)
    save_figure(fig, output_dir, "figure_30_signed_node_difference_raincloud")


def plot_signed_node_difference_binned_trends(
    case_rows: List[Dict[str, str]],
    output_dir: Path,
    *,
    x_left_key: str,
    x_right_key: str,
    wl_key: str,
    ged_key: str,
    x_axis_label: str,
    title_prefix: str,
    stem: str,
) -> None:
    """Plot signed node-count difference with scatter and binned median trend lines."""

    def draw_panel(
        ax: plt.Axes,
        *,
        y_key: str,
        y_label: str,
        title: str,
        scatter_color: str,
        trend_color: str,
        y_transform=None,
    ) -> None:
        style_axes(ax)
        x, y = signed_node_difference_arrays(
            case_rows,
            x_left_key,
            x_right_key,
            y_key,
            y_transform=y_transform,
        )
        if x.size == 0:
            ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
            ax.set_ylabel(y_label)
            ax.set_title(title)
            return

        ax.scatter(x, y, s=24, alpha=0.38, color=scatter_color, linewidths=0.0, zorder=2)
        ax.axvline(0.0, color="#666666", linestyle="--", linewidth=1.0, alpha=0.85, zorder=1)

        diff_values, medians = grouped_summary_by_signed_difference(x, y)
        ax.plot(
            diff_values,
            medians,
            color=trend_color,
            linewidth=2.2,
            marker="o",
            markersize=4.0,
            zorder=3,
        )

        x_span = max(abs(x.min()), abs(x.max()), 1.0)
        ax.set_xlim(-x_span - 0.5, x_span + 0.5)
        ax.set_ylim(0.0, 1.05)
        ax.set_ylabel(y_label)
        ax.set_title(title)

    fig, axes = plt.subplots(2, 1, figsize=(7.4, 7.4), sharex=True)
    draw_panel(
        axes[0],
        y_key=wl_key,
        y_label="WL Kernel Similarity",
        title=f"{title_prefix} vs WL Kernel Similarity",
        scatter_color="#AFC6DD",
        trend_color="#2E5E8A",
    )
    draw_panel(
        axes[1],
        y_key=ged_key,
        y_label="1 - Normalized GED",
        title=f"{title_prefix} vs 1 - Normalized GED",
        scatter_color="#E7B3B6",
        trend_color="#B03A44",
        y_transform=lambda values: 1.0 - values,
    )
    axes[1].set_xlabel(x_axis_label)
    fig.suptitle(f"Binned Trend of Similarity vs {title_prefix}", y=1.02)
    save_figure(fig, output_dir, stem)


def plot_signed_edge_difference_trends(
    case_rows: List[Dict[str, str]],
    output_dir: Path,
    *,
    x_left_key: str,
    x_right_key: str,
    wl_key: str,
    ged_key: str,
    x_axis_label: str,
    title_prefix: str,
    stem: str,
) -> None:
    """Plot signed edge-count difference against similarity with side-specific trend lines."""

    def draw_panel(
        ax: plt.Axes,
        *,
        y_key: str,
        y_label: str,
        title: str,
        color_points: str,
        color_negative: str,
        color_positive: str,
        y_transform=None,
    ) -> None:
        style_axes(ax)
        x, y = signed_count_difference_arrays(
            case_rows,
            x_left_key,
            x_right_key,
            y_key,
            y_transform=y_transform,
        )
        if x.size == 0:
            ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
            ax.set_ylabel(y_label)
            ax.set_title(title)
            return

        ax.scatter(x, y, s=24, alpha=0.42, color=color_points, linewidths=0.0)
        ax.axvline(0.0, color="#666666", linestyle="--", linewidth=1.0, alpha=0.85)

        diff_values, medians = grouped_summary_by_signed_difference(x, y)
        negative_mask = diff_values < 0
        zero_mask = diff_values == 0
        positive_mask = diff_values > 0

        if np.any(negative_mask):
            ax.plot(
                diff_values[negative_mask],
                medians[negative_mask],
                color=color_negative,
                linewidth=2.0,
                marker="o",
                markersize=3.5,
                label="Negative side trend",
            )
        if np.any(zero_mask):
            ax.scatter(
                diff_values[zero_mask],
                medians[zero_mask],
                s=40,
                color="#333333",
                zorder=3,
                label="Zero difference",
            )
        if np.any(positive_mask):
            ax.plot(
                diff_values[positive_mask],
                medians[positive_mask],
                color=color_positive,
                linewidth=2.0,
                marker="o",
                markersize=3.5,
                label="Positive side trend",
            )

        x_span = max(abs(x.min()), abs(x.max()), 1.0)
        ax.set_xlim(-x_span - 0.5, x_span + 0.5)
        ax.set_ylim(0.0, 1.05)
        ax.set_ylabel(y_label)
        ax.set_title(title)
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            ax.legend(loc="best")

    fig, axes = plt.subplots(2, 1, figsize=(7.4, 7.4), sharex=True)
    draw_panel(
        axes[0],
        y_key=wl_key,
        y_label="WL Kernel Similarity",
        title=f"{title_prefix} vs WL Kernel Similarity",
        color_points="#C2D3A5",
        color_negative="#5D7A1F",
        color_positive="#8AAE3F",
    )
    draw_panel(
        axes[1],
        y_key=ged_key,
        y_label="1 - Normalized GED",
        title=f"{title_prefix} vs 1 - Normalized GED",
        color_points="#F0C6A7",
        color_negative="#C7762B",
        color_positive="#E19A4C",
        y_transform=lambda values: 1.0 - values,
    )
    axes[1].set_xlabel(x_axis_label)
    fig.suptitle(f"Directional Trend of Similarity vs {title_prefix}", y=1.02)
    save_figure(fig, output_dir, stem)


def plot_signed_edge_difference_boxplots(
    case_rows: List[Dict[str, str]],
    output_dir: Path,
    *,
    x_left_key: str,
    x_right_key: str,
    wl_key: str,
    ged_key: str,
    x_axis_label: str,
    title_prefix: str,
    stem: str,
) -> None:
    """Plot similarity grouped by signed edge-difference buckets."""
    fig, axes = plt.subplots(2, 1, figsize=(8.0, 7.2), sharex=True)

    wl_labels, wl_series = grouped_boxplot_by_signed_difference_bucket(
        case_rows,
        x_left_key,
        x_right_key,
        wl_key,
    )
    style_axes(axes[0])
    styled_boxplot(axes[0], wl_labels, wl_series, color="#8AAE3F")
    axes[0].axvline(wl_labels.index("0") + 1, color="#666666", linestyle="--", linewidth=1.0, alpha=0.85) if "0" in wl_labels else None
    axes[0].set_ylabel("WL Kernel Similarity")
    axes[0].set_title(f"WL Kernel Similarity by {title_prefix} Bucket")
    axes[0].set_ylim(0.0, 1.05)

    ged_labels, ged_series = grouped_boxplot_by_signed_difference_bucket(
        case_rows,
        x_left_key,
        x_right_key,
        ged_key,
        y_transform=lambda value: 1.0 - value,
    )
    style_axes(axes[1])
    styled_boxplot(axes[1], ged_labels, ged_series, color="#E19A4C")
    axes[1].axvline(ged_labels.index("0") + 1, color="#666666", linestyle="--", linewidth=1.0, alpha=0.85) if "0" in ged_labels else None
    axes[1].set_ylabel("1 - Normalized GED")
    axes[1].set_title(f"1 - Normalized GED by {title_prefix} Bucket")
    axes[1].set_xlabel(x_axis_label)
    axes[1].set_ylim(0.0, 1.05)

    fig.suptitle(f"Directional Distribution Across {title_prefix} Buckets", y=1.02)
    save_figure(fig, output_dir, stem)


def plot_signed_edge_difference_binned_trends(
    case_rows: List[Dict[str, str]],
    output_dir: Path,
    *,
    x_left_key: str,
    x_right_key: str,
    wl_key: str,
    ged_key: str,
    x_axis_label: str,
    title_prefix: str,
    stem: str,
) -> None:
    """Plot signed edge-count difference with scatter and binned median trend lines."""

    def draw_panel(
        ax: plt.Axes,
        *,
        y_key: str,
        y_label: str,
        title: str,
        scatter_color: str,
        trend_color: str,
        y_transform=None,
    ) -> None:
        style_axes(ax)
        x, y = signed_count_difference_arrays(
            case_rows,
            x_left_key,
            x_right_key,
            y_key,
            y_transform=y_transform,
        )
        if x.size == 0:
            ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
            ax.set_ylabel(y_label)
            ax.set_title(title)
            return

        ax.scatter(x, y, s=24, alpha=0.38, color=scatter_color, linewidths=0.0, zorder=2)
        ax.axvline(0.0, color="#666666", linestyle="--", linewidth=1.0, alpha=0.85, zorder=1)

        diff_values, medians = grouped_summary_by_signed_difference(x, y)
        ax.plot(
            diff_values,
            medians,
            color=trend_color,
            linewidth=2.2,
            marker="o",
            markersize=4.0,
            zorder=3,
        )

        x_span = max(abs(x.min()), abs(x.max()), 1.0)
        ax.set_xlim(-x_span - 0.5, x_span + 0.5)
        ax.set_ylim(0.0, 1.05)
        ax.set_ylabel(y_label)
        ax.set_title(title)

    fig, axes = plt.subplots(2, 1, figsize=(7.4, 7.4), sharex=True)
    draw_panel(
        axes[0],
        y_key=wl_key,
        y_label="WL Kernel Similarity",
        title=f"{title_prefix} vs WL Kernel Similarity",
        scatter_color="#D4E0B9",
        trend_color="#6F8D29",
    )
    draw_panel(
        axes[1],
        y_key=ged_key,
        y_label="1 - Normalized GED",
        title=f"{title_prefix} vs 1 - Normalized GED",
        scatter_color="#F3D2B8",
        trend_color="#D28635",
        y_transform=lambda values: 1.0 - values,
    )
    axes[1].set_xlabel(x_axis_label)
    fig.suptitle(f"Binned Trend of Similarity vs {title_prefix}", y=1.02)
    save_figure(fig, output_dir, stem)


def plot_count_difference_density(
    case_rows: List[Dict[str, str]],
    output_dir: Path,
    *,
    x_left_key: str,
    x_right_key: str,
    wl_key: str,
    ged_key: str,
    x_axis_label: str,
    title_prefix: str,
    stem: str,
) -> None:
    """Plot signed count difference against similarity as 2D densities."""

    def draw_density_panel(
        ax: plt.Axes,
        *,
        y_key: str,
        y_label: str,
        color: str,
        title: str,
        y_transform=None,
    ) -> None:
        style_axes(ax)
        selected = select_complete_rows(case_rows, [x_left_key, x_right_key, y_key])
        if not selected:
            ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
            ax.set_ylabel(y_label)
            ax.set_title(title)
            return

        x = np.asarray([row[x_left_key] - row[x_right_key] for row in selected], dtype=float)
        y = np.asarray([row[y_key] for row in selected], dtype=float)
        if y_transform is not None:
            y = y_transform(y)

        ax.scatter(x, y, s=24, alpha=0.45, color=color, linewidths=0.0, zorder=2)
        ax.axvline(0.0, color="#666666", linestyle="--", linewidth=1.0, alpha=0.85, zorder=1)

        can_fit_kde = (
            x.size >= 3
            and not np.allclose(x.min(), x.max())
            and not np.allclose(y.min(), y.max())
        )
        if can_fit_kde:
            try:
                values = np.vstack([x, y])
                kde = gaussian_kde(values)
                x_pad = max(0.5, 0.08 * max(abs(x.min()), abs(x.max()), 1.0))
                x_grid = np.linspace(x.min() - x_pad, x.max() + x_pad, 220)
                y_grid = np.linspace(max(0.0, y.min() - 0.05), min(1.0, y.max() + 0.05), 220)
                xx, yy = np.meshgrid(x_grid, y_grid)
                positions = np.vstack([xx.ravel(), yy.ravel()])
                density = kde(positions).reshape(xx.shape)
                ax.contourf(xx, yy, density, levels=10, cmap="Greens", alpha=0.35, zorder=0)
                ax.contour(xx, yy, density, levels=6, colors=color, linewidths=0.8, alpha=0.75, zorder=1)
            except np.linalg.LinAlgError:
                pass

        x_span = max(abs(x.min()), abs(x.max()), 1.0)
        ax.set_xlim(-x_span - 0.5, x_span + 0.5)
        ax.set_ylim(0.0, 1.05)
        ax.set_ylabel(y_label)
        ax.set_title(title)

    fig, axes = plt.subplots(2, 1, figsize=(7.4, 7.4), sharex=True)
    draw_density_panel(
        axes[0],
        y_key=wl_key,
        y_label="WL Kernel Similarity",
        color="#6F8D29",
        title=f"{title_prefix} vs WL Kernel Similarity",
    )
    draw_density_panel(
        axes[1],
        y_key=ged_key,
        y_label="1 - Normalized GED",
        color="#D28635",
        title=f"{title_prefix} vs 1 - Normalized GED",
        y_transform=lambda values: 1.0 - values,
    )
    axes[1].set_xlabel(x_axis_label)
    fig.suptitle(f"Similarity Metrics vs {title_prefix}", y=1.02)
    save_figure(fig, output_dir, stem)


def plot_node_vs_edge_difference(
    case_rows: List[Dict[str, str]],
    output_dir: Path,
    *,
    node_left_key: str,
    node_right_key: str,
    edge_left_key: str,
    edge_right_key: str,
    title: str,
    x_label: str,
    y_label: str,
    stem: str,
) -> None:
    """Plot signed node-count difference against signed edge-count difference."""
    selected = select_complete_rows(
        case_rows,
        [node_left_key, node_right_key, edge_left_key, edge_right_key],
    )
    fig, ax = plt.subplots(figsize=(7.0, 6.0))
    style_axes(ax)

    if selected:
        x = np.asarray([row[node_left_key] - row[node_right_key] for row in selected], dtype=float)
        y = np.asarray([row[edge_left_key] - row[edge_right_key] for row in selected], dtype=float)
        ax.scatter(x, y, s=28, alpha=0.55, color="#4C72B0", linewidths=0.0)
        ax.axvline(0.0, color="#666666", linestyle="--", linewidth=1.0, alpha=0.85)
        ax.axhline(0.0, color="#666666", linestyle="--", linewidth=1.0, alpha=0.85)
        params = add_regression_line(ax, x, y, color="#4A4A4A")
        r_squared = compute_r_squared(x, y)
        if params is not None:
            annotate_regression_stats(ax, params[0], params[1], r_squared)
        x_span = max(abs(x.min()), abs(x.max()), 1.0)
        y_span = max(abs(y.min()), abs(y.max()), 1.0)
        ax.set_xlim(-x_span - 0.5, x_span + 0.5)
        ax.set_ylim(-y_span - 0.5, y_span + 0.5)

    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    ax.set_title(title)
    save_figure(fig, output_dir, stem)


def plot_total_count_difference_vs_similarity(
    case_rows: List[Dict[str, str]],
    output_dir: Path,
    *,
    node_left_key: str,
    node_right_key: str,
    edge_left_key: str,
    edge_right_key: str,
    wl_key: str,
    ged_key: str,
    x_axis_label: str,
    title_prefix: str,
    stem: str,
) -> None:
    """Plot signed total-count difference (nodes + edges) against similarity as 2D densities."""

    def draw_density_panel(
        ax: plt.Axes,
        *,
        y_key: str,
        y_label: str,
        title: str,
        color: str,
        cmap: str,
        y_transform=None,
    ) -> None:
        style_axes(ax)
        selected = select_complete_rows(
            case_rows,
            [node_left_key, node_right_key, edge_left_key, edge_right_key, y_key],
        )
        if not selected:
            ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
            ax.set_ylabel(y_label)
            ax.set_title(title)
            return

        x = np.asarray(
            [
                (row[node_left_key] + row[edge_left_key]) - (row[node_right_key] + row[edge_right_key])
                for row in selected
            ],
            dtype=float,
        )
        y = np.asarray([row[y_key] for row in selected], dtype=float)
        if y_transform is not None:
            y = y_transform(y)

        ax.scatter(x, y, s=26, alpha=0.45, color=color, linewidths=0.0, zorder=2)
        ax.axvline(0.0, color="#666666", linestyle="--", linewidth=1.0, alpha=0.85, zorder=1)

        can_fit_kde = (
            x.size >= 3
            and not np.allclose(x.min(), x.max())
            and not np.allclose(y.min(), y.max())
        )
        if can_fit_kde:
            try:
                values = np.vstack([x, y])
                kde = gaussian_kde(values)
                x_pad = max(0.5, 0.08 * max(abs(x.min()), abs(x.max()), 1.0))
                x_grid = np.linspace(x.min() - x_pad, x.max() + x_pad, 220)
                y_grid = np.linspace(max(0.0, y.min() - 0.05), min(1.0, y.max() + 0.05), 220)
                xx, yy = np.meshgrid(x_grid, y_grid)
                positions = np.vstack([xx.ravel(), yy.ravel()])
                density = kde(positions).reshape(xx.shape)
                ax.contourf(xx, yy, density, levels=10, cmap=cmap, alpha=0.35, zorder=0)
                ax.contour(xx, yy, density, levels=6, colors=color, linewidths=0.8, alpha=0.75, zorder=1)
            except np.linalg.LinAlgError:
                pass

        x_span = max(abs(x.min()), abs(x.max()), 1.0)
        ax.set_xlim(-x_span - 0.5, x_span + 0.5)
        ax.set_ylim(0.0, 1.05)
        ax.set_ylabel(y_label)
        ax.set_title(title)

    fig, axes = plt.subplots(2, 1, figsize=(7.4, 7.4), sharex=True)
    draw_density_panel(
        axes[0],
        y_key=wl_key,
        y_label="WL Kernel Similarity",
        title=f"{title_prefix} vs WL Kernel Similarity",
        color="#3B6A99",
        cmap="Blues",
    )
    draw_density_panel(
        axes[1],
        y_key=ged_key,
        y_label="1 - Normalized GED",
        title=f"{title_prefix} vs 1 - Normalized GED",
        color="#BA4A53",
        cmap="Reds",
        y_transform=lambda values: 1.0 - values,
    )
    axes[1].set_xlabel(x_axis_label)
    fig.suptitle(f"Similarity vs {title_prefix}", y=1.02)
    save_figure(fig, output_dir, stem)


def generate_all_figures(results_dir: Path, output_dir: Path | None = None) -> Path:
    """Generate the scientific figures for one evaluation results directory."""
    results_dir = results_dir.resolve()
    output_dir = ensure_output_dir((output_dir or (results_dir / "figures")).resolve())
    set_plot_style()
    clear_existing_figures(output_dir)

    case_rows = filter_ok_case_rows(read_csv_rows(results_dir / CASE_SCORE_FILENAME))
    has_generated_ged = has_numeric_metric(case_rows, EXACT_COL)
    has_accept_all_ged = has_numeric_metric(case_rows, EXACT_ACCEPT_COL)
    has_any_ged = has_generated_ged or has_accept_all_ged

    plot_node_edge_relationship(case_rows, output_dir)
    plot_performance_trends(case_rows, output_dir)
    plot_similarity_density(case_rows, output_dir)
    plot_max_path_length_distribution(case_rows, output_dir)
    plot_max_path_vs_wl(case_rows, output_dir)
    plot_similarity_by_hazard_consequence(case_rows, output_dir)
    if has_any_ged:
        plot_signed_node_difference_trends(
            case_rows,
            output_dir,
            x_left_key="generated_node_count",
            x_right_key="updated_node_count",
            wl_key=WL_COL,
            ged_key=EXACT_COL,
            x_axis_label="Node Count Difference (Generated - Updated)",
            title_prefix="Signed Node Difference (Generated - Updated)",
            stem="figure_10_signed_node_difference_trends",
        )
        plot_signed_node_difference_boxplots(
            case_rows,
            output_dir,
            x_left_key="generated_node_count",
            x_right_key="updated_node_count",
            wl_key=WL_COL,
            ged_key=EXACT_COL,
            x_axis_label="Signed Node Count Difference Bucket (Generated - Updated)",
            title_prefix="Signed Node Difference",
            stem="figure_11_signed_node_difference_boxplots",
        )
        plot_signed_node_difference_raincloud(case_rows, output_dir)
        plot_node_difference_vs_similarity_density(
            case_rows,
            output_dir,
            x_left_key="generated_node_count",
            x_right_key="updated_node_count",
            wl_key=WL_COL,
            ged_key=EXACT_COL,
            x_axis_label="Node Count Difference (Generated - Updated)",
            title_prefix="Signed Node Difference (Generated - Updated)",
            stem="figure_12_node_difference_vs_similarity_density",
        )
        plot_signed_node_difference_binned_trends(
            case_rows,
            output_dir,
            x_left_key="generated_node_count",
            x_right_key="updated_node_count",
            wl_key=WL_COL,
            ged_key=EXACT_COL,
            x_axis_label="Node Count Difference (Generated - Updated)",
            title_prefix="Signed Node Difference (Generated - Updated)",
            stem="figure_13_signed_node_difference_binned_trends",
        )
        plot_signed_edge_difference_trends(
            case_rows,
            output_dir,
            x_left_key="generated_edge_count",
            x_right_key="updated_edge_count",
            wl_key=WL_COL,
            ged_key=EXACT_COL,
            x_axis_label="Edge Count Difference (Generated - Updated)",
            title_prefix="Signed Edge Difference (Generated - Updated)",
            stem="figure_18_signed_edge_difference_trends",
        )
        plot_signed_edge_difference_boxplots(
            case_rows,
            output_dir,
            x_left_key="generated_edge_count",
            x_right_key="updated_edge_count",
            wl_key=WL_COL,
            ged_key=EXACT_COL,
            x_axis_label="Signed Edge Count Difference Bucket (Generated - Updated)",
            title_prefix="Signed Edge Difference",
            stem="figure_19_signed_edge_difference_boxplots",
        )
        plot_count_difference_density(
            case_rows,
            output_dir,
            x_left_key="generated_edge_count",
            x_right_key="updated_edge_count",
            wl_key=WL_COL,
            ged_key=EXACT_COL,
            x_axis_label="Edge Count Difference (Generated - Updated)",
            title_prefix="Signed Edge Difference (Generated - Updated)",
            stem="figure_20_edge_difference_vs_similarity_density",
        )
        plot_signed_edge_difference_binned_trends(
            case_rows,
            output_dir,
            x_left_key="generated_edge_count",
            x_right_key="updated_edge_count",
            wl_key=WL_COL,
            ged_key=EXACT_COL,
            x_axis_label="Edge Count Difference (Generated - Updated)",
            title_prefix="Signed Edge Difference (Generated - Updated)",
            stem="figure_21_signed_edge_difference_binned_trends",
        )
        plot_node_vs_edge_difference(
            case_rows,
            output_dir,
            node_left_key="generated_node_count",
            node_right_key="updated_node_count",
            edge_left_key="generated_edge_count",
            edge_right_key="updated_edge_count",
            title="Signed Node Difference vs Signed Edge Difference (Generated - Updated)",
            x_label="Node Count Difference (Generated - Updated)",
            y_label="Edge Count Difference (Generated - Updated)",
            stem="figure_22_node_vs_edge_difference",
        )
        plot_total_count_difference_vs_similarity(
            case_rows,
            output_dir,
            node_left_key="generated_node_count",
            node_right_key="updated_node_count",
            edge_left_key="generated_edge_count",
            edge_right_key="updated_edge_count",
            wl_key=WL_COL,
            ged_key=EXACT_COL,
            x_axis_label="Total Count Difference ((Nodes + Edges) Generated - Updated)",
            title_prefix="Signed Total Count Difference (Generated - Updated)",
            stem="figure_23_total_count_difference_vs_similarity",
        )
        if has_accept_all_ged:
            plot_signed_node_difference_trends(
                case_rows,
                output_dir,
                x_left_key="accept_all_node_count",
                x_right_key="updated_node_count",
                wl_key=WL_ACCEPT_COL,
                ged_key=EXACT_ACCEPT_COL,
                x_axis_label="Node Count Difference (Accept-all - Updated)",
                title_prefix="Signed Node Difference (Accept-all - Updated)",
                stem="figure_14_accept_all_signed_node_difference_trends",
            )
            plot_signed_node_difference_boxplots(
                case_rows,
                output_dir,
                x_left_key="accept_all_node_count",
                x_right_key="updated_node_count",
                wl_key=WL_ACCEPT_COL,
                ged_key=EXACT_ACCEPT_COL,
                x_axis_label="Signed Node Count Difference Bucket (Accept-all - Updated)",
                title_prefix="Accept-all Signed Node Difference",
                stem="figure_15_accept_all_signed_node_difference_boxplots",
            )
            plot_node_difference_vs_similarity_density(
                case_rows,
                output_dir,
                x_left_key="accept_all_node_count",
                x_right_key="updated_node_count",
                wl_key=WL_ACCEPT_COL,
                ged_key=EXACT_ACCEPT_COL,
                x_axis_label="Node Count Difference (Accept-all - Updated)",
                title_prefix="Signed Node Difference (Accept-all - Updated)",
                stem="figure_16_accept_all_node_difference_vs_similarity_density",
            )
            plot_signed_node_difference_binned_trends(
                case_rows,
                output_dir,
                x_left_key="accept_all_node_count",
                x_right_key="updated_node_count",
                wl_key=WL_ACCEPT_COL,
                ged_key=EXACT_ACCEPT_COL,
                x_axis_label="Node Count Difference (Accept-all - Updated)",
                title_prefix="Signed Node Difference (Accept-all - Updated)",
                stem="figure_17_accept_all_signed_node_difference_binned_trends",
            )
            plot_signed_edge_difference_trends(
                case_rows,
                output_dir,
                x_left_key="accept_all_edge_count",
                x_right_key="updated_edge_count",
                wl_key=WL_ACCEPT_COL,
                ged_key=EXACT_ACCEPT_COL,
                x_axis_label="Edge Count Difference (Accept-all - Updated)",
                title_prefix="Signed Edge Difference (Accept-all - Updated)",
                stem="figure_23_accept_all_signed_edge_difference_trends",
            )
            plot_signed_edge_difference_boxplots(
                case_rows,
                output_dir,
                x_left_key="accept_all_edge_count",
                x_right_key="updated_edge_count",
                wl_key=WL_ACCEPT_COL,
                ged_key=EXACT_ACCEPT_COL,
                x_axis_label="Signed Edge Count Difference Bucket (Accept-all - Updated)",
                title_prefix="Accept-all Signed Edge Difference",
                stem="figure_24_accept_all_signed_edge_difference_boxplots",
            )
            plot_count_difference_density(
                case_rows,
                output_dir,
                x_left_key="accept_all_edge_count",
                x_right_key="updated_edge_count",
                wl_key=WL_ACCEPT_COL,
                ged_key=EXACT_ACCEPT_COL,
                x_axis_label="Edge Count Difference (Accept-all - Updated)",
                title_prefix="Signed Edge Difference (Accept-all - Updated)",
                stem="figure_25_accept_all_edge_difference_vs_similarity_density",
            )
            plot_signed_edge_difference_binned_trends(
                case_rows,
                output_dir,
                x_left_key="accept_all_edge_count",
                x_right_key="updated_edge_count",
                wl_key=WL_ACCEPT_COL,
                ged_key=EXACT_ACCEPT_COL,
                x_axis_label="Edge Count Difference (Accept-all - Updated)",
                title_prefix="Signed Edge Difference (Accept-all - Updated)",
                stem="figure_26_accept_all_signed_edge_difference_binned_trends",
            )
            plot_node_vs_edge_difference(
                case_rows,
                output_dir,
                node_left_key="accept_all_node_count",
                node_right_key="updated_node_count",
                edge_left_key="accept_all_edge_count",
                edge_right_key="updated_edge_count",
                title="Signed Node Difference vs Signed Edge Difference (Accept-all - Updated)",
                x_label="Node Count Difference (Accept-all - Updated)",
                y_label="Edge Count Difference (Accept-all - Updated)",
                stem="figure_28_accept_all_node_vs_edge_difference",
            )
            plot_total_count_difference_vs_similarity(
                case_rows,
                output_dir,
                node_left_key="accept_all_node_count",
                node_right_key="updated_node_count",
                edge_left_key="accept_all_edge_count",
                edge_right_key="updated_edge_count",
                wl_key=WL_ACCEPT_COL,
                ged_key=EXACT_ACCEPT_COL,
                x_axis_label="Total Count Difference ((Nodes + Edges) Accept-all - Updated)",
                title_prefix="Signed Total Count Difference (Accept-all - Updated)",
                stem="figure_29_accept_all_total_count_difference_vs_similarity",
            )
        plot_ged_vs_wl(case_rows, output_dir)
        plot_max_path_vs_exact_similarity(case_rows, output_dir)
    if has_any_ged or has_numeric_metric(case_rows, "ged_node_insertion_count"):
        plot_ged_operation_share(case_rows, output_dir)

    return output_dir


def main() -> Path:
    """CLI entrypoint for figure generation."""
    args = parse_args()
    output_dir = generate_all_figures(args.results_dir, args.output_dir)
    print(f"Saved evaluation figures to {output_dir}.")
    return output_dir


if __name__ == "__main__":
    main()
