from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


CASE_SCORE_FILENAME = "case_scores.csv"
SOFT_F1_API_FILENAME = "case_soft_f1_api_scores.csv"
SEMANTIC_FILENAME = "case_semantic_scores.csv"
SOFT_F1_ACCEPT_DIRNAME = "result_soft_f1_api_accept_all_vs_updated"
SOFT_F1_NO_REV_DIRNAME = "result_soft_f1_api"
WL_COLUMN = "structural_similarity_accept_all_vs_updated"
NORM_GED_COLUMN = "normalized_graph_edit_distance_accept_all_vs_updated"
WL_COLUMN_NO_REV = "structural_similarity"
NORM_GED_COLUMN_NO_REV = "normalized_graph_edit_distance"
DEFAULT_COMPARISON_ROOTS = [
    Path(r"runs\stability_test\rounds"),
    Path(r"runs\stability_test\rounds_with_few_shot"),
]
DEFAULT_COMPARISON_LABELS = ["No few-shot", "Few-shot"]
DEFAULT_OUTPUT_DIR = Path(r"runs\stability_test\figures_comparing_rounds")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a grouped violin plot that compares WL kernel similarity and "
            "1 - normalized GED for accept-all vs updated causal graphs across "
            "multiple stability result roots."
        )
    )
    parser.add_argument(
        "--comparison-roots",
        type=Path,
        nargs="+",
        default=DEFAULT_COMPARISON_ROOTS,
        help=(
            "Result roots to compare. Each root can be an experiment folder or "
            "a results directory containing timestamped outputs."
        ),
    )
    parser.add_argument(
        "--comparison-labels",
        nargs="+",
        default=DEFAULT_COMPARISON_LABELS,
        help="Display labels for --comparison-roots in the same order.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where the comparison figure will be written.",
    )
    return parser.parse_args()


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        return list(csv.DictReader(fp))


