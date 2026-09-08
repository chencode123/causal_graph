#!/usr/bin/env python3
"""Draw a 3x3 condition-oriented mixed-effects evaluation figure.

The figure combines structural and auxiliary graph-evaluation results for the
same 112 held-out reports across five runs and four conditions.  Boxplots show
per-report five-run means.  Diamonds and error bars show run-adjusted marginal
means and 95% confidence intervals from

    metric ~ condition + run + (1 | report_id).

Three sequential paired contrasts are annotated in each panel.  Holm
adjustment is nevertheless applied once across all six planned contrasts for
all nine metrics, and the complete results are written beside the figure.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
import numpy as np
import pandas as pd

from gen_fig_paired_mixed_effects import (
    CONDITION_COLORS,
    CONDITION_LABELS,
    DEFAULT_CONDITION_PATHS,
    PLANNED_CONTRASTS,
    analyze_metric,
    apply_holm,
    fit_mixed_model,
    load_condition_csv,
    marginal_design_vector,
    normalize_run,
    retain_complete_reports,
    sha256_file,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
def latest_auxiliary_path() -> Path:
    root = (
        PROJECT_ROOT / "runs" / "stability_test" / "evaluation_final" / "auxiliary"
    )
    candidates = sorted(
        root.glob("*/combined_auxiliary_case_scores.csv"),
        key=lambda path: path.parent.name,
        reverse=True,
    )
    return candidates[0] if candidates else root / "combined_auxiliary_case_scores.csv"


DEFAULT_AUXILIARY_PATH = latest_auxiliary_path()
DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT / "runs" / "stability_test" / "statistical_analysis" / "paired_effects"
)

STRUCTURAL_METRICS = (
    "graph_edit_similarity",
    "structural_similarity",
)
AUXILIARY_METRICS = (
    "soft_node_precision",
    "soft_node_recall",
    "soft_node_f1",
    "soft_edge_precision",
    "soft_edge_recall",
    "soft_edge_f1",
    "semantic_similarity",
)
ALL_METRICS = STRUCTURAL_METRICS + AUXILIARY_METRICS

METRIC_LABELS = {
    "graph_edit_similarity": "GES",
    "structural_similarity": "WLS",
    "soft_node_precision": "Node precision",
    "soft_node_recall": "Node recall",
    "soft_node_f1": "Node F1",
    "soft_edge_precision": "Edge precision",
    "soft_edge_recall": "Edge recall",
    "soft_edge_f1": "Edge F1",
    "semantic_similarity": "Semantic similarity",
}

PANEL_ORDER = (
    "graph_edit_similarity",
    "structural_similarity",
    "semantic_similarity",
    "soft_node_precision",
    "soft_node_recall",
    "soft_node_f1",
    "soft_edge_precision",
    "soft_edge_recall",
    "soft_edge_f1",
)
CONDITION_ORDER = ("single_pass", "no_revision", "revision", "revision_fs")
DISPLAY_CONTRASTS = (
    ("no_revision", "single_pass"),
    ("revision", "no_revision"),
    ("revision_fs", "revision"),
)
AUXILIARY_CONDITION_MAP = {
    "single_pass": "single_pass",
    "no_revision": "no_revision",
    "revision": "revision",
    "revision_fs": "revision_fs",
}


def load_merged_panel(auxiliary_path: Path) -> tuple[pd.DataFrame, dict[str, object]]:
    """Load and one-to-one merge structural and auxiliary report-run panels."""
    structural_frames: list[pd.DataFrame] = []
    structural_audits: list[dict[str, object]] = []
    for condition in CONDITION_ORDER:
        frame, audit, failed = load_condition_csv(
            condition,
            DEFAULT_CONDITION_PATHS[condition],
            list(STRUCTURAL_METRICS),
        )
        if failed:
            raise ValueError(f"Structural input for {condition} contains failed rows.")
        frame["report_id"] = frame["report_id"].str.strip().str.lower()
        structural_frames.append(
            frame[["condition", "report_id", "run", *STRUCTURAL_METRICS]].copy()
        )
        structural_audits.append(
            {
                "condition": condition,
                "path": audit.path,
                "sha256": audit.sha256,
                "ok_rows": audit.ok_rows,
            }
        )
    structural = pd.concat(structural_frames, ignore_index=True)

    auxiliary_resolved = auxiliary_path.resolve()
    if not auxiliary_resolved.is_file():
        raise FileNotFoundError(f"Missing auxiliary input: {auxiliary_resolved}")
    auxiliary = pd.read_csv(
        auxiliary_resolved,
        dtype={"batch_id": str, "case_id": str, "report_id": str},
    )
    required = {"condition", "run", "report_id", "status", *AUXILIARY_METRICS}
    missing = sorted(required - set(auxiliary.columns))
    if missing:
        raise ValueError(f"Auxiliary input is missing columns: {missing}")
    failed_auxiliary = auxiliary.loc[auxiliary["status"] != "ok"]
    if not failed_auxiliary.empty:
        raise ValueError(f"Auxiliary input contains {len(failed_auxiliary)} failed rows.")
    auxiliary = auxiliary.loc[auxiliary["status"] == "ok"].copy()
    auxiliary["condition"] = auxiliary["condition"].str.strip().str.lower()
    raw_auxiliary_conditions = sorted(auxiliary["condition"].unique().tolist())
    unmapped_conditions = sorted(
        set(raw_auxiliary_conditions) - set(AUXILIARY_CONDITION_MAP)
    )
    if unmapped_conditions:
        raise ValueError(f"Unmapped auxiliary conditions: {unmapped_conditions}")
    auxiliary["condition"] = auxiliary["condition"].map(AUXILIARY_CONDITION_MAP)
    auxiliary["report_id"] = auxiliary["report_id"].str.strip().str.lower()
    auxiliary["run"] = auxiliary["run"].map(normalize_run)
    unexpected_conditions = sorted(set(auxiliary["condition"]) - set(CONDITION_ORDER))
    if unexpected_conditions:
        raise ValueError(f"Unexpected auxiliary conditions: {unexpected_conditions}")
    keys = ["condition", "report_id", "run"]
    duplicates = auxiliary.duplicated(keys, keep=False)
    if duplicates.any():
        examples = auxiliary.loc[duplicates, keys].head(10).to_dict("records")
        raise ValueError(f"Duplicate auxiliary panel rows: {examples}")
    for metric in AUXILIARY_METRICS:
        auxiliary[metric] = pd.to_numeric(auxiliary[metric], errors="coerce")
        if auxiliary[metric].isna().any():
            raise ValueError(f"Auxiliary metric {metric} contains missing values.")

    structural_keys = set(map(tuple, structural[keys].to_numpy()))
    auxiliary_keys = set(map(tuple, auxiliary[keys].to_numpy()))
    if structural_keys != auxiliary_keys:
        raise ValueError(
            "Structural and auxiliary panel keys do not match: "
            f"structural_only={len(structural_keys - auxiliary_keys)}, "
            f"auxiliary_only={len(auxiliary_keys - structural_keys)}"
        )
    merged = structural.merge(
        auxiliary[[*keys, *AUXILIARY_METRICS]],
        on=keys,
        how="inner",
        validate="one_to_one",
    )
    retained, incomplete, panel_audit = retain_complete_reports(
        merged,
        list(CONDITION_ORDER),
        [1, 2, 3, 4, 5],
        allow_incomplete=False,
        expected_reports=112,
    )
    if incomplete:
        raise AssertionError("Strict complete-panel validation unexpectedly retained gaps.")
    audit = {
        "structural_sources": structural_audits,
        "auxiliary_source": {
            "path": str(auxiliary_resolved),
            "sha256": sha256_file(auxiliary_resolved),
            "ok_rows": int(len(auxiliary)),
            "source_conditions": raw_auxiliary_conditions,
            "condition_map": AUXILIARY_CONDITION_MAP,
        },
        "merge_validation": "one_to_one on condition/report_id/run",
        "panel": panel_audit,
    }
    return retained, audit


def estimate_adjusted_means(
    data: pd.DataFrame, metric: str, runs: list[int]
) -> tuple[list[dict[str, object]], dict[str, object]]:
    metric_data = data[["report_id", "condition", "run", metric]].rename(
        columns={metric: "value"}
    )
    result, fit_data, optimizer, fit_errors = fit_mixed_model(metric_data)
    fixed_cov = result.cov_params().loc[result.fe_params.index, result.fe_params.index]
    beta = result.fe_params.to_numpy(dtype=float)
    covariance = fixed_cov.to_numpy(dtype=float)
    rows: list[dict[str, object]] = []
    for condition in CONDITION_ORDER:
        vector = marginal_design_vector(result, condition, runs)
        estimate = float(vector @ beta)
        standard_error = float(np.sqrt(vector @ covariance @ vector))
        rows.append(
            {
                "metric": metric,
                "metric_label": METRIC_LABELS[metric],
                "condition": condition,
                "condition_label": CONDITION_LABELS[condition],
                "adjusted_mean": estimate,
                "standard_error": standard_error,
                "ci_lower": estimate - 1.959963984540054 * standard_error,
                "ci_upper": estimate + 1.959963984540054 * standard_error,
                "reports": int(fit_data["report_id"].nunique()),
                "observations": int(len(fit_data)),
            }
        )
    audit = {
        "metric": metric,
        "formula": "value ~ C(condition) + C(run) + (1 | report_id)",
        "optimizer": optimizer,
        "fallback_errors": fit_errors,
        "converged": bool(result.converged),
        "observations": int(result.nobs),
        "reports": int(fit_data["report_id"].nunique()),
        "report_random_intercept_variance": float(result.cov_re.iloc[0, 0]),
        "residual_variance": float(result.scale),
    }
    return rows, audit


def add_contrast_bracket(
    axis: plt.Axes,
    x_left: float,
    x_right: float,
    y: float,
    cap_height: float,
    label: str,
) -> None:
    axis.plot(
        [x_left, x_left, x_right, x_right],
        [y, y + cap_height, y + cap_height, y],
        color="#555555",
        linewidth=0.8,
        clip_on=False,
        zorder=5,
    )
    axis.text(
        (x_left + x_right) / 2,
        y + cap_height * 1.35,
        label,
        ha="center",
        va="bottom",
        fontsize=16,
        color="#333333",
        clip_on=False,
    )


def draw_figure(
    data: pd.DataFrame,
    adjusted_means: pd.DataFrame,
    contrasts: pd.DataFrame,
    output_dir: Path,
) -> None:
    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": ["Times New Roman", "DejaVu Serif"],
            "font.size": 20,
            "axes.labelsize": 20,
            "axes.titlesize": 22,
            "xtick.labelsize": 18,
            "ytick.labelsize": 18,
            "legend.fontsize": 18,
            "figure.dpi": 150,
            "savefig.dpi": 300,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.facecolor": "white",
            "savefig.bbox": "tight",
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )
    fig, axes = plt.subplots(3, 3, figsize=(20.0, 15.2))
    x_positions = np.arange(len(CONDITION_ORDER), dtype=float)
    short_condition_labels = ("Single\nPass", "No\nRevision", "Revision", "Revision\n+ FS")

    for panel_index, metric in enumerate(PANEL_ORDER):
        axis = axes.flat[panel_index]
        axis.grid(axis="y", color="#E6E6E6", linewidth=0.8, zorder=0)
        axis.spines["left"].set_linewidth(0.8)
        axis.spines["bottom"].set_linewidth(0.8)
        axis.tick_params(length=4, width=0.8)

        metric_report_means = (
            data.groupby(["report_id", "condition"], observed=True)[metric]
            .mean()
            .unstack()
        )
        plotted_values: list[float] = []
        for x, condition in zip(x_positions, CONDITION_ORDER):
            values = metric_report_means[condition].dropna().to_numpy(dtype=float)
            plotted_values.extend(values.tolist())
            bp = axis.boxplot(
                [values],
                positions=[x],
                widths=0.52,
                patch_artist=True,
                showmeans=False,
                showfliers=True,
                whiskerprops={"color": "#555555", "linewidth": 0.9},
                capprops={"color": "#555555", "linewidth": 0.9},
                medianprops={"color": "#111111", "linewidth": 1.5},
                flierprops={
                    "marker": "o",
                    "markersize": 2.7,
                    "markerfacecolor": CONDITION_COLORS[condition],
                    "markeredgecolor": "#444444",
                    "markeredgewidth": 0.35,
                    "alpha": 0.5,
                },
            )
            bp["boxes"][0].set_facecolor(CONDITION_COLORS[condition])
            bp["boxes"][0].set_edgecolor("#444444")
            bp["boxes"][0].set_linewidth(0.9)
            bp["boxes"][0].set_alpha(0.72)

        metric_means = adjusted_means.loc[
            adjusted_means["metric"] == metric
        ].set_index("condition").loc[list(CONDITION_ORDER)]
        mean_values = metric_means["adjusted_mean"].to_numpy(dtype=float)
        lower_values = metric_means["ci_lower"].to_numpy(dtype=float)
        upper_values = metric_means["ci_upper"].to_numpy(dtype=float)
        axis.plot(
            x_positions,
            mean_values,
            color="#555555",
            linewidth=1.0,
            linestyle="--",
            zorder=3,
        )
        for x, condition, mean, lower, upper in zip(
            x_positions,
            CONDITION_ORDER,
            mean_values,
            lower_values,
            upper_values,
        ):
            axis.errorbar(
                x,
                mean,
                yerr=np.array([[mean - lower], [upper - mean]]),
                fmt="D",
                markersize=5.5,
                markerfacecolor="white",
                markeredgecolor="#111111",
                markeredgewidth=0.9,
                color="#111111",
                linewidth=1.2,
                capsize=2.8,
                zorder=4,
            )
            axis.annotate(
                f"{mean:.3f}",
                xy=(x, mean),
                xytext=(0, 8),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=16,
                color="#222222",
                bbox={
                    "boxstyle": "round,pad=0.12",
                    "facecolor": "white",
                    "edgecolor": "none",
                    "alpha": 0.82,
                },
                zorder=6,
            )

        core_min = min(min(plotted_values), float(np.min(lower_values)))
        core_max = max(max(plotted_values), float(np.max(upper_values)))
        core_span = max(core_max - core_min, 0.06)
        bracket_base = core_max + 0.04 * core_span
        bracket_gap = 0.08 * core_span
        cap_height = 0.015 * core_span
        metric_contrasts = contrasts.loc[contrasts["metric"] == metric].set_index(
            "contrast"
        )
        for level, (condition_a, condition_b) in enumerate(DISPLAY_CONTRASTS):
            contrast_key = f"{condition_a} - {condition_b}"
            item = metric_contrasts.loc[contrast_key]
            dz = float(item["cohens_dz"])
            x_a = float(CONDITION_ORDER.index(condition_a))
            x_b = float(CONDITION_ORDER.index(condition_b))
            add_contrast_bracket(
                axis,
                min(x_a, x_b),
                max(x_a, x_b),
                bracket_base + level * bracket_gap,
                cap_height,
                f"$d_z$={dz:.2f}",
            )

        axis.set_ylim(
            max(0.0, core_min - 0.12 * core_span),
            bracket_base + (len(DISPLAY_CONTRASTS) - 1) * bracket_gap + 0.08 * core_span,
        )
        bounded_ticks = [
            float(tick)
            for tick in axis.get_yticks()
            if axis.get_ylim()[0] <= float(tick) <= 1.0000001
        ]
        axis.set_yticks(bounded_ticks)
        axis.set_xlim(-0.55, 3.55)
        axis.set_xticks(x_positions)
        axis.set_xticklabels(short_condition_labels)
        axis.set_ylabel("Score")
        axis.set_title(
            f"({chr(ord('a') + panel_index)}) {METRIC_LABELS[metric]}",
            loc="left",
            fontweight="bold",
        )

    legend_handles = [
        Patch(
            facecolor=CONDITION_COLORS[condition],
            edgecolor="#444444",
            alpha=0.72,
            label=CONDITION_LABELS[condition],
        )
        for condition in CONDITION_ORDER
    ]
    legend_handles.append(
        Line2D(
            [0],
            [0],
            marker="D",
            linestyle="--",
            color="#555555",
            markerfacecolor="white",
            markeredgecolor="#111111",
            markersize=5.5,
            label="Mixed-effects adjusted mean (95% CI)",
        )
    )
    fig.legend(
        handles=legend_handles,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.994),
        ncol=5,
        frameon=False,
    )
    fig.text(
        0.5,
        0.012,
        "Boxes show five-run report means (n = 112). Brackets report paired Cohen's $d_z$ "
        "for the right condition minus the left condition. Complete confidence intervals and "
        "Holm-adjusted p-values are reported in the accompanying results table. Panels use "
        "metric-specific y-axis ranges.",
        ha="center",
        va="bottom",
        fontsize=14,
        color="#444444",
    )
    fig.subplots_adjust(left=0.07, right=0.985, top=0.93, bottom=0.09, hspace=0.48, wspace=0.24)
    for suffix in ("pdf", "png", "svg"):
        path = output_dir / f"fig_mixed_effects_by_condition.{suffix}"
        if suffix == "png":
            fig.savefig(path, dpi=300)
        else:
            fig.savefig(path)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Draw a 3x3 condition-oriented mixed-effects evaluation figure."
    )
    parser.add_argument("--auxiliary-path", type=Path, default=DEFAULT_AUXILIARY_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--bootstrap-resamples", type=int, default=10_000)
    parser.add_argument("--random-seed", type=int, default=20260831)
    args = parser.parse_args()
    if args.bootstrap_resamples < 1000:
        parser.error("--bootstrap-resamples must be at least 1000")

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    data, input_audit = load_merged_panel(args.auxiliary_path)

    rng = np.random.default_rng(args.random_seed)
    contrast_rows: list[dict[str, object]] = []
    adjusted_mean_rows: list[dict[str, object]] = []
    contrast_model_audits: list[dict[str, object]] = []
    mean_model_audits: list[dict[str, object]] = []
    for metric in ALL_METRICS:
        rows, model_audit = analyze_metric(
            data,
            metric,
            list(PLANNED_CONTRASTS),
            [1, 2, 3, 4, 5],
            args.bootstrap_resamples,
            rng,
        )
        for row in rows:
            row["metric_label"] = METRIC_LABELS[metric]
        contrast_rows.extend(rows)
        contrast_model_audits.append(model_audit)
        mean_rows, mean_audit = estimate_adjusted_means(data, metric, [1, 2, 3, 4, 5])
        adjusted_mean_rows.extend(mean_rows)
        mean_model_audits.append(mean_audit)

    apply_holm(contrast_rows)
    contrasts = pd.DataFrame(contrast_rows)
    adjusted_means = pd.DataFrame(adjusted_mean_rows)
    contrasts.to_csv(output_dir / "condition_mixed_effects_contrasts.csv", index=False)
    adjusted_means.to_csv(output_dir / "condition_adjusted_means.csv", index=False)
    data.to_csv(output_dir / "condition_analysis_long_data.csv", index=False)
    draw_figure(data, adjusted_means, contrasts, output_dir)

    audit = {
        "analysis": "condition-oriented repeated-measures mixed-effects evaluation",
        "input_audit": input_audit,
        "independent_unit": "report_id",
        "independent_reports": int(data["report_id"].nunique()),
        "repeated_observations": int(len(data)),
        "conditions": list(CONDITION_ORDER),
        "runs": [1, 2, 3, 4, 5],
        "metrics": list(ALL_METRICS),
        "model": "metric ~ condition + run + (1 | report_id)",
        "all_planned_contrasts": [f"{a} - {b}" for a, b in PLANNED_CONTRASTS],
        "displayed_sequential_contrasts": [f"{a} - {b}" for a, b in DISPLAY_CONTRASTS],
        "effect_size": "Cohen's dz from per-report five-run condition means",
        "effect_size_ci": f"percentile bootstrap with {args.bootstrap_resamples} report resamples",
        "multiplicity_control": "one Holm correction across all 54 metric-by-contrast tests",
        "boxplot_unit": "per-report mean across five runs",
        "diamond": "mixed-effects adjusted marginal mean with 95% confidence interval",
        "diamond_value_label": "adjusted marginal mean shown to three decimals",
        "figure_significance_symbols": "none; adjusted p-values remain in the contrast table",
        "panel_y_axes": "metric-specific",
        "random_seed": args.random_seed,
        "contrast_model_audits": contrast_model_audits,
        "adjusted_mean_model_audits": mean_model_audits,
    }
    (output_dir / "condition_mixed_effects_audit.json").write_text(
        json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Complete reports: {data['report_id'].nunique()}")
    print(f"Retained rows: {len(data)}")
    print(f"Metrics: {len(ALL_METRICS)}")
    print(f"Holm family: {len(contrast_rows)} tests")
    print(f"Saved outputs to: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
