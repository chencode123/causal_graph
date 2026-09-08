"""Plot audited five-run graph-evaluation distributions for four conditions.

The four conditions are no revision, revision without few-shot feedback, revision
with few-shot feedback, and the schema-constrained single-pass baseline.
Each run writes the original report-run plots and additional paired plots based
on each report's mean across five runs, using an otherwise identical layout.
"""
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
FINAL_AUXILIARY_FILENAME = "combined_auxiliary_case_scores.csv"
SOFT_F1_ACCEPT_DIRNAME = "result_soft_f1_api_accept_all_vs_updated"
SOFT_F1_NO_REV_DIRNAME = "result_soft_f1_api"
WL_COLUMN = "structural_similarity_accept_all_vs_updated"
NORM_GED_COLUMN = "normalized_graph_edit_distance_accept_all_vs_updated"
WL_COLUMN_NO_REV = "structural_similarity"
NORM_GED_COLUMN_NO_REV = "normalized_graph_edit_distance"
DEFAULT_NO_REVISION_ROOT = Path(r"runs\stability_test\evaluation_final\no_revision")
DEFAULT_REVISION_ROOT = Path(r"runs\stability_test\evaluation_final\revision")
DEFAULT_FEW_SHOT_ROOT = Path(r"runs\stability_test\evaluation_final\few_shot")
DEFAULT_SINGLE_PASS_ROOT = Path(r"runs\stability_test\evaluation_final\single_pass")
DEFAULT_AUXILIARY_ROOT = Path(r"runs\stability_test\evaluation_final\auxiliary")
DEFAULT_OUTPUT_DIR = Path(r"runs\stability_test\figures_comparing_rounds\five_run")
EXPECTED_REPORTS = 112
EXPECTED_RUNS = 5


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate original report-run and paired report-mean box-plot variants "
            "of the stability comparison combined figure."
        )
    )
    parser.add_argument("--no-revision-root", type=Path,
                        default=DEFAULT_NO_REVISION_ROOT)
    parser.add_argument("--revision-root", type=Path,
                        default=DEFAULT_REVISION_ROOT)
    parser.add_argument("--few-shot-root", type=Path,
                        default=DEFAULT_FEW_SHOT_ROOT)
    parser.add_argument("--single-pass-root", type=Path,
                        default=DEFAULT_SINGLE_PASS_ROOT)
    parser.add_argument("--auxiliary-root", type=Path,
                        default=DEFAULT_AUXILIARY_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--legacy-output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR.parent,
        help=(
            "Directory for compatibility copies named "
            "combined_comparison_boxplot_label_<position>."
        ),
    )
    parser.add_argument(
        "--no-legacy-aliases",
        action="store_true",
        help="Do not write compatibility copies using the earlier filenames.",
    )
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="Development only: plot available successful rows instead of requiring 112x5.",
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
    direct = root / CASE_SCORE_FILENAME
    if direct.exists():
        return direct
    search = (root / "results") if (root / "results").exists() else root
    candidates = list(search.rglob(CASE_SCORE_FILENAME))
    if not candidates:
        raise FileNotFoundError(f"Cannot find {CASE_SCORE_FILENAME} under {root}")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def find_latest_named_csv(root: Path, filename: str) -> Path:
    root = root.resolve()
    direct = root / filename
    if direct.exists():
        return direct
    candidates = list(root.rglob(filename))
    if not candidates:
        raise FileNotFoundError(f"Cannot find {filename} under {root}")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def find_latest_soft_f1_accept_csv(root: Path) -> Path:
    root = root.resolve()
    preferred = root / SOFT_F1_ACCEPT_DIRNAME
    if preferred.exists():
        return find_latest_named_csv(preferred, SOFT_F1_API_FILENAME)
    return find_latest_named_csv(root, SOFT_F1_API_FILENAME)


