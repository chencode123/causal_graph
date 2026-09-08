#!/usr/bin/env python3
"""Run paired mixed-effects analyses and draw a publication forest plot.

The script consumes the structural ``case_scores.csv`` files for the single-pass,
two-stage No Revision, revision, and few-shot experiments. It constructs the four
manuscript conditions from separate audited sources. Incident cases are independent
units and model runs are repeated
observations.  By default, the script refuses
incomplete condition-report-run panels.  ``--allow-incomplete`` drops entire
reports that do not have every condition and run, and marks the output as
preliminary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import warnings
from dataclasses import asdict, dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import norm

try:
    import statsmodels.formula.api as smf
    from patsy import build_design_matrices
    from statsmodels.stats.multitest import multipletests
except ImportError as exc:  # pragma: no cover - environment-dependent guidance
    raise SystemExit(
        "Missing dependency. Install it in the active environment with: "
        "python -m pip install statsmodels"
    ) from exc


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT / "runs" / "stability_test" / "statistical_analysis" / "paired_effects"
)

DEFAULT_CONDITION_PATHS = {
    "single_pass": PROJECT_ROOT
    / "runs"
    / "stability_test"
    / "evaluation_final"
    / "single_pass"
    / "20260828_141620"
    / "case_scores.csv",
    "no_revision": PROJECT_ROOT
    / "runs"
    / "stability_test"
    / "evaluation_final"
    / "no_revision"
    / "20260902_164902"
    / "case_scores.csv",
    "revision": PROJECT_ROOT
    / "runs"
    / "stability_test"
    / "evaluation_final"
    / "revision"
    / "20260829_170239"
    / "case_scores.csv",
    "revision_fs": PROJECT_ROOT
    / "runs"
    / "stability_test"
    / "evaluation_final"
    / "few_shot"
    / "20260828_140052"
    / "case_scores.csv",
}

CONDITION_METRIC_COLUMNS = {
    "single_pass": {
        "graph_edit_similarity": "graph_edit_similarity",
        "structural_similarity": "structural_similarity",
    },
    "no_revision": {
        "graph_edit_similarity": "graph_edit_similarity",
        "structural_similarity": "structural_similarity",
    },
    "revision": {
        "graph_edit_similarity": "graph_edit_similarity_accept_all_vs_updated",
        "structural_similarity": "structural_similarity_accept_all_vs_updated",
    },
    "revision_fs": {
        "graph_edit_similarity": "graph_edit_similarity_accept_all_vs_updated",
        "structural_similarity": "structural_similarity_accept_all_vs_updated",
    },
}

METRIC_LABELS = {
    "graph_edit_similarity": "Graph edit similarity (GES)",
    "structural_similarity": "WL structural similarity",
}

CONDITION_LABELS = {
    "single_pass": "Single Pass",
    "no_revision": "No Revision",
    "revision": "Revision",
    "revision_fs": "Revision + FS",
}

PLANNED_CONTRASTS = (
    ("no_revision", "single_pass"),
    ("revision", "no_revision"),
    ("revision_fs", "no_revision"),
    ("revision_fs", "revision"),
    ("revision", "single_pass"),
    ("revision_fs", "single_pass"),
)

CONDITION_COLORS = {
    "single_pass": "#D0D0D0",
    "no_revision": "#A8A8A8",
    "revision": "#5E81AC",
    "revision_fs": "#2E4A6E",
}


@dataclass
class SourceAudit:
    condition: str
    path: str
    sha256: str
    metric_columns: dict[str, str]
    total_rows: int
    ok_rows: int
    failed_rows: int
    unique_reports_with_ok_rows: int
    unique_runs_with_ok_rows: int


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_condition_argument(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("Use NAME=PATH for --condition.")
    name, raw_path = value.split("=", 1)
    name = name.strip()
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise argparse.ArgumentTypeError(f"Invalid condition name: {name!r}")
    return name, Path(raw_path).expanduser()


def normalize_run(value: object) -> int:
    match = re.search(r"(\d+)$", str(value).strip())
    if match is None:
        raise ValueError(f"Cannot infer run number from {value!r}")
    return int(match.group(1))


def load_condition_csv(condition: str, path: Path, metrics: list[str]) -> tuple[pd.DataFrame, SourceAudit, list[dict[str, str]]]:
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"Missing case-score file for {condition}: {resolved}")
    frame = pd.read_csv(resolved, dtype={"batch_id": str, "case_id": str})
    metric_columns = CONDITION_METRIC_COLUMNS[condition]
    missing_mappings = sorted(set(metrics) - set(metric_columns))
    if missing_mappings:
        raise ValueError(
            f"No source-column mapping for {condition} metric(s): {missing_mappings}"
        )
    source_metric_columns = {metric_columns[metric] for metric in metrics}
    required = {"round", "batch_id", "case_id", "status", *source_metric_columns}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{condition} is missing columns: {missing}")

    failed = frame.loc[frame["status"] != "ok", ["round", "batch_id", "case_id", "warnings"]].copy()
    ok = frame.loc[frame["status"] == "ok"].copy()
    ok["condition"] = condition
    ok["report_id"] = ok["batch_id"].str.strip() + "/" + ok["case_id"].str.strip()
    ok["run"] = ok["round"].map(normalize_run)

    key_columns = ["condition", "report_id", "run"]
    duplicates = ok.duplicated(key_columns, keep=False)
    if duplicates.any():
        examples = ok.loc[duplicates, key_columns].head(10).to_dict("records")
        raise ValueError(f"Duplicate report-condition-run rows in {condition}: {examples}")

    for metric in metrics:
        source_column = metric_columns[metric]
        ok[metric] = pd.to_numeric(ok[source_column], errors="coerce")
        if ok[metric].isna().any():
            examples = ok.loc[ok[metric].isna(), ["round", "batch_id", "case_id"]]
            raise ValueError(
                f"{condition} has missing/non-numeric values in {source_column}: "
                f"{examples.head(10).to_dict('records')}"
            )

    audit = SourceAudit(
        condition=condition,
        path=str(resolved),
        sha256=sha256_file(resolved),
        metric_columns={metric: metric_columns[metric] for metric in metrics},
        total_rows=int(len(frame)),
        ok_rows=int(len(ok)),
        failed_rows=int(len(failed)),
        unique_reports_with_ok_rows=int(ok["report_id"].nunique()),
        unique_runs_with_ok_rows=int(ok["run"].nunique()),
    )
    return ok, audit, failed.fillna("").astype(str).to_dict("records")


def retain_complete_reports(
    long_data: pd.DataFrame,
    conditions: list[str],
    expected_runs: list[int],
    allow_incomplete: bool,
    expected_reports: int | None,
) -> tuple[pd.DataFrame, list[str], dict[str, object]]:
    expected_cells = {(condition, run) for condition in conditions for run in expected_runs}
    report_cells: dict[str, set[tuple[str, int]]] = {}
    for report_id, group in long_data.groupby("report_id", sort=True):
        report_cells[str(report_id)] = set(zip(group["condition"], group["run"]))

    complete = sorted(report_id for report_id, cells in report_cells.items() if cells == expected_cells)
    incomplete = sorted(report_id for report_id, cells in report_cells.items() if cells != expected_cells)
    if incomplete and not allow_incomplete:
        raise ValueError(
            f"Incomplete paired panel for {len(incomplete)} report(s): {incomplete[:10]}. "
            "Repair the source evaluation or pass --allow-incomplete for a preliminary plot."
        )
    if expected_reports is not None and len(complete) != expected_reports and not allow_incomplete:
        raise ValueError(
            f"Expected {expected_reports} complete reports, found {len(complete)}."
        )

    retained = long_data[long_data["report_id"].isin(complete)].copy()
    expected_rows = len(complete) * len(expected_cells)
    if len(retained) != expected_rows:
        raise AssertionError(f"Retained {len(retained)} rows; expected {expected_rows}.")

    details = {
        "conditions": conditions,
        "expected_runs": expected_runs,
        "expected_cells_per_report": len(expected_cells),
        "complete_report_count": len(complete),
        "incomplete_report_count": len(incomplete),
        "incomplete_report_ids": incomplete,
        "retained_row_count": len(retained),
    }
    return retained, incomplete, details


def fit_mixed_model(metric_data: pd.DataFrame):
    fit_data = metric_data[["value", "condition", "run", "report_id"]].dropna().copy()
    if fit_data.empty:
        raise ValueError("No finite metric observations remain for mixed-effects fitting.")
    fit_data["condition"] = pd.Categorical(fit_data["condition"])
    fit_data["run"] = pd.Categorical(fit_data["run"])
    model = smf.mixedlm(
        "value ~ C(condition) + C(run)",
        fit_data,
        groups=fit_data["report_id"],
        re_formula="1",
    )
    errors: list[str] = []
    # On these bounded similarity scores, statsmodels/L-BFGS can report
    # convergence at a singular random-effects boundary with llf=inf and a
    # zero intercept.  BFGS and Powell recover the finite interior solution.
    # Accept a fit only when convergence, likelihood, fixed effects, and the
    # random-intercept covariance are all finite.
    for method in ("bfgs", "powell", "lbfgs"):
        try:
            with warnings.catch_warnings(record=True) as caught_warnings:
                warnings.simplefilter("always")
                result = model.fit(reml=True, method=method, maxiter=2000, disp=False)
            finite_fit = (
                bool(result.converged)
                and math.isfinite(float(result.llf))
                and np.all(np.isfinite(result.fe_params.to_numpy(dtype=float)))
                and np.all(np.isfinite(result.cov_re.to_numpy(dtype=float)))
            )
            if finite_fit:
                return result, fit_data, method, errors
            warning_text = "; ".join(str(item.message) for item in caught_warnings)
            errors.append(
                f"{method}: rejected non-finite/singular fit "
                f"(converged={result.converged}, llf={result.llf}, "
                f"warnings={warning_text!r})"
            )
        except Exception as exc:  # pragma: no cover - fallback depends on data
            errors.append(f"{method}: {type(exc).__name__}: {exc}")
    raise RuntimeError(f"Mixed-effects fitting failed. Attempts: {errors}")


def marginal_design_vector(result, condition: str, runs: list[int]) -> np.ndarray:
    grid = pd.DataFrame({"condition": [condition] * len(runs), "run": runs})
    grid["condition"] = pd.Categorical(
        grid["condition"], categories=result.model.data.frame["condition"].cat.categories
    )
    grid["run"] = pd.Categorical(
        grid["run"], categories=result.model.data.frame["run"].cat.categories
    )
    design_info = getattr(result.model.data, "design_info", None)
    if design_info is None:
        design_info = getattr(result.model.data, "model_spec", None)
    if design_info is None:
        raise RuntimeError("The fitted model did not retain formula design metadata.")
    design = build_design_matrices([design_info], grid, return_type="dataframe")[0]
    return design[result.fe_params.index].to_numpy(dtype=float).mean(axis=0)


def bootstrap_dz(differences: np.ndarray, resamples: int, rng: np.random.Generator) -> tuple[float, float]:
    n = len(differences)
    if n < 2:
        return math.nan, math.nan
    values: list[np.ndarray] = []
    chunk_size = 1000
    for start in range(0, resamples, chunk_size):
        size = min(chunk_size, resamples - start)
        indices = rng.integers(0, n, size=(size, n))
        samples = differences[indices]
        sample_sd = samples.std(axis=1, ddof=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            chunk = samples.mean(axis=1) / sample_sd
        values.append(chunk[np.isfinite(chunk)])
    finite = np.concatenate(values) if values else np.array([], dtype=float)
    if finite.size == 0:
        return math.nan, math.nan
    lower, upper = np.quantile(finite, [0.025, 0.975])
    return float(lower), float(upper)


def analyze_metric(
    data: pd.DataFrame,
    metric: str,
    contrasts: list[tuple[str, str]],
    runs: list[int],
    bootstrap_resamples: int,
    rng: np.random.Generator,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    metric_data = data[["report_id", "condition", "run", metric]].rename(
        columns={metric: "value"}
    )
    result, fit_data, optimizer, fit_errors = fit_mixed_model(metric_data)
    fixed_cov = result.cov_params().loc[result.fe_params.index, result.fe_params.index]
    beta = result.fe_params.to_numpy(dtype=float)
    covariance = fixed_cov.to_numpy(dtype=float)
    report_means = fit_data.groupby(["report_id", "condition"], observed=True)["value"].mean().unstack()

    rows: list[dict[str, object]] = []
    for condition_a, condition_b in contrasts:
        vector_a = marginal_design_vector(result, condition_a, runs)
        vector_b = marginal_design_vector(result, condition_b, runs)
        contrast_vector = vector_a - vector_b
        estimate = float(contrast_vector @ beta)
        standard_error = float(np.sqrt(contrast_vector @ covariance @ contrast_vector))
        z_value = estimate / standard_error if standard_error > 0 else math.nan
        raw_p = float(2.0 * norm.sf(abs(z_value))) if math.isfinite(z_value) else math.nan
        difference_ci_lower = estimate - 1.959963984540054 * standard_error
        difference_ci_upper = estimate + 1.959963984540054 * standard_error

        paired_differences = (
            report_means[condition_a] - report_means[condition_b]
        ).dropna().to_numpy(dtype=float)
        difference_sd = float(np.std(paired_differences, ddof=1))
        cohens_dz = (
            float(np.mean(paired_differences) / difference_sd)
            if difference_sd > 0
            else math.nan
        )
        dz_ci_lower, dz_ci_upper = bootstrap_dz(
            paired_differences, bootstrap_resamples, rng
        )

        rows.append(
            {
                "metric": metric,
                "metric_label": METRIC_LABELS.get(metric, metric),
                "condition_a": condition_a,
                "condition_b": condition_b,
                "contrast": f"{condition_a} - {condition_b}",
                "contrast_label": (
                    f"{CONDITION_LABELS.get(condition_a, condition_a)} - "
                    f"{CONDITION_LABELS.get(condition_b, condition_b)}"
                ),
                "model_adjusted_difference": estimate,
                "difference_standard_error": standard_error,
                "difference_ci_lower": difference_ci_lower,
                "difference_ci_upper": difference_ci_upper,
                "z_value": z_value,
                "raw_p_value": raw_p,
                "cohens_dz": cohens_dz,
                "dz_ci_lower": dz_ci_lower,
                "dz_ci_upper": dz_ci_upper,
            }
        )

    model_audit = {
        "metric": metric,
        "formula": "value ~ C(condition) + C(run) + (1 | report_id)",
        "reml": True,
        "optimizer": optimizer,
        "fallback_errors": fit_errors,
        "converged": bool(result.converged),
        "observations": int(result.nobs),
        "reports": int(fit_data["report_id"].nunique()),
        "fixed_effects": {key: float(value) for key, value in result.fe_params.items()},
        "report_random_intercept_variance": float(result.cov_re.iloc[0, 0]),
        "residual_variance": float(result.scale),
    }
    return rows, model_audit


def apply_holm(rows: list[dict[str, object]]) -> None:
    valid_indices = [
        index for index, row in enumerate(rows) if math.isfinite(float(row["raw_p_value"]))
    ]
    raw_values = [float(rows[index]["raw_p_value"]) for index in valid_indices]
    if raw_values:
        rejected, adjusted, _, _ = multipletests(raw_values, alpha=0.05, method="holm")
        for index, adjusted_p, reject in zip(valid_indices, adjusted, rejected):
            rows[index]["holm_adjusted_p_value"] = float(adjusted_p)
            rows[index]["holm_reject_0_05"] = bool(reject)
    for index, row in enumerate(rows):
        if index not in valid_indices:
            row["holm_adjusted_p_value"] = math.nan
            row["holm_reject_0_05"] = False


def draw_mixed_effects_forest_plot(
    results: pd.DataFrame,
    output_dir: Path,
    preliminary: bool,
) -> None:
    """Draw mixed-effects contrasts in the stability-boxplot visual style."""
    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": ["Times New Roman", "DejaVu Serif"],
            "font.size": 12,
            "axes.labelsize": 12,
            "axes.titlesize": 12,
            "xtick.labelsize": 11,
            "ytick.labelsize": 10,
            "legend.fontsize": 10,
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

    metric_panels = (
        ("graph_edit_similarity", "GES"),
        ("structural_similarity", "WLS"),
    )
    contrast_order = [f"{a} - {b}" for a, b in PLANNED_CONTRASTS]
    fig, axes = plt.subplots(2, 2, figsize=(13.0, 8.4), sharey="row")
    estimate_specs = (
        (
            "model_adjusted_difference",
            "difference_ci_lower",
            "difference_ci_upper",
            "Adjusted paired difference",
        ),
        ("cohens_dz", "dz_ci_lower", "dz_ci_upper", "Cohen's $d_z$"),
    )

    panel_index = 0
    for row_index, (metric, metric_short_label) in enumerate(metric_panels):
        metric_rows = results.loc[results["metric"] == metric].copy()
        metric_rows["contrast_rank"] = metric_rows["contrast"].map(
            {value: index for index, value in enumerate(contrast_order)}
        )
        metric_rows = metric_rows.sort_values("contrast_rank").reset_index(drop=True)
        y = np.arange(len(metric_rows))[::-1]
        labels = metric_rows["contrast_label"].tolist()

        for col_index, (value_col, lower_col, upper_col, x_label) in enumerate(
            estimate_specs
        ):
            axis = axes[row_index, col_index]
            axis.grid(axis="x", color="#E6E6E6", linewidth=0.8, zorder=0)
            axis.spines["left"].set_linewidth(0.8)
            axis.spines["bottom"].set_linewidth(0.8)
            axis.tick_params(length=4, width=0.8)
            axis.axvline(
                0.0, color="#777777", linewidth=0.9, linestyle="--", zorder=1
            )

            for result_index, item in metric_rows.iterrows():
                value = float(item[value_col])
                low = float(item[lower_col])
                high = float(item[upper_col])
                color = CONDITION_COLORS.get(str(item["condition_a"]), "#555555")
                significant = bool(item["holm_reject_0_05"])
                axis.errorbar(
                    value,
                    y[result_index],
                    xerr=np.array([[value - low], [high - value]]),
                    fmt="D",
                    color=color,
                    markerfacecolor=color if significant else "white",
                    markeredgecolor="#333333" if significant else color,
                    markeredgewidth=0.9,
                    markersize=5.8,
                    linewidth=1.4,
                    capsize=2.8,
                    zorder=3,
                )

            axis.set_yticks(y)
            axis.set_yticklabels(labels)
            if col_index != 0:
                axis.tick_params(axis="y", labelleft=False)
            axis.set_xlabel(x_label)
            axis.set_title(
                f"({chr(ord('a') + panel_index)}) {metric_short_label}",
                loc="left",
                fontweight="bold",
            )
            panel_index += 1

    fig.text(
        0.5,
        0.018,
        "Diamonds show model estimates; error bars show 95% confidence intervals. "
        "Filled diamonds indicate Holm-adjusted p < 0.05.",
        ha="center",
        va="bottom",
        fontsize=10,
        color="#444444",
    )
    if preliminary:
        fig.text(
            0.5,
            0.985,
            "PRELIMINARY COMPLETE-CASE ANALYSIS",
            ha="center",
            va="top",
            fontsize=9,
            color="#D55E00",
            fontweight="bold",
        )
    fig.subplots_adjust(left=0.23, bottom=0.13, hspace=0.42, wspace=0.23)
    fig.savefig(output_dir / "fig_paired_mixed_effects.pdf")
    fig.savefig(output_dir / "fig_paired_mixed_effects.png", dpi=300)
    fig.savefig(output_dir / "fig_paired_mixed_effects.svg")
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fit per-report mixed-effects contrasts and draw a 2x2 forest plot."
    )
    parser.add_argument(
        "--condition",
        action="append",
        type=parse_condition_argument,
        default=None,
        metavar="NAME=CASE_SCORES.csv",
        help=(
            "Override a condition's case_scores.csv path using NAME=PATH. Repeat for "
            "all four conditions; otherwise the audited final inputs are used."
        ),
    )
    parser.add_argument(
        "--metric",
        action="append",
        dest="metrics",
        default=None,
        help="Metric column to analyse. Defaults to GES and WL similarity.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--bootstrap-resamples", type=int, default=10_000)
    parser.add_argument("--random-seed", type=int, default=20260828)
    parser.add_argument("--expected-reports", type=int, default=112)
    parser.add_argument(
        "--expected-runs",
        default="1,2,3,4,5",
        help="Comma-separated run numbers required for every report (default: 1,2,3,4,5).",
    )
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="Drop incomplete reports and mark outputs preliminary instead of failing.",
    )
    args = parser.parse_args()

    condition_paths = dict(args.condition) if args.condition else DEFAULT_CONDITION_PATHS.copy()
    required_conditions = {"single_pass", "no_revision", "revision", "revision_fs"}
    if set(condition_paths) != required_conditions:
        parser.error(f"Conditions must be exactly {sorted(required_conditions)}")
    metrics = args.metrics or ["graph_edit_similarity", "structural_similarity"]
    if args.bootstrap_resamples < 1000:
        parser.error("--bootstrap-resamples must be at least 1000")
    try:
        expected_runs = sorted({int(value.strip()) for value in args.expected_runs.split(",")})
    except ValueError:
        parser.error("--expected-runs must be a comma-separated list of integers")
    if not expected_runs:
        parser.error("--expected-runs must contain at least one run number")

    frames: list[pd.DataFrame] = []
    source_audits: list[SourceAudit] = []
    failed_rows: dict[str, list[dict[str, str]]] = {}
    for condition, path in condition_paths.items():
        frame, source_audit, failures = load_condition_csv(condition, path, metrics)
        frames.append(frame)
        source_audits.append(source_audit)
        failed_rows[condition] = failures

    long_wide = pd.concat(frames, ignore_index=True)
    observed_runs = sorted(long_wide["run"].unique().tolist())
    if observed_runs != expected_runs:
        raise ValueError(
            f"Expected runs {expected_runs}, but the inputs contain runs {observed_runs}."
        )
    retained, incomplete_reports, panel_audit = retain_complete_reports(
        long_wide,
        sorted(condition_paths),
        expected_runs,
        allow_incomplete=args.allow_incomplete,
        expected_reports=args.expected_reports,
    )

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    retained.to_csv(output_dir / "analysis_long_data.csv", index=False)

    rng = np.random.default_rng(args.random_seed)
    contrast_rows: list[dict[str, object]] = []
    model_audits: list[dict[str, object]] = []
    for metric in metrics:
        rows, model_audit = analyze_metric(
            retained,
            metric,
            list(PLANNED_CONTRASTS),
            expected_runs,
            args.bootstrap_resamples,
            rng,
        )
        contrast_rows.extend(rows)
        model_audits.append(model_audit)

    apply_holm(contrast_rows)
    results = pd.DataFrame(contrast_rows)
    results.to_csv(output_dir / "paired_mixed_effects_results.csv", index=False)

    preliminary = bool(incomplete_reports or any(failed_rows.values()))
    draw_mixed_effects_forest_plot(results, output_dir, preliminary=preliminary)

    audit = {
        "analysis": "paired mixed-effects contrasts with report-level effect sizes",
        "source_audits": [asdict(item) for item in source_audits],
        "source_failed_rows": failed_rows,
        "panel_audit": panel_audit,
        "metrics": metrics,
        "planned_contrasts": [f"{a} - {b}" for a, b in PLANNED_CONTRASTS],
        "mixed_effects_formula": "metric ~ condition + run + (1 | report_id)",
        "effect_size": "Cohen's dz from per-report condition means across runs",
        "effect_size_ci": f"percentile bootstrap with {args.bootstrap_resamples} report resamples",
        "multiplicity_control": "Holm correction across all metric-by-contrast primary tests",
        "figure_type": "two-by-two mixed-effects forest plot",
        "figure_left_column": "model-adjusted paired difference with 95% CI",
        "figure_right_column": "Cohen's dz with report-bootstrap 95% CI",
        "figure_marker_fill": "filled when Holm-adjusted p < 0.05",
        "random_seed": args.random_seed,
        "allow_incomplete": args.allow_incomplete,
        "preliminary": preliminary,
        "model_audits": model_audits,
    }
    (output_dir / "analysis_input_audit.json").write_text(
        json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"Complete reports: {panel_audit['complete_report_count']}")
    print(f"Retained rows: {panel_audit['retained_row_count']}")
    print(f"Primary tests: {len(results)}")
    print(f"Preliminary: {preliminary}")
    print(f"Saved outputs to: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
