from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
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
EXPECTED_REPORTS = 112
EXPECTED_RUNS = 5
DEFAULT_NO_REVISION_CSV = Path(
    r"runs\stability_test\evaluation_final\no_revision\20260902_164902\case_scores.csv"
)
DEFAULT_REVISION_CSV = Path(
    r"runs\stability_test\evaluation_final\revision\20260829_170239\case_scores.csv"
)
DEFAULT_FEW_SHOT_CSV = Path(
    r"runs\stability_test\evaluation_final\few_shot\20260828_140052\case_scores.csv"
)
DEFAULT_SINGLE_PASS_CSV = Path(
    r"runs\stability_test\evaluation_final\single_pass\20260828_141620\case_scores.csv"
)
def latest_auxiliary_csv() -> Path:
    root = Path(r"runs\stability_test\evaluation_final\auxiliary")
    candidates = sorted(
        root.glob("*/combined_auxiliary_case_scores.csv"),
        key=lambda path: path.parent.name,
        reverse=True,
    )
    return candidates[0] if candidates else root / "combined_auxiliary_case_scores.csv"


DEFAULT_AUXILIARY_CSV = latest_auxiliary_csv()
DEFAULT_OUTPUT_DIR = Path(r"runs\stability_test\figures_comparing_rounds")
FOUR_COLORS = ["#D0D0D0", "#A8A8A8", "#5E81AC", "#2E4A6E"]
CONDITION_LABELS = ["Single Pass", "No Revision", "Revision", "Revision + FS"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate the legacy-style comparison figures from audited five-run data."
    )
    parser.add_argument(
        "--no-revision-csv",
        type=Path,
        default=DEFAULT_NO_REVISION_CSV,
        help="Five-run two-stage No Revision structural case_scores.csv.",
    )
    parser.add_argument(
        "--revision-csv",
        type=Path,
        default=DEFAULT_REVISION_CSV,
        help="Five-run revised structural case_scores.csv.",
    )
    parser.add_argument(
        "--few-shot-csv",
        type=Path,
        default=DEFAULT_FEW_SHOT_CSV,
        help="Five-run few-shot structural case_scores.csv.",
    )
    parser.add_argument(
        "--single-pass-csv",
        type=Path,
        default=DEFAULT_SINGLE_PASS_CSV,
        help="Five-run single-pass structural case_scores.csv.",
    )
    parser.add_argument(
        "--auxiliary-csv",
        type=Path,
        default=DEFAULT_AUXILIARY_CSV,
        help="Unified five-run node, edge, and semantic result CSV.",
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


def audit_structural_input(path: Path, expected_runs: set[str]) -> dict[str, object]:
    rows = read_csv_rows(path)
    successful = [row for row in rows if str(row.get("status", "")).strip().lower() == "ok"]
    reports = {
        f"{row.get('batch_id', '').strip()}/{row.get('case_id', '').strip()}"
        for row in successful
    }
    runs = {str(row.get("round", "")).strip() for row in successful}
    report_counts = Counter(
        f"{row.get('batch_id', '').strip()}/{row.get('case_id', '').strip()}"
        for row in successful
    )
    keys = [
        (
            str(row.get("round", "")).strip(),
            str(row.get("batch_id", "")).strip(),
            str(row.get("case_id", "")).strip(),
        )
        for row in successful
    ]
    problems: list[str] = []
    if len(rows) != EXPECTED_REPORTS * EXPECTED_RUNS:
        problems.append(f"expected 560 total rows, found {len(rows)}")
    if len(successful) != EXPECTED_REPORTS * EXPECTED_RUNS:
        problems.append(f"expected 560 successful rows, found {len(successful)}")
    if len(reports) != EXPECTED_REPORTS:
        problems.append(f"expected 112 reports, found {len(reports)}")
    if runs != expected_runs:
        problems.append(f"expected runs {sorted(expected_runs)}, found {sorted(runs)}")
    if report_counts and set(report_counts.values()) != {EXPECTED_RUNS}:
        problems.append("reports do not all have five observations")
    if len(keys) != len(set(keys)):
        problems.append("duplicate run/batch/case rows were found")
    audit = {
        "path": str(path.resolve()),
        "total_rows": len(rows),
        "successful_rows": len(successful),
        "independent_reports": len(reports),
        "runs": sorted(runs),
        "complete": not problems,
        "problems": problems,
    }
    if problems:
        raise RuntimeError(f"Five-run structural input audit failed for {path}: " + "; ".join(problems))
    return audit


def collect_final_auxiliary_metrics(
    path: Path,
) -> tuple[dict[str, dict[str, list[float]]], dict[str, object]]:
    condition_names = (
        "single_pass",
        "no_revision",
        "revision",
        "revision_fs",
    )
    metric_names = (
        "soft_node_precision",
        "soft_node_recall",
        "soft_node_f1",
        "soft_edge_precision",
        "soft_edge_recall",
        "soft_edge_f1",
        "semantic_similarity",
    )
    rows = read_csv_rows(path)
    successful = [row for row in rows if str(row.get("status", "")).strip().lower() == "ok"]
    result = {
        condition: {metric: [] for metric in metric_names}
        for condition in condition_names
    }
    condition_audits: dict[str, object] = {}
    problems: list[str] = []

    if len(rows) != len(condition_names) * EXPECTED_REPORTS * EXPECTED_RUNS:
        problems.append(f"expected 2240 total rows, found {len(rows)}")
    if len(successful) != len(rows):
        problems.append(f"expected all rows to be successful, found {len(successful)} successful rows")

    all_keys: list[tuple[str, str, str]] = []
    for condition in condition_names:
        selected = [row for row in successful if row.get("condition") == condition]
        reports = {str(row.get("report_id", "")).strip() for row in selected}
        runs = {str(row.get("run", "")).strip() for row in selected}
        expected_runs = (
            {f"run_{index:02d}" for index in range(1, EXPECTED_RUNS + 1)}
            if condition == "single_pass"
            else {f"round_{index}" for index in range(1, EXPECTED_RUNS + 1)}
        )
        report_counts = Counter(str(row.get("report_id", "")).strip() for row in selected)
        local_problems: list[str] = []
        if len(selected) != EXPECTED_REPORTS * EXPECTED_RUNS:
            local_problems.append(f"expected 560 successful rows, found {len(selected)}")
        if len(reports) != EXPECTED_REPORTS:
            local_problems.append(f"expected 112 reports, found {len(reports)}")
        if runs != expected_runs:
            local_problems.append(f"expected runs {sorted(expected_runs)}, found {sorted(runs)}")
        if report_counts and set(report_counts.values()) != {EXPECTED_RUNS}:
            local_problems.append("reports do not all have five observations")

        for row in selected:
            all_keys.append((condition, str(row.get("run", "")), str(row.get("report_id", ""))))
            for metric in metric_names:
                value = to_float(row.get(metric, ""))
                if value is None:
                    local_problems.append(f"missing {metric} value")
                    break
                result[condition][metric].append(value)

        if local_problems:
            problems.extend(f"{condition}: {problem}" for problem in local_problems)
        condition_audits[condition] = {
            "successful_rows": len(selected),
            "independent_reports": len(reports),
            "runs": sorted(runs),
            "complete": not local_problems,
            "problems": local_problems,
        }

    if len(all_keys) != len(set(all_keys)):
        problems.append("duplicate condition/run/report rows were found")
    audit = {
        "path": str(path.resolve()),
        "total_rows": len(rows),
        "successful_rows": len(successful),
        "conditions": condition_audits,
        "complete": not problems,
        "problems": problems,
    }
    if problems:
        raise RuntimeError("Five-run auxiliary input audit failed: " + "; ".join(problems))
    return result, audit


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
    structural_paths: dict[str, Path],
    output_dir: Path,
) -> Path:
    metrics = {
        condition: collect_similarity_metrics(path)
        for condition, path in structural_paths.items()
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

    metric_specs = [
        ("wl_kernel", "WLS"),
        ("one_minus_norm_ged", "GES"),
    ]

    group_centers = np.arange(len(metric_specs), dtype=float) * 3.2
    offsets = np.array([-1.05, -0.35, 0.35, 1.05], dtype=float)
    width = 0.55

    legend_handles = [
        plt.Line2D([0], [0], color=c, linewidth=10, alpha=0.82)
        for c in FOUR_COLORS
    ]
    legend_labels_list = list(CONDITION_LABELS)
    mean_handle = None

    for metric_index, (metric_key, metric_name) in enumerate(metric_specs):
        no_revision_key = {
            "wl_kernel": "wl_kernel_no_rev",
            "one_minus_norm_ged": "one_minus_norm_ged_no_rev",
        }[metric_key]
        all_series = [
            metrics["single_pass"][no_revision_key],
            metrics["no_revision"][no_revision_key],
            metrics["revision"][metric_key],
            metrics["few_shot"][metric_key],
        ]
        for dataset_index, series in enumerate(all_series):
            if not series:
                continue
            position = float(group_centers[metric_index] + offsets[dataset_index])
            color = FOUR_COLORS[dataset_index]
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
    for condition, csv_path in structural_paths.items():
        print(f"  {condition}: {csv_path}")
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
    spacing = max(n_conditions * 0.90, 2.0)
    group_centers = np.arange(n_metrics, dtype=float) * spacing
    half = (n_conditions - 1) / 2.0
    offsets = np.array([(i - half) * 0.9 for i in range(n_conditions)])
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
                position,
                min(mean_value + 0.035 + 0.100 * (cond_index % 2), 1.02),
                f"{mean_value:.3f}",
                ha="center", va="bottom", fontsize=15, color="#222222",
            )

    ax.set_xticks(group_centers)
    ax.set_xticklabels([name for _, name in metric_specs])
    ax.set_ylim(0.0, 1.08)
    if show_ylabel:
        ax.set_ylabel("Score")
    return mean_handle