def find_latest_soft_f1_no_rev_csv(root: Path) -> Path | None:
    root = root.resolve()
    preferred = root / SOFT_F1_NO_REV_DIRNAME
    if not preferred.exists():
        return None
    try:
        return find_latest_named_csv(preferred, SOFT_F1_API_FILENAME)
    except FileNotFoundError:
        return None


def collect_similarity_metrics(
    path: Path, *, aggregate_by_report: bool = False
) -> dict[str, list[float]]:
    metric_columns = {
        "wl_kernel": WL_COLUMN,
        "one_minus_norm_ged": NORM_GED_COLUMN,
        "wl_kernel_no_rev": WL_COLUMN_NO_REV,
        "one_minus_norm_ged_no_rev": NORM_GED_COLUMN_NO_REV,
    }
    result: dict[str, list[float]] = {key: [] for key in metric_columns}
    report_values: dict[str, dict[str, list[float]]] = {
        key: {} for key in metric_columns
    }
    for row in read_csv_rows(path):
        if str(row.get("status", "")).strip().lower() != "ok":
            continue
        report_id = (
            f"{str(row.get('batch_id', '')).strip().lower()}/"
            f"{str(row.get('case_id', '')).strip().lower()}"
        )
        for metric, column in metric_columns.items():
            value = to_float(row.get(column, ""))
            if value is None:
                continue
            if metric.startswith("one_minus_norm_ged"):
                value = 1.0 - value
            if aggregate_by_report:
                report_values[metric].setdefault(report_id, []).append(value)
            else:
                result[metric].append(value)
    if aggregate_by_report:
        for metric, report_map in report_values.items():
            result[metric] = [
                float(np.mean(report_map[report_id]))
                for report_id in sorted(report_map)
            ]
    return result


def collect_soft_f1_api_metrics(path: Path) -> dict[str, list[float]]:
    keys = [
        "soft_node_precision", "soft_node_recall", "soft_node_f1",
        "soft_edge_precision", "soft_edge_recall", "soft_edge_f1",
    ]
    result: dict[str, list[float]] = {k: [] for k in keys}
    for row in read_csv_rows(path):
        if str(row.get("status", "")).strip().lower() != "ok":
            continue
        for key in keys:
            v = to_float(row.get(key, ""))
            if v is not None:
                result[key].append(v)
    return result


def collect_semantic_metrics(path: Path) -> dict[str, list[float]]:
    acc, nr = [], []
    for row in read_csv_rows(path):
        if str(row.get("status", "")).strip().lower() != "ok":
            continue
        v = to_float(row.get("semantic_similarity_accept_all_vs_updated", ""))
        if v is not None:
            acc.append(v)
        v = to_float(row.get("semantic_similarity_generated_vs_updated", ""))
        if v is not None:
            nr.append(v)
    return {"semantic_accept_all_vs_updated": acc, "semantic_no_rev": nr}