def to_float(value: str) -> float | None:
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def find_latest_case_scores(root: Path) -> Path:
    root = root.resolve()
    direct_candidate = root / CASE_SCORE_FILENAME
    if direct_candidate.exists():
        return direct_candidate

    results_candidate = root / "results"
    search_root = results_candidate if results_candidate.exists() else root
    candidates = list(search_root.rglob(CASE_SCORE_FILENAME))
    if not candidates:
        raise FileNotFoundError(f"Cannot find {CASE_SCORE_FILENAME} under {root}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def collect_similarity_metrics(case_scores_path: Path) -> dict[str, list[float]]:
    wl_values: list[float] = []
    ged_similarity_values: list[float] = []
    wl_no_rev_values: list[float] = []
    ged_no_rev_values: list[float] = []

    for row in read_csv_rows(case_scores_path):
        if str(row.get("status", "")).strip().lower() != "ok":
            continue
        wl_value = to_float(row.get(WL_COLUMN, ""))
        norm_ged_value = to_float(row.get(NORM_GED_COLUMN, ""))
        wl_no_rev = to_float(row.get(WL_COLUMN_NO_REV, ""))
        norm_ged_no_rev = to_float(row.get(NORM_GED_COLUMN_NO_REV, ""))
        if wl_value is not None:
            wl_values.append(wl_value)
        if norm_ged_value is not None:
            ged_similarity_values.append(1.0 - norm_ged_value)
        if wl_no_rev is not None:
            wl_no_rev_values.append(wl_no_rev)
        if norm_ged_no_rev is not None:
            ged_no_rev_values.append(1.0 - norm_ged_no_rev)

    return {
        "wl_kernel": wl_values,
        "one_minus_norm_ged": ged_similarity_values,
        "wl_kernel_no_rev": wl_no_rev_values,
        "one_minus_norm_ged_no_rev": ged_no_rev_values,
    }


def collect_soft_f1_api_metrics(case_scores_path: Path) -> dict[str, list[float]]:
    node_precision_values: list[float] = []
    node_recall_values: list[float] = []
    node_f1_values: list[float] = []
    edge_precision_values: list[float] = []
    edge_recall_values: list[float] = []
    edge_f1_values: list[float] = []

    for row in read_csv_rows(case_scores_path):
        if str(row.get("status", "")).strip().lower() != "ok":
            continue
        node_precision = to_float(row.get("soft_node_precision", ""))
        node_recall = to_float(row.get("soft_node_recall", ""))
        node_f1 = to_float(row.get("soft_node_f1", ""))
        edge_precision = to_float(row.get("soft_edge_precision", ""))
        edge_recall = to_float(row.get("soft_edge_recall", ""))
        edge_f1 = to_float(row.get("soft_edge_f1", ""))
        if node_precision is not None:
            node_precision_values.append(node_precision)
        if node_recall is not None:
            node_recall_values.append(node_recall)
        if node_f1 is not None:
            node_f1_values.append(node_f1)
        if edge_precision is not None:
            edge_precision_values.append(edge_precision)
        if edge_recall is not None:
            edge_recall_values.append(edge_recall)
        if edge_f1 is not None:
            edge_f1_values.append(edge_f1)

    return {
        "soft_node_precision": node_precision_values,
        "soft_node_recall": node_recall_values,
        "soft_node_f1": node_f1_values,
        "soft_edge_precision": edge_precision_values,
        "soft_edge_recall": edge_recall_values,
        "soft_edge_f1": edge_f1_values,
    }


def collect_semantic_metrics(case_scores_path: Path) -> dict[str, list[float]]:
    semantic_accept_all_values: list[float] = []
    semantic_no_rev_values: list[float] = []

    for row in read_csv_rows(case_scores_path):
        if str(row.get("status", "")).strip().lower() != "ok":
            continue
        semantic_accept_all = to_float(row.get("semantic_similarity_accept_all_vs_updated", ""))
        semantic_no_rev = to_float(row.get("semantic_similarity_generated_vs_updated", ""))
        if semantic_accept_all is not None:
            semantic_accept_all_values.append(semantic_accept_all)
        if semantic_no_rev is not None:
            semantic_no_rev_values.append(semantic_no_rev)

    return {
        "semantic_accept_all_vs_updated": semantic_accept_all_values,
        "semantic_no_rev": semantic_no_rev_values,
    }


def find_latest_named_csv(root: Path, filename: str) -> Path:
    root = root.resolve()
    direct_candidate = root / filename
    if direct_candidate.exists():
        return direct_candidate

    candidates = list(root.rglob(filename))
    if not candidates:
        raise FileNotFoundError(f"Cannot find {filename} under {root}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def find_latest_soft_f1_accept_csv(root: Path) -> Path:
    root = root.resolve()
    preferred_root = root / SOFT_F1_ACCEPT_DIRNAME
    if preferred_root.exists():
        return find_latest_named_csv(preferred_root, SOFT_F1_API_FILENAME)
    return find_latest_named_csv(root, SOFT_F1_API_FILENAME)


def find_latest_soft_f1_no_rev_csv(root: Path) -> Path | None:
    root = root.resolve()
    preferred_root = root / SOFT_F1_NO_REV_DIRNAME
    if not preferred_root.exists():
        return None
    try:
        return find_latest_named_csv(preferred_root, SOFT_F1_API_FILENAME)
    except FileNotFoundError:
        return None


def plot_similarity_comparison(
    comparison_roots: list[Path],
    comparison_labels: list[str],
    output_dir: Path,
) -> Path:
    if len(comparison_roots) != len(comparison_labels):
        raise ValueError("--comparison-roots and --comparison-labels must have the same length.")

    resolved_csv_paths = [find_latest_case_scores(root) for root in comparison_roots]
    metrics_by_label = {
        label: collect_similarity_metrics(csv_path)
        for label, csv_path in zip(comparison_labels, resolved_csv_paths)
    }

    output_dir = ensure_dir(output_dir.resolve())

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
            "font.sans-serif": ["Arial", "Times New Roman", "DejaVu Sans"],
            "font.size": 11,
            "axes.titlesize": 13,
            "axes.labelsize": 11,
            "legend.fontsize": 10,
        }
    )

    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    ax.grid(axis="y", color="#E6E6E6", linewidth=0.8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_linewidth(0.8)
    ax.spines["bottom"].set_linewidth(0.8)
    ax.tick_params(length=4, width=0.8)

    # 3 conditions: No Revision / Revision / Revision + FS
    THREE_COLORS = ["#A8A8A8", "#5E81AC", "#2E4A6E"]
    CONDITION_LABELS = ["No Revision", "Revision", "Revision + FS"]
    no_rev_key_map = {"wl_kernel": "wl_kernel_no_rev", "one_minus_norm_ged": "one_minus_norm_ged_no_rev"}

    metric_specs = [
        ("wl_kernel", "WLS"),
        ("one_minus_norm_ged", "GES"),
    ]

    group_centers = np.arange(len(metric_specs), dtype=float) * 3.2
    offsets = np.array([-0.7, 0.0, 0.7], dtype=float)
    width = 0.55

    legend_handles = [
        plt.Line2D([0], [0], color=c, linewidth=10, alpha=0.82)
        for c in THREE_COLORS
    ]
    legend_labels_list = list(CONDITION_LABELS)
    mean_handle = None

    for metric_index, (metric_key, metric_name) in enumerate(metric_specs):
        no_rev_key = no_rev_key_map[metric_key]
        all_series = [
            metrics_by_label[comparison_labels[0]][no_rev_key],
            metrics_by_label[comparison_labels[0]][metric_key],
            metrics_by_label[comparison_labels[1]][metric_key],
        ]
        for dataset_index, series in enumerate(all_series):
            if not series:
                continue
            position = float(group_centers[metric_index] + offsets[dataset_index])
            color = THREE_COLORS[dataset_index]
            violin = ax.violinplot(
                [series],
                positions=[position],
                widths=width,
                showmeans=False,
                showmedians=False,
                showextrema=False,
            )
            for body in violin["bodies"]:
                body.set_facecolor(color)
                body.set_edgecolor("#444444")
                body.set_linewidth(0.9)
                body.set_alpha(0.78)

            mean_value = float(np.mean(series))
            ax.scatter(
                [position], [mean_value], marker="D", s=50,
                facecolor="white", edgecolor="#111111", linewidth=0.9, zorder=4,
            )
            if mean_handle is None:
                mean_handle = plt.Line2D(
                    [0], [0], marker="D", linestyle="",
                    markerfacecolor="white", markeredgecolor="#111111",
                    color="#111111", markersize=6,
                )
            ax.text(
                position, min(mean_value + 0.035, 1.02), f"{mean_value:.3f}",
                ha="center", va="bottom", fontsize=8.5, color="#222222",
            )

    ax.set_xticks(group_centers)
    ax.set_xticklabels([metric_name for _, metric_name in metric_specs])
    ax.set_ylim(0.0, 1.05)
    ax.set_ylabel("Score")
    ax.set_xlabel("")

    if mean_handle is not None:
        legend_handles.append(mean_handle)
        legend_labels_list.append("Mean")
    if legend_handles:
        ax.legend(legend_handles, legend_labels_list,
                  loc="best", frameon=False, fontsize=8.5, handlelength=1.2)

    figure_base = output_dir / "structure_metric_comparison_boxplot"
    fig.tight_layout()
    fig.savefig(figure_base.with_suffix(".png"))
    fig.savefig(figure_base.with_suffix(".svg"))
    plt.close(fig)

    print("Comparison data sources:")
    for label, csv_path in zip(comparison_labels, resolved_csv_paths):
        print(f"  {label}: {csv_path}")
    print(f"Saved comparison figure to {figure_base.with_suffix('.png')}")
    return figure_base.with_suffix(".png")


def _draw_panel(
    ax,
    metric_specs: list[tuple[str, str]],
    series_list: list[tuple[str, list[float], str]],
    title: str,
    show_ylabel: bool,
) -> plt.Line2D | None:
    """Draw one violin panel.

    series_list: list of (label, data, color) — one entry per violin per metric group.
    Each entry applies to ALL metrics in metric_specs in order.
    Actually: series_list contains (label, key_suffix, color) where the metric key
    is looked up per metric. Pass pre-resolved data directly as list[float].

    Simplified: series_list is list of (display_label, {metric_key: [float]}, color).
    """
    ax.grid(axis="y", color="#E6E6E6", linewidth=0.8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_linewidth(0.8)
    ax.spines["bottom"].set_linewidth(0.8)
    ax.tick_params(length=4, width=0.8)

    n_conditions = len(series_list)
    n_metrics = len(metric_specs)
    spacing = max(n_conditions * 0.75, 2.0)
    group_centers = np.arange(n_metrics, dtype=float) * spacing
    half = (n_conditions - 1) / 2.0
    offsets = np.array([(i - half) * 0.7 for i in range(n_conditions)])
    width = 0.55
    mean_handle = None

    for metric_index, (metric_key, _metric_name) in enumerate(metric_specs):
        for cond_index, (_, data_map, color) in enumerate(series_list):
            series = data_map.get(metric_key, [])
            if not series:
                continue
            position = float(group_centers[metric_index] + offsets[cond_index])
            violin = ax.violinplot(
                [series],
                positions=[position],
                widths=width,
                showmeans=False,
                showmedians=False,
                showextrema=False,
            )
            for body in violin["bodies"]:
                body.set_facecolor(color)
                body.set_edgecolor("#444444")
                body.set_linewidth(0.9)
                body.set_alpha(0.78)

            mean_value = float(np.mean(series))
            ax.scatter(
                [position], [mean_value], marker="D", s=45,
                facecolor="white", edgecolor="#111111", linewidth=0.9, zorder=4,
            )
            if mean_handle is None:
                mean_handle = plt.Line2D(
                    [0], [0], marker="D", linestyle="",
                    markerfacecolor="white", markeredgecolor="#111111",
                    color="#111111", markersize=6,
                )
            ax.text(
                position, min(mean_value + 0.035, 1.02), f"{mean_value:.3f}",
                ha="center", va="bottom", fontsize=15, color="#222222",
            )

    ax.set_xticks(group_centers)
    ax.set_xticklabels([name for _, name in metric_specs])
    ax.set_ylim(0.0, 1.08)
    if show_ylabel:
        ax.set_ylabel("Score")
    return mean_handle


def plot_soft_and_semantic_comparison(
    comparison_roots: list[Path],
    comparison_labels: list[str],
    output_dir: Path,
) -> Path:
    if len(comparison_roots) != len(comparison_labels):
        raise ValueError("--comparison-roots and --comparison-labels must have the same length.")

    # Accept-all soft F1 (always available)
    soft_f1_accept_paths = [find_latest_soft_f1_accept_csv(root) for root in comparison_roots]
    # No-revision soft F1 (optional — only if data exists)
    soft_f1_no_rev_paths = [find_latest_soft_f1_no_rev_csv(root) for root in comparison_roots]
    semantic_csv_paths = [find_latest_named_csv(root, SEMANTIC_FILENAME) for root in comparison_roots]

    accept_metrics: dict[str, dict[str, list[float]]] = {}
    no_rev_metrics: dict[str, dict[str, list[float]]] = {}
    for label, accept_path, no_rev_path, semantic_path in zip(
        comparison_labels, soft_f1_accept_paths, soft_f1_no_rev_paths, semantic_csv_paths
    ):
        m: dict[str, list[float]] = {}
        m.update(collect_soft_f1_api_metrics(accept_path))
        m.update(collect_semantic_metrics(semantic_path))
        accept_metrics[label] = m

        if no_rev_path is not None:
            nr: dict[str, list[float]] = {}
            nr.update(collect_soft_f1_api_metrics(no_rev_path))
            nr["semantic_no_rev"] = m.get("semantic_no_rev", [])
            no_rev_metrics[label] = nr

    has_no_rev = comparison_labels[0] in no_rev_metrics

    output_dir = ensure_dir(output_dir.resolve())

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
            "font.sans-serif": ["Arial", "Times New Roman", "DejaVu Sans"],
        }
    )

    # 3-color scheme: No Revision / Revision / Revision + FS
    THREE_COLORS = ["#A8A8A8", "#5E81AC", "#2E4A6E"]

    sem_series = [
        ("No Revision",
         {"sem_val": accept_metrics[comparison_labels[0]].get("semantic_no_rev", [])},
         THREE_COLORS[0]),
        ("Revision",
         {"sem_val": accept_metrics[comparison_labels[0]].get("semantic_accept_all_vs_updated", [])},
         THREE_COLORS[1]),
        ("Revision + FS",
         {"sem_val": accept_metrics[comparison_labels[1]].get("semantic_accept_all_vs_updated", [])},
         THREE_COLORS[2]),
    ]

    if has_no_rev:
        node_edge_series = [
            ("No Revision", no_rev_metrics[comparison_labels[0]], THREE_COLORS[0]),
            ("Revision",    accept_metrics[comparison_labels[0]], THREE_COLORS[1]),
            ("Revision + FS", accept_metrics[comparison_labels[1]], THREE_COLORS[2]),
        ]
    else:
        node_edge_series = [
            ("Revision",      accept_metrics[comparison_labels[0]], THREE_COLORS[1]),
            ("Revision + FS", accept_metrics[comparison_labels[1]], THREE_COLORS[2]),
        ]

    legend_labels_list = ["No Revision", "Revision", "Revision + FS"]
    legend_colors = THREE_COLORS

    panel_defs = [
        (
            [("soft_node_precision", "Precision"), ("soft_node_recall", "Recall"), ("soft_node_f1", "F1")],
            "Soft Node Matching",
            node_edge_series,
            "soft_node_comparison_violin",
            (7.5, 4.5),
        ),
        (
            [("soft_edge_precision", "Precision"), ("soft_edge_recall", "Recall"), ("soft_edge_f1", "F1")],
            "Soft Edge Matching",
            node_edge_series,
            "soft_edge_comparison_violin",
            (7.5, 4.5),
        ),
        (
            [("sem_val", "Semantic\nsimilarity")],
            "Semantic Similarity",
            sem_series,
            "semantic_comparison_violin",
            (4.5, 4.5),
        ),
    ]

    legend_handles = [
        plt.Line2D([0], [0], color=c, linewidth=10, alpha=0.82)
        for c in legend_colors
    ]

    saved_paths = []
    last_idx = len(panel_defs) - 1
    for panel_idx, (metric_specs, title, series, filename, fig_size) in enumerate(panel_defs):
        fig, ax = plt.subplots(figsize=fig_size)
        mean_handle = _draw_panel(
            ax=ax,
            metric_specs=metric_specs,
            series_list=series,
            title=title,
            show_ylabel=True,
        )
        figure_base = output_dir / filename
        fig.tight_layout()
        fig.savefig(figure_base.with_suffix(".png"))
        fig.savefig(figure_base.with_suffix(".svg"))
        plt.close(fig)
        saved_paths.append(figure_base.with_suffix(".png"))
        print(f"Saved: {figure_base.with_suffix('.png')}")

    print("Soft F1 accept-all data sources:")
    for label, csv_path in zip(comparison_labels, soft_f1_accept_paths):
        print(f"  {label}: {csv_path}")
    if has_no_rev:
        print("Soft F1 no-revision data sources:")
        for label, csv_path in zip(comparison_labels, soft_f1_no_rev_paths):
            print(f"  {label}: {csv_path}")
    print("Semantic data sources:")
    for label, csv_path in zip(comparison_labels, semantic_csv_paths):
        print(f"  {label}: {csv_path}")
    return saved_paths[0]


