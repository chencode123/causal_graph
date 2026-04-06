from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Dict, Iterable, List

import matplotlib.pyplot as plt
import numpy as np
from scipy.stats import gaussian_kde


CASE_SCORE_FILENAME = "case_scores.csv"

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


def metric_arrays(case_rows: List[Dict[str, str]]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Extract core numeric arrays used across figures."""
    selected = select_complete_rows(
        case_rows,
        [
            "generated_node_count",
            "generated_edge_count",
            "verified_construction_steps",
            "normalized_graph_edit_distance",
            "structural_similarity",
        ],
    )
    node_count = np.asarray([row["generated_node_count"] for row in selected], dtype=float)
    edge_count = np.asarray([row["generated_edge_count"] for row in selected], dtype=float)
    construction_steps = np.asarray([row["verified_construction_steps"] for row in selected], dtype=float)
    normalized_ged = np.asarray([row["normalized_graph_edit_distance"] for row in selected], dtype=float)
    wl_similarity = np.asarray([row["structural_similarity"] for row in selected], dtype=float)
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
        "normalized_graph_edit_distance",
        y_transform=lambda value: 1.0 - value,
    )
    wl_steps, wl_medians, wl_q1, wl_q3 = grouped_summary_by_step(
        case_rows,
        "verified_construction_steps",
        "structural_similarity",
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

    ax.set_xlabel("Construction Steps")
    ax.set_ylabel("Similarity Score")
    ax.set_title("Performance Trends Across Construction Complexity")
    ax.set_ylim(0.0, 1.05)
    ax.set_zorder(2)
    ax.patch.set_alpha(0.0)
    ax.legend(loc="best")
    save_figure(fig, output_dir, "figure_2_performance_trends")


def plot_similarity_density(case_rows: List[Dict[str, str]], output_dir: Path) -> None:
    """Create a dual-density plot for two structural similarity metrics."""
    selected = select_complete_rows(case_rows, ["normalized_graph_edit_distance", "structural_similarity"])
    fig, ax = plt.subplots(figsize=(6.8, 5.2))
    style_axes(ax)

    if selected:
        exact_similarity = 1.0 - np.asarray([row["normalized_graph_edit_distance"] for row in selected], dtype=float)
        wl_similarity = np.asarray([row["structural_similarity"] for row in selected], dtype=float)
        lower_bound = max(0.0, min(exact_similarity.min(), wl_similarity.min()) - 0.05)
        upper_bound = min(1.0, max(exact_similarity.max(), wl_similarity.max()) + 0.05)
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

        ax.set_xlim(lower_bound, upper_bound)

    ax.set_xlabel("Similarity Score")
    ax.set_ylabel("Density")
    ax.set_title("Distribution of Structural Performance Metrics")
    ax.legend(loc="best")
    save_figure(fig, output_dir, "figure_3_similarity_density")


def plot_ged_vs_wl(case_rows: List[Dict[str, str]], output_dir: Path) -> None:
    """Create a scatter plot for GED-based similarity versus WL kernel similarity."""
    selected_rows = [
        row
        for row in case_rows
        if to_float(row.get("normalized_graph_edit_distance", "")) is not None
        and to_float(row.get("structural_similarity", "")) is not None
    ]
    fig, ax = plt.subplots(figsize=(6.8, 5.2))
    style_axes(ax)

    if selected_rows:
        normalized_ged = np.asarray(
            [to_float(row.get("normalized_graph_edit_distance", "")) for row in selected_rows],
            dtype=float,
        )
        x = 1.0 - normalized_ged
        y = np.asarray(
            [to_float(row.get("structural_similarity", "")) for row in selected_rows],
            dtype=float,
        )
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

    ax.set_xlabel("1 - Normalized GED")
    ax.set_ylabel("WL Kernel Similarity")
    ax.set_title("Relationship Between GED-Based and WL Similarity")
    ax.set_ylim(0.0, 1.05)
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


def plot_max_path_vs_wl(case_rows: List[Dict[str, str]], output_dir: Path) -> None:
    """Plot WL similarity grouped by maximum path length."""
    fig, ax = plt.subplots(figsize=(6.8, 5.2))
    style_axes(ax)

    labels, series = grouped_boxplot_data(case_rows, "max_path_length", "structural_similarity")
    styled_boxplot(ax, labels, series, color="#4C72B0")

    ax.set_xlabel("Max Path Length")
    ax.set_ylabel("WL Kernel Similarity")
    ax.set_title("WL Similarity Across Maximum Causal Chain Depth")
    ax.set_ylim(0.0, 1.05)
    save_figure(fig, output_dir, "figure_7_max_path_vs_wl")


def plot_max_path_vs_exact_similarity(case_rows: List[Dict[str, str]], output_dir: Path) -> None:
    """Plot GED-based similarity grouped by maximum path length."""
    fig, ax = plt.subplots(figsize=(6.8, 5.2))
    style_axes(ax)

    labels, series = grouped_boxplot_data(
        case_rows,
        "max_path_length",
        "normalized_graph_edit_distance",
        y_transform=lambda value: 1.0 - value,
    )
    styled_boxplot(ax, labels, series, color="#C44E52")

    ax.set_xlabel("Max Path Length")
    ax.set_ylabel("1 - Normalized GED")
    ax.set_title("GED-Based Similarity Across Maximum Causal Chain Depth")
    ax.set_ylim(0.0, 1.05)
    save_figure(fig, output_dir, "figure_8_max_path_vs_exact_similarity")


def plot_similarity_by_hazard_consequence(case_rows: List[Dict[str, str]], output_dir: Path) -> None:
    """Plot structural similarity metrics grouped by hazard consequence type."""
    fig, axes = plt.subplots(2, 1, figsize=(9.0, 7.8), sharex=True)

    wl_labels, wl_series = grouped_boxplot_by_label(
        case_rows,
        "hazard_consequence_type",
        "structural_similarity",
    )
    exact_labels, exact_series = grouped_boxplot_by_label(
        case_rows,
        "hazard_consequence_type",
        "normalized_graph_edit_distance",
        y_transform=lambda value: 1.0 - value,
    )

    style_axes(axes[0])
    styled_boxplot(axes[0], wl_labels, wl_series, color="#4C72B0")
    axes[0].set_ylabel("WL Kernel Similarity")
    axes[0].set_title("Similarity Score by Hazard Consequence Type")
    axes[0].set_ylim(0.0, 1.05)

    style_axes(axes[1])
    styled_boxplot(axes[1], exact_labels, exact_series, color="#C44E52")
    axes[1].set_ylabel("1 - Normalized GED")
    axes[1].set_xlabel("Hazard Consequence Type")
    axes[1].set_ylim(0.0, 1.05)
    axes[1].tick_params(axis="x", rotation=25)

    save_figure(fig, output_dir, "figure_9_similarity_by_hazard_consequence")


def generate_all_figures(results_dir: Path, output_dir: Path | None = None) -> Path:
    """Generate the scientific figures for one evaluation results directory."""
    results_dir = results_dir.resolve()
    output_dir = ensure_output_dir((output_dir or (results_dir / "figures")).resolve())
    set_plot_style()
    clear_existing_figures(output_dir)

    case_rows = filter_ok_case_rows(read_csv_rows(results_dir / CASE_SCORE_FILENAME))

    plot_node_edge_relationship(case_rows, output_dir)
    plot_performance_trends(case_rows, output_dir)
    plot_similarity_density(case_rows, output_dir)
    plot_ged_vs_wl(case_rows, output_dir)
    plot_max_path_length_distribution(case_rows, output_dir)
    plot_ged_operation_share(case_rows, output_dir)
    plot_max_path_vs_wl(case_rows, output_dir)
    plot_max_path_vs_exact_similarity(case_rows, output_dir)
    plot_similarity_by_hazard_consequence(case_rows, output_dir)

    return output_dir


def main() -> Path:
    """CLI entrypoint for figure generation."""
    args = parse_args()
    output_dir = generate_all_figures(args.results_dir, args.output_dir)
    print(f"Saved evaluation figures to {output_dir}.")
    return output_dir


if __name__ == "__main__":
    main()