def collect_final_auxiliary_metrics(
    path: Path,
    *,
    aggregate_by_report: bool = False,
) -> tuple[dict[str, dict[str, list[float]]], dict[str, object]]:
    """Load and strictly audit the unified five-run node/edge/semantic output."""
    condition_names = (
        "single_pass",
        "no_revision",
        "revision",
        "revision_fs",
    )
    metric_names = (
        "soft_node_precision", "soft_node_recall", "soft_node_f1",
        "soft_edge_precision", "soft_edge_recall", "soft_edge_f1",
        "semantic_similarity",
    )
    rows = read_csv_rows(path)
    successful = [row for row in rows if str(row.get("status", "")).lower() == "ok"]
    result = {
        condition: {metric: [] for metric in metric_names}
        for condition in condition_names
    }
    report_metric_values = {
        condition: {metric: {} for metric in metric_names}
        for condition in condition_names
    }
    audit_conditions: dict[str, object] = {}
    problems: list[str] = []

    for condition in condition_names:
        selected = [row for row in successful if row.get("condition") == condition]
        reports = {row.get("report_id", "") for row in selected}
        runs = {row.get("run", "") for row in selected}
        report_counts = Counter(row.get("report_id", "") for row in selected)
        expected_runs = (
            {f"run_{index:02d}" for index in range(1, 6)}
            if condition == "single_pass"
            else {f"round_{index}" for index in range(1, 6)}
        )
        local_problems: list[str] = []
        if len(selected) != EXPECTED_REPORTS * EXPECTED_RUNS:
            local_problems.append(f"expected 560 successful rows, found {len(selected)}")
        if len(reports) != EXPECTED_REPORTS:
            local_problems.append(f"expected 112 reports, found {len(reports)}")
        if runs != expected_runs:
            local_problems.append(
                f"expected runs {sorted(expected_runs)}, found {sorted(runs)}"
            )
        if report_counts and set(report_counts.values()) != {EXPECTED_RUNS}:
            local_problems.append("reports do not all have five observations")
        for row in selected:
            for metric in metric_names:
                value = to_float(row.get(metric, ""))
                if value is None:
                    local_problems.append(f"missing {metric} value")
                    break
                if aggregate_by_report:
                    report_id = str(row.get("report_id", "")).strip().lower()
                    report_metric_values[condition][metric].setdefault(
                        report_id, []
                    ).append(value)
                else:
                    result[condition][metric].append(value)
        if local_problems:
            problems.extend(f"{condition}: {problem}" for problem in local_problems)
        audit_conditions[condition] = {
            "successful_rows": len(selected),
            "independent_reports": len(reports),
            "runs": sorted(runs),
            "complete": not local_problems,
            "problems": local_problems,
        }

    if aggregate_by_report:
        for condition in condition_names:
            for metric in metric_names:
                report_map = report_metric_values[condition][metric]
                result[condition][metric] = [
                    float(np.mean(report_map[report_id]))
                    for report_id in sorted(report_map)
                ]

    return result, {
        "path": str(path.resolve()),
        "total_rows": len(rows),
        "successful_rows": len(successful),
        "conditions": audit_conditions,
        "complete": not problems,
        "problems": problems,
        "plot_unit": "report_mean" if aggregate_by_report else "report_run",
    }