def plot_combined_figure(
    comparison_roots: list[Path],
    comparison_labels: list[str],
    output_dir: Path,
) -> Path:
    """2×2 combined figure: (a) Structure, (b) Node, (c) Edge, (d) Semantic."""
    THREE_COLORS = ["#A8A8A8", "#5E81AC", "#2E4A6E"]

    # ── load data ──────────────────────────────────────────────────────────────
    struct_paths = [find_latest_case_scores(r) for r in comparison_roots]
    struct_metrics = {
        label: collect_similarity_metrics(p)
        for label, p in zip(comparison_labels, struct_paths)
    }

    soft_f1_accept_paths = [find_latest_soft_f1_accept_csv(r) for r in comparison_roots]
    soft_f1_no_rev_paths = [find_latest_soft_f1_no_rev_csv(r) for r in comparison_roots]
    semantic_paths = [find_latest_named_csv(r, SEMANTIC_FILENAME) for r in comparison_roots]

    accept_metrics: dict[str, dict[str, list[float]]] = {}
    no_rev_metrics: dict[str, dict[str, list[float]]] = {}
    for label, ap, nrp, sp in zip(comparison_labels, soft_f1_accept_paths, soft_f1_no_rev_paths, semantic_paths):
        m: dict[str, list[float]] = {}
        m.update(collect_soft_f1_api_metrics(ap))
        m.update(collect_semantic_metrics(sp))
        accept_metrics[label] = m
        if nrp is not None:
            nr: dict[str, list[float]] = {}
            nr.update(collect_soft_f1_api_metrics(nrp))
            nr["semantic_no_rev"] = m.get("semantic_no_rev", [])
            no_rev_metrics[label] = nr

    has_no_rev = comparison_labels[0] in no_rev_metrics

    # ── series definitions ─────────────────────────────────────────────────────
    # Structure
    struct_series = [
        ("No Revision", {
            "wl_kernel":          struct_metrics[comparison_labels[0]]["wl_kernel_no_rev"],
            "one_minus_norm_ged": struct_metrics[comparison_labels[0]]["one_minus_norm_ged_no_rev"],
        }, THREE_COLORS[0]),
        ("Revision", {
            "wl_kernel":          struct_metrics[comparison_labels[0]]["wl_kernel"],
            "one_minus_norm_ged": struct_metrics[comparison_labels[0]]["one_minus_norm_ged"],
        }, THREE_COLORS[1]),
        ("Revision + FS", {
            "wl_kernel":          struct_metrics[comparison_labels[1]]["wl_kernel"],
            "one_minus_norm_ged": struct_metrics[comparison_labels[1]]["one_minus_norm_ged"],
        }, THREE_COLORS[2]),
    ]

    if has_no_rev:
        node_edge_series = [
            ("No Revision",   no_rev_metrics[comparison_labels[0]], THREE_COLORS[0]),
            ("Revision",      accept_metrics[comparison_labels[0]], THREE_COLORS[1]),
            ("Revision + FS", accept_metrics[comparison_labels[1]], THREE_COLORS[2]),
        ]
    else:
        node_edge_series = [
            ("Revision",      accept_metrics[comparison_labels[0]], THREE_COLORS[1]),
            ("Revision + FS", accept_metrics[comparison_labels[1]], THREE_COLORS[2]),
        ]

    sem_series = [
        ("No Revision",   {"sem_val": accept_metrics[comparison_labels[0]].get("semantic_no_rev", [])},              THREE_COLORS[0]),
        ("Revision",      {"sem_val": accept_metrics[comparison_labels[0]].get("semantic_accept_all_vs_updated", [])}, THREE_COLORS[1]),
        ("Revision + FS", {"sem_val": accept_metrics[comparison_labels[1]].get("semantic_accept_all_vs_updated", [])}, THREE_COLORS[2]),
    ]

    # ── figure layout ──────────────────────────────────────────────────────────
    plt.style.use("default")
    plt.rcParams.update({
        "figure.dpi": 150, "savefig.dpi": 300,
        "figure.facecolor": "white", "axes.facecolor": "white",
        "savefig.facecolor": "white", "savefig.bbox": "tight",
        "font.family": "serif",
        "font.serif": ["Times New Roman", "DejaVu Serif"],
        "font.size": 20,
        "axes.labelsize": 20,
        "axes.titlesize": 20,
        "xtick.labelsize": 18,
        "ytick.labelsize": 18,
        "legend.fontsize": 20,
    })

    fig = plt.figure(figsize=(13, 7.0))
    gs = fig.add_gridspec(2, 2, hspace=0.3, wspace=0.1)
    axes = [
        fig.add_subplot(gs[0, 0]),  # (a) Structure
        fig.add_subplot(gs[0, 1]),  # (b) Node
        fig.add_subplot(gs[1, 0]),  # (c) Edge
        fig.add_subplot(gs[1, 1]),  # (d) Semantic
    ]

    panels = [
        ([("wl_kernel", "WLS"), ("one_minus_norm_ged", "GES")], struct_series),
        ([("soft_node_precision", "Precision"), ("soft_node_recall", "Recall"), ("soft_node_f1", "F1")], node_edge_series),
        ([("soft_edge_precision", "Precision"), ("soft_edge_recall", "Recall"), ("soft_edge_f1", "F1")], node_edge_series),
        ([("sem_val", "Semantic similarity")], sem_series),
    ]
    panel_titles = ["Structural Similarity", "Node Matching", "Edge Matching", "Semantic Similarity"]
    panel_labels = ["(a)", "(b)", "(c)", "(d)"]

    for ax_idx, (ax, (metric_specs, series), title, label) in enumerate(zip(axes, panels, panel_titles, panel_labels)):
        show_ylabel = ax_idx in (0, 2)
        _draw_panel(ax=ax, metric_specs=metric_specs, series_list=series,
                    title=title, show_ylabel=show_ylabel)
        if not show_ylabel:
            ax.tick_params(labelleft=False)
        ax.text(0.0, 1.01, label, transform=ax.transAxes,
                fontsize=20, fontweight="bold", va="bottom", ha="left")

    # ── shared legend at bottom ────────────────────────────────────────────────
    legend_handles = [plt.Line2D([0], [0], color=c, linewidth=10, alpha=0.82) for c in THREE_COLORS]
    mean_handle = plt.Line2D([0], [0], marker="D", linestyle="",
                             markerfacecolor="white", markeredgecolor="#111111",
                             color="#111111", markersize=6)
    legend_handles.append(mean_handle)
    legend_labels = ["No Revision", "Revision", "Revision + FS", "Mean"]
    fig.subplots_adjust(bottom=0.08)
    fig.legend(legend_handles, legend_labels,
               loc="lower center", ncol=4, frameon=False,
               bbox_to_anchor=(0.5, -0.05))

    output_dir = ensure_dir(output_dir.resolve())
    figure_base = output_dir / "combined_comparison"
    fig.savefig(figure_base.with_suffix(".png"))
    fig.savefig(figure_base.with_suffix(".svg"))
    plt.close(fig)
    print(f"Saved combined figure: {figure_base.with_suffix('.png')}")
    return figure_base.with_suffix(".png")


def main() -> None:
    args = parse_args()
    plot_similarity_comparison(
        comparison_roots=args.comparison_roots,
        comparison_labels=args.comparison_labels,
        output_dir=args.output_dir,
    )
    plot_soft_and_semantic_comparison(
        comparison_roots=args.comparison_roots,
        comparison_labels=args.comparison_labels,
        output_dir=args.output_dir,
    )
    plot_combined_figure(
        comparison_roots=args.comparison_roots,
        comparison_labels=args.comparison_labels,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    main()