def plot_soft_and_semantic_comparison(
    auxiliary_metrics: dict[str, dict[str, list[float]]],
    auxiliary_path: Path,
    output_dir: Path,
) -> Path:
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

    sem_series = [
        (label, {"sem_val": auxiliary_metrics[condition]["semantic_similarity"]}, color)
        for label, condition, color in zip(
            CONDITION_LABELS,
            ("single_pass", "no_revision", "revision", "revision_fs"),
            FOUR_COLORS,
        )
    ]

    node_edge_series = [
        (label, auxiliary_metrics[condition], color)
        for label, condition, color in zip(
            CONDITION_LABELS,
            ("single_pass", "no_revision", "revision", "revision_fs"),
            FOUR_COLORS,
        )
    ]

    legend_labels_list = list(CONDITION_LABELS)
    legend_colors = FOUR_COLORS

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

    print(f"Five-run auxiliary data source: {auxiliary_path}")
    return saved_paths[0]


def plot_combined_figure(
    structural_paths: dict[str, Path],
    auxiliary_metrics: dict[str, dict[str, list[float]]],
    output_dir: Path,
) -> Path:
    """2×2 combined figure: (a) Structure, (b) Node, (c) Edge, (d) Semantic."""
    struct_metrics = {
        condition: collect_similarity_metrics(path)
        for condition, path in structural_paths.items()
    }

    struct_series = [
        ("Single Pass", {
            "wl_kernel":          struct_metrics["single_pass"]["wl_kernel_no_rev"],
            "one_minus_norm_ged": struct_metrics["single_pass"]["one_minus_norm_ged_no_rev"],
        }, FOUR_COLORS[0]),
        ("No Revision", {
            "wl_kernel":          struct_metrics["no_revision"]["wl_kernel_no_rev"],
            "one_minus_norm_ged": struct_metrics["no_revision"]["one_minus_norm_ged_no_rev"],
        }, FOUR_COLORS[1]),
        ("Revision", {
            "wl_kernel":          struct_metrics["revision"]["wl_kernel"],
            "one_minus_norm_ged": struct_metrics["revision"]["one_minus_norm_ged"],
        }, FOUR_COLORS[2]),
        ("Revision + FS", {
            "wl_kernel":          struct_metrics["few_shot"]["wl_kernel"],
            "one_minus_norm_ged": struct_metrics["few_shot"]["one_minus_norm_ged"],
        }, FOUR_COLORS[3]),
    ]

    condition_specs = (
        ("Single Pass", "single_pass", FOUR_COLORS[0]),
        ("No Revision", "no_revision", FOUR_COLORS[1]),
        ("Revision", "revision", FOUR_COLORS[2]),
        ("Revision + FS", "revision_fs", FOUR_COLORS[3]),
    )
    node_edge_series = [
        (label, auxiliary_metrics[condition], color)
        for label, condition, color in condition_specs
    ]

    sem_series = [
        (label, {"sem_val": auxiliary_metrics[condition]["semantic_similarity"]}, color)
        for label, condition, color in condition_specs
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

    fig = plt.figure(figsize=(16, 7.0))
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
    legend_handles = [plt.Line2D([0], [0], color=c, linewidth=10, alpha=0.82) for c in FOUR_COLORS]
    mean_handle = plt.Line2D([0], [0], marker="D", linestyle="",
                             markerfacecolor="white", markeredgecolor="#111111",
                             color="#111111", markersize=6)
    legend_handles.append(mean_handle)
    legend_labels = [*CONDITION_LABELS, "Mean"]
    fig.subplots_adjust(bottom=0.08)
    fig.legend(legend_handles, legend_labels,
               loc="lower center", ncol=5, frameon=False,
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
    structural_paths = {
        "single_pass": args.single_pass_csv.resolve(),
        "no_revision": args.no_revision_csv.resolve(),
        "revision": args.revision_csv.resolve(),
        "few_shot": args.few_shot_csv.resolve(),
    }
    for path in [*structural_paths.values(), args.auxiliary_csv.resolve()]:
        if not path.is_file():
            raise FileNotFoundError(path)

    structural_audits = {
        "single_pass": audit_structural_input(
            structural_paths["single_pass"],
            {f"run_{index:02d}" for index in range(1, EXPECTED_RUNS + 1)},
        ),
        "no_revision": audit_structural_input(
            structural_paths["no_revision"],
            {f"round_{index}" for index in range(1, EXPECTED_RUNS + 1)},
        ),
        "revision": audit_structural_input(
            structural_paths["revision"],
            {f"round_{index}" for index in range(1, EXPECTED_RUNS + 1)},
        ),
        "few_shot": audit_structural_input(
            structural_paths["few_shot"],
            {f"round_{index}" for index in range(1, EXPECTED_RUNS + 1)},
        ),
    }
    auxiliary_path = args.auxiliary_csv.resolve()
    auxiliary_metrics, auxiliary_audit = collect_final_auxiliary_metrics(auxiliary_path)

    structural_report_sets = {
        condition: {
            f"{row.get('batch_id', '').strip()}/{row.get('case_id', '').strip()}"
            for row in read_csv_rows(path)
            if str(row.get("status", "")).strip().lower() == "ok"
        }
        for condition, path in structural_paths.items()
    }
    auxiliary_report_sets = {
        condition: {
            str(row.get("report_id", "")).strip()
            for row in read_csv_rows(auxiliary_path)
            if str(row.get("status", "")).strip().lower() == "ok"
            and row.get("condition") == condition
        }
        for condition in (
            "single_pass",
            "no_revision",
            "revision",
            "revision_fs",
        )
    }
    reference_reports = structural_report_sets["no_revision"]
    report_set_problems: list[str] = []
    for condition, reports in structural_report_sets.items():
        if reports != reference_reports:
            report_set_problems.append(f"structural report set differs for {condition}")
    for condition, reports in auxiliary_report_sets.items():
        if reports != reference_reports:
            report_set_problems.append(f"auxiliary report set differs for {condition}")
    if report_set_problems:
        raise RuntimeError("Five-run paired report audit failed: " + "; ".join(report_set_problems))

    plot_similarity_comparison(
        structural_paths=structural_paths,
        output_dir=args.output_dir,
    )
    plot_soft_and_semantic_comparison(
        auxiliary_metrics=auxiliary_metrics,
        auxiliary_path=auxiliary_path,
        output_dir=args.output_dir,
    )
    plot_combined_figure(
        structural_paths=structural_paths,
        auxiliary_metrics=auxiliary_metrics,
        output_dir=args.output_dir,
    )

    output_dir = ensure_dir(args.output_dir.resolve())
    audit = {
        "expected_reports": EXPECTED_REPORTS,
        "expected_runs": EXPECTED_RUNS,
        "conditions": CONDITION_LABELS,
        "colors": dict(zip(CONDITION_LABELS, FOUR_COLORS)),
        "structural_inputs": structural_audits,
        "auxiliary_input": auxiliary_audit,
        "paired_report_sets_identical": True,
        "output_files": [
            "structure_metric_comparison_boxplot.png",
            "structure_metric_comparison_boxplot.svg",
            "soft_node_comparison_violin.png",
            "soft_node_comparison_violin.svg",
            "soft_edge_comparison_violin.png",
            "soft_edge_comparison_violin.svg",
            "semantic_comparison_violin.png",
            "semantic_comparison_violin.svg",
            "combined_comparison.png",
            "combined_comparison.svg",
        ],
    }
    audit_path = output_dir / "five_run_comparison_input_audit.json"
    audit_path.write_text(json.dumps(audit, indent=2), encoding="utf-8")
    print(f"Saved five-run input audit: {audit_path}")


if __name__ == "__main__":
    main()