# ── box-plot panel ────────────────────────────────────────────────────────────
def _draw_panel_box(
    ax,
    metric_specs: list[tuple[str, str]],
    series_list: list[tuple[str, dict, str]],
    show_ylabel: bool,
    label_pos: str = "left",
    x_pad: float | None = None,
) -> plt.Line2D | None:
    """Draw one box-plot panel.

    metric_specs  – list of (metric_key, display_name)
    series_list   – list of (condition_label, data_dict, color)
    label_pos     – "above" (staggered above upper cap) or "left" (rotated, left of box)
    Returns a Line2D handle for the mean-marker legend entry, or None.
    """
    ax.grid(axis="y", color="#E6E6E6", linewidth=0.8, zorder=0)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_linewidth(0.8)
    ax.spines["bottom"].set_linewidth(0.8)
    ax.tick_params(length=4, width=0.8)

    n_conditions = len(series_list)
    n_metrics = len(metric_specs)
    mean_label_fontsize = 9 if n_metrics >= 3 else 11
    spacing = max(n_conditions * 1.0, 2.0)
    group_centers = np.arange(n_metrics, dtype=float) * spacing
    half = (n_conditions - 1) / 2.0
    offsets = np.array([(i - half) * 0.9 for i in range(n_conditions)])
    width = 0.52
    mean_handle = None

    for metric_index, (metric_key, _) in enumerate(metric_specs):
        pending_above: list[tuple[float, float, float]] = []
        # Each tuple is (position, mean_value, label_y).  label_y is based on
        # that condition's own highest visible mark, not the group maximum.

        for cond_index, (_, data_map, color) in enumerate(series_list):
            series = data_map.get(metric_key, [])
            if not series:
                continue
            position = float(group_centers[metric_index] + offsets[cond_index])

            bp = ax.boxplot(
                [series],
                positions=[position],
                widths=width,
                patch_artist=True,
                showmeans=False,
                showfliers=True,
                whiskerprops=dict(color="#555555", linewidth=0.9),
                capprops=dict(color="#555555", linewidth=0.9),
                medianprops=dict(color="#111111", linewidth=1.6),
                flierprops=dict(
                    marker="o", markersize=3,
                    markerfacecolor=color, markeredgecolor="#444444",
                    markeredgewidth=0.4, alpha=0.55,
                ),
            )
            bp["boxes"][0].set_facecolor(color)
            bp["boxes"][0].set_edgecolor("#444444")
            bp["boxes"][0].set_linewidth(0.9)
            bp["boxes"][0].set_alpha(0.78)

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
            if label_pos == "above":
                upper_cap_y = float(bp["caps"][1].get_ydata()[0])
                highest_visible_y = upper_cap_y
                flier_y = np.asarray(bp["fliers"][0].get_ydata(), dtype=float)
                finite_flier_y = flier_y[np.isfinite(flier_y)]
                if finite_flier_y.size:
                    highest_visible_y = max(
                        highest_visible_y, float(np.max(finite_flier_y))
                    )
                pending_above.append(
                    (position, mean_value, highest_visible_y + 0.02)
                )
            else:
                ax.text(
                    position - width / 2 - 0.15, mean_value, f"{mean_value:.3f}",
                    ha="center", va="center", fontsize=12, color="#222222",
                    rotation=90,
                )

        if label_pos == "above":
            for pos, mean_val, text_y in pending_above:
                ax.text(
                    pos, text_y, f"{mean_val:.3f}",
                    ha="center", va="bottom", fontsize=mean_label_fontsize,
                    color="#222222",
                )

    # Dashed vertical separators between metric groups
    for i in range(n_metrics - 1):
        mid = (group_centers[i] + group_centers[i + 1]) / 2.0
        ax.axvline(mid, color="#BBBBBB", linewidth=0.8, linestyle="--", zorder=0)

    ax.set_xticks(group_centers)
    ax.set_xticklabels([name for _, name in metric_specs])
    ax.set_ylim(0.0, 1.14 if label_pos == "above" else 1.08)
    if x_pad is not None:
        ax.set_xlim(
            group_centers[0] + offsets[0] - width / 2 - x_pad,
            group_centers[-1] + offsets[-1] + width / 2 + x_pad,
        )
    if show_ylabel:
        ax.set_ylabel("Score")
    return mean_handle


# ── combined 2×2 box-plot figure ──────────────────────────────────────────────
def audit_five_run_input(
    path: Path,
    expected_run_labels: set[str],
    *,
    allow_incomplete: bool,
) -> dict[str, object]:
    rows = read_csv_rows(path)
    successful = [row for row in rows if str(row.get("status", "")).lower() == "ok"]
    run_labels = {str(row.get("round", "")) for row in successful}
    report_counts = Counter(
        f"{row.get('batch_id', '').lower()}/{row.get('case_id', '').lower()}"
        for row in successful
    )
    expected_rows = EXPECTED_REPORTS * EXPECTED_RUNS
    problems: list[str] = []
    if len(rows) != expected_rows:
        problems.append(f"expected {expected_rows} rows, found {len(rows)}")
    if len(successful) != expected_rows:
        problems.append(f"expected {expected_rows} successful rows, found {len(successful)}")
    if run_labels != expected_run_labels:
        problems.append(
            f"expected runs {sorted(expected_run_labels)}, found {sorted(run_labels)}"
        )
    if len(report_counts) != EXPECTED_REPORTS:
        problems.append(f"expected {EXPECTED_REPORTS} reports, found {len(report_counts)}")
    if report_counts and set(report_counts.values()) != {EXPECTED_RUNS}:
        problems.append("reports do not all have exactly five successful observations")
    if problems and not allow_incomplete:
        raise RuntimeError(f"Five-run input audit failed for {path}: " + "; ".join(problems))
    return {
        "path": str(path.resolve()),
        "total_rows": len(rows),
        "successful_rows": len(successful),
        "independent_reports": len(report_counts),
        "run_labels": sorted(run_labels),
        "complete": not problems,
        "problems": problems,
    }


def _save_combined_boxplot_variants(
    *,
    struct_series: list[tuple[str, dict, str]],
    auxiliary_series: list[tuple[str, dict, str]],
    colors: list[str],
    output_dir: Path,
    legacy_output_dir: Path | None,
    filename_infix: str = "",
) -> list[Path]:
    """Render the unchanged 2x2 construction for one observation unit."""
    saved: list[Path] = []
    for label_pos in ("above", "left"):
        fig, axes = plt.subplots(2, 2, figsize=(13.0, 8.4))
        panel_specs = [
            (
                axes[0, 0], "(a) Structural Similarity",
                [("wl_kernel", "WLS"), ("one_minus_norm_ged", "GES")],
                struct_series,
            ),
            (
                axes[0, 1], "(b) Node Matching",
                [("soft_node_precision", "Precision"),
                 ("soft_node_recall", "Recall"),
                 ("soft_node_f1", "F1")],
                auxiliary_series,
            ),
            (
                axes[1, 0], "(c) Edge Matching",
                [("soft_edge_precision", "Precision"),
                 ("soft_edge_recall", "Recall"),
                 ("soft_edge_f1", "F1")],
                auxiliary_series,
            ),
            (
                axes[1, 1], "(d) Semantic Similarity",
                [("semantic_similarity", "Semantic similarity")],
                auxiliary_series,
            ),
        ]
        for ax, title, metric_specs, series in panel_specs:
            _draw_panel_box(
                ax=ax,
                metric_specs=metric_specs,
                series_list=series,
                show_ylabel=True,
                label_pos=label_pos,
                x_pad=0.55,
            )
            ax.set_title(title, loc="left", fontweight="bold")
        legend_handles = [
            plt.Line2D([0], [0], color=color, linewidth=9, alpha=0.82)
            for color in colors
        ]
        mean_handle = plt.Line2D(
            [0], [0], marker="D", linestyle="",
            markerfacecolor="white", markeredgecolor="#111111",
            color="#111111", markersize=6,
        )
        legend_handles.append(mean_handle)
        legend_labels = [
            "Single Pass", "No Revision", "Revision", "Revision + FS", "Mean"
        ]
        fig.subplots_adjust(bottom=0.12, hspace=0.35, wspace=0.23)
        fig.legend(
            legend_handles, legend_labels,
            loc="lower center", ncol=5, frameon=False,
            bbox_to_anchor=(0.5, 0.01),
        )

        figure_base = (
            output_dir
            / f"five_run_combined_boxplot{filename_infix}_label_{label_pos}"
        )
        fig.savefig(figure_base.with_suffix(".pdf"))
        fig.savefig(figure_base.with_suffix(".png"))
        fig.savefig(figure_base.with_suffix(".svg"))
        if legacy_output_dir is not None:
            legacy_dir = ensure_dir(legacy_output_dir.resolve())
            legacy_base = (
                legacy_dir
                / f"combined_comparison_boxplot{filename_infix}_label_{label_pos}"
            )
            fig.savefig(legacy_base.with_suffix(".pdf"))
            fig.savefig(legacy_base.with_suffix(".png"))
            fig.savefig(legacy_base.with_suffix(".svg"))
            print(f"Saved compatibility copy: {legacy_base.with_suffix('.png')}")
        plt.close(fig)
        print(f"Saved: {figure_base.with_suffix('.pdf')}")
        saved.append(figure_base.with_suffix(".pdf"))
    return saved


def plot_combined_figure_boxplot(
    no_revision_root: Path,
    revision_root: Path,
    few_shot_root: Path,
    single_pass_root: Path,
    auxiliary_root: Path,
    output_dir: Path,
    *,
    allow_incomplete: bool = False,
    legacy_output_dir: Path | None = None,
) -> Path:
    """Plot original and paired five-run structural and auxiliary metrics."""
    # Preserve the original gray-to-blue visual hierarchy. Single Pass is
    # added as a lighter gray at the far left without changing the established
    # colors for the three main-method conditions.
    colors = ["#D0D0D0", "#A8A8A8", "#5E81AC", "#2E4A6E"]
    paths = {
        "no_revision": find_latest_case_scores(no_revision_root),
        "revision": find_latest_case_scores(revision_root),
        "few_shot": find_latest_case_scores(few_shot_root),
        "single_pass": find_latest_case_scores(single_pass_root),
    }
    audits = {
        "no_revision": audit_five_run_input(
            paths["no_revision"],
            {f"round_{index}" for index in range(1, 6)},
            allow_incomplete=allow_incomplete,
        ),
        "revision": audit_five_run_input(
            paths["revision"],
            {f"round_{index}" for index in range(1, 6)},
            allow_incomplete=allow_incomplete,
        ),
        "few_shot": audit_five_run_input(
            paths["few_shot"],
            {f"round_{index}" for index in range(1, 6)},
            allow_incomplete=allow_incomplete,
        ),
        "single_pass": audit_five_run_input(
            paths["single_pass"],
            {f"run_{index:02d}" for index in range(1, 6)},
            allow_incomplete=allow_incomplete,
        ),
    }
    metrics_report_run = {
        name: collect_similarity_metrics(path) for name, path in paths.items()
    }
    metrics_report_mean = {
        name: collect_similarity_metrics(path, aggregate_by_report=True)
        for name, path in paths.items()
    }
    auxiliary_path = find_latest_named_csv(auxiliary_root, FINAL_AUXILIARY_FILENAME)
    auxiliary_report_run, auxiliary_audit = collect_final_auxiliary_metrics(
        auxiliary_path
    )
    auxiliary_report_mean, auxiliary_paired_audit = collect_final_auxiliary_metrics(
        auxiliary_path, aggregate_by_report=True
    )
    if auxiliary_audit["problems"] and not allow_incomplete:
        raise RuntimeError(
            "Five-run auxiliary input audit failed: "
            + "; ".join(auxiliary_audit["problems"])
        )

    if auxiliary_paired_audit["problems"] and not allow_incomplete:
        raise RuntimeError(
            "Five-run paired auxiliary input audit failed: "
            + "; ".join(auxiliary_paired_audit["problems"])
        )

    def make_struct_series(
        metrics: dict[str, dict[str, list[float]]],
    ) -> list[tuple[str, dict, str]]:
        return [
            ("Single Pass", {
                "wl_kernel": metrics["single_pass"]["wl_kernel_no_rev"],
                "one_minus_norm_ged": metrics["single_pass"]["one_minus_norm_ged_no_rev"],
            }, colors[0]),
            ("No Revision", {
                "wl_kernel": metrics["no_revision"]["wl_kernel_no_rev"],
                "one_minus_norm_ged": metrics["no_revision"]["one_minus_norm_ged_no_rev"],
            }, colors[1]),
            ("Revision", {
                "wl_kernel": metrics["revision"]["wl_kernel"],
                "one_minus_norm_ged": metrics["revision"]["one_minus_norm_ged"],
            }, colors[2]),
            ("Revision + FS", {
                "wl_kernel": metrics["few_shot"]["wl_kernel"],
                "one_minus_norm_ged": metrics["few_shot"]["one_minus_norm_ged"],
            }, colors[3]),
        ]

    struct_series_report_run = make_struct_series(metrics_report_run)
    struct_series_report_mean = make_struct_series(metrics_report_mean)
    condition_specs = [
        ("Single Pass", "single_pass", colors[0]),
        ("No Revision", "no_revision", colors[1]),
        ("Revision", "revision", colors[2]),
        ("Revision + FS", "revision_fs", colors[3]),
    ]
    auxiliary_series_report_run = [
        (label, auxiliary_report_run[condition], color)
        for label, condition, color in condition_specs
    ]
    auxiliary_series_report_mean = [
        (label, auxiliary_report_mean[condition], color)
        for label, condition, color in condition_specs
    ]

    plt.style.use("default")
    plt.rcParams.update({
        "figure.dpi": 150, "savefig.dpi": 300,
        "figure.facecolor": "white", "axes.facecolor": "white",
        "savefig.facecolor": "white", "savefig.bbox": "tight",
        "font.family": "serif",
        "font.serif": ["Times New Roman", "DejaVu Serif"],
        "font.size": 12,
        "axes.labelsize": 12,
        "axes.titlesize": 12,
        "xtick.labelsize": 11,
        "ytick.labelsize": 11,
        "legend.fontsize": 10,
    })

    output_dir = ensure_dir(output_dir.resolve())
    saved = _save_combined_boxplot_variants(
        struct_series=struct_series_report_run,
        auxiliary_series=auxiliary_series_report_run,
        colors=colors,
        output_dir=output_dir,
        legacy_output_dir=legacy_output_dir,
    )
    paired_saved = _save_combined_boxplot_variants(
        struct_series=struct_series_report_mean,
        auxiliary_series=auxiliary_series_report_mean,
        colors=colors,
        output_dir=output_dir,
        legacy_output_dir=legacy_output_dir,
        filename_infix="_paired",
    )

    audit_path = output_dir / "five_run_combined_boxplot_audit.json"
    audit_path.write_text(
        json.dumps(
            {
                "conditions": {
                    "Single Pass": "single_pass generated graph",
                    "No Revision": "two-stage no_revision graph",
                    "Revision": "revision source accept-all revised graph",
                    "Revision + FS": "few_shot accept-all revised graph",
                },
                "expected_reports": EXPECTED_REPORTS,
                "expected_runs": EXPECTED_RUNS,
                "allow_incomplete": allow_incomplete,
                "plot_type": "boxplot_original_and_report_mean_paired",
                "legacy_output_dir": (
                    None if legacy_output_dir is None else str(legacy_output_dir.resolve())
                ),
                "inputs": audits,
                "auxiliary_input_report_run": auxiliary_audit,
                "auxiliary_input_report_mean": auxiliary_paired_audit,
                "original_report_run_plotted_observations": {
                    label: {
                        metric: len(values)
                        for metric, values in data.items()
                    }
                    for label, data, _ in struct_series_report_run
                },
                "original_auxiliary_plotted_observations": {
                    label: {metric: len(values) for metric, values in data.items()}
                    for label, data, _ in auxiliary_series_report_run
                },
                "paired_report_mean_plotted_observations": {
                    label: {
                        metric: len(values)
                        for metric, values in data.items()
                    }
                    for label, data, _ in struct_series_report_mean
                },
                "paired_auxiliary_plotted_observations": {
                    label: {metric: len(values) for metric, values in data.items()}
                    for label, data, _ in auxiliary_series_report_mean
                },
                "original_outputs": [str(path) for path in saved],
                "paired_outputs": [str(path) for path in paired_saved],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Audit: {audit_path}")

    return saved[0]


def main() -> None:
    args = parse_args()
    plot_combined_figure_boxplot(
        no_revision_root=args.no_revision_root,
        revision_root=args.revision_root,
        few_shot_root=args.few_shot_root,
        single_pass_root=args.single_pass_root,
        auxiliary_root=args.auxiliary_root,
        output_dir=args.output_dir,
        allow_incomplete=args.allow_incomplete,
        legacy_output_dir=(None if args.no_legacy_aliases else args.legacy_output_dir),
    )


if __name__ == "__main__":
    main()
