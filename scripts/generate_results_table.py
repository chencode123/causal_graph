"""Generate the audited five-run descriptive results table.

Each run-specific cell is the mean ± sample SD across the same 112 held-out
reports. Repeated runs are retained as separate descriptive columns. The
between-run CV is calculated from the five run-specific means. No report-run
row is treated as an independent report for inferential analysis.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASE = PROJECT_ROOT / "runs" / "stability_test" / "evaluation_final"

DEFAULT_STRUCTURAL_INPUTS = {
    "single_pass": BASE / "single_pass" / "20260828_141620" / "case_scores.csv",
    "no_revision": BASE / "no_revision" / "20260902_164902" / "case_scores.csv",
    "revision": BASE / "revision" / "20260829_170239" / "case_scores.csv",
    "few_shot": BASE / "few_shot" / "20260828_140052" / "case_scores.csv",
}
def latest_auxiliary_input() -> Path:
    candidates = sorted(
        (BASE / "auxiliary").glob("*/combined_auxiliary_case_scores.csv"),
        key=lambda path: path.parent.name,
        reverse=True,
    )
    return candidates[0] if candidates else (
        BASE / "auxiliary" / "combined_auxiliary_case_scores.csv"
    )


DEFAULT_AUXILIARY_INPUT = latest_auxiliary_input()
DEFAULT_OUTPUT_DIR = PROJECT_ROOT.parents[1] / "manuscript" / "llm_manuscript"
DEFAULT_OUTPUT_CSV = DEFAULT_OUTPUT_DIR / "results_table.csv"
DEFAULT_AUDIT_JSON = DEFAULT_OUTPUT_DIR / "results_table_audit.json"

EXPECTED_REPORTS = 112
EXPECTED_RUNS = 5

CONDITION_ORDER = (
    "Single Pass",
    "No Revision",
    "Revision",
    "Revision + FS",
)

METRIC_ORDER = (
    "WLS",
    "GES",
    "Node Precision",
    "Node Recall",
    "Node F1",
    "Edge Precision",
    "Edge Recall",
    "Edge F1",
    "Semantic Sim.",
)

AUXILIARY_METRICS = {
    "Node Precision": "soft_node_precision",
    "Node Recall": "soft_node_recall",
    "Node F1": "soft_node_f1",
    "Edge Precision": "soft_edge_precision",
    "Edge Recall": "soft_edge_recall",
    "Edge F1": "soft_edge_f1",
    "Semantic Sim.": "semantic_similarity",
}

STRUCTURAL_CONDITION_MAP = {
    "Single Pass": ("single_pass", "generated"),
    "No Revision": ("no_revision", "generated"),
    "Revision": ("revision", "revised"),
    "Revision + FS": ("few_shot", "revised"),
}

AUXILIARY_CONDITION_MAP = {
    "Single Pass": "single_pass",
    "No Revision": "no_revision",
    "Revision": "revision",
    "Revision + FS": "revision_fs",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate the final five-run descriptive results table."
    )
    parser.add_argument(
        "--single-pass-csv",
        type=Path,
        default=DEFAULT_STRUCTURAL_INPUTS["single_pass"],
    )
    parser.add_argument(
        "--no-revision-csv",
        type=Path,
        default=DEFAULT_STRUCTURAL_INPUTS["no_revision"],
    )
    parser.add_argument(
        "--revision-csv",
        type=Path,
        default=DEFAULT_STRUCTURAL_INPUTS["revision"],
    )
    parser.add_argument(
        "--few-shot-csv",
        type=Path,
        default=DEFAULT_STRUCTURAL_INPUTS["few_shot"],
    )
    parser.add_argument(
        "--auxiliary-csv",
        type=Path,
        default=DEFAULT_AUXILIARY_INPUT,
    )
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--audit-json", type=Path, default=DEFAULT_AUDIT_JSON)
    return parser.parse_args()


def normalize_report_id(batch_id: object, case_id: object) -> str:
    return f"{str(batch_id).strip()}/{str(case_id).strip()}".lower()


def expected_run_names(kind: str) -> tuple[str, ...]:
    if kind == "single_pass":
        return tuple(f"run_{index:02d}" for index in range(1, EXPECTED_RUNS + 1))
    return tuple(f"round_{index}" for index in range(1, EXPECTED_RUNS + 1))


def load_structural_input(
    path: Path,
    kind: str,
) -> tuple[pd.DataFrame, dict[str, object]]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    frame = pd.read_csv(path)
    required = {
        "round",
        "batch_id",
        "case_id",
        "status",
        "structural_similarity",
        "graph_edit_similarity",
        "structural_similarity_accept_all_vs_updated",
        "graph_edit_similarity_accept_all_vs_updated",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise RuntimeError(f"{path} is missing columns {missing}")

    successful = frame[frame["status"].astype(str).str.lower() == "ok"].copy()
    successful["report_id"] = successful.apply(
        lambda row: normalize_report_id(row["batch_id"], row["case_id"]), axis=1
    )
    successful["run"] = successful["round"].astype(str)
    expected_runs = set(expected_run_names(kind))
    reports = set(successful["report_id"])
    runs = set(successful["run"])
    report_counts = Counter(successful["report_id"])
    duplicate_count = int(successful.duplicated(subset=["report_id", "run"]).sum())
    problems: list[str] = []
    if len(frame) != EXPECTED_REPORTS * EXPECTED_RUNS:
        problems.append(f"expected 560 total rows, found {len(frame)}")
    if len(successful) != EXPECTED_REPORTS * EXPECTED_RUNS:
        problems.append(f"expected 560 successful rows, found {len(successful)}")
    if len(reports) != EXPECTED_REPORTS:
        problems.append(f"expected 112 reports, found {len(reports)}")
    if runs != expected_runs:
        problems.append(f"expected runs {sorted(expected_runs)}, found {sorted(runs)}")
    if report_counts and set(report_counts.values()) != {EXPECTED_RUNS}:
        problems.append("reports do not all have five observations")
    if duplicate_count:
        problems.append(f"found {duplicate_count} duplicate report-run rows")
    if problems:
        raise RuntimeError(f"Structural input audit failed for {path}: " + "; ".join(problems))

    return successful, {
        "path": str(path),
        "total_rows": int(len(frame)),
        "successful_rows": int(len(successful)),
        "independent_reports": int(len(reports)),
        "runs": sorted(runs),
        "complete": True,
    }


def load_auxiliary_input(
    path: Path,
) -> tuple[pd.DataFrame, dict[str, object]]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    frame = pd.read_csv(path)
    required = {
        "condition",
        "run",
        "report_id",
        "status",
        *AUXILIARY_METRICS.values(),
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise RuntimeError(f"{path} is missing columns {missing}")
    successful = frame[frame["status"].astype(str).str.lower() == "ok"].copy()
    successful["report_id"] = successful["report_id"].astype(str).str.lower()
    problems: list[str] = []
    condition_audits: dict[str, object] = {}
    if len(frame) != len(CONDITION_ORDER) * EXPECTED_REPORTS * EXPECTED_RUNS:
        problems.append(f"expected 2240 total rows, found {len(frame)}")
    if len(successful) != len(frame):
        problems.append(f"expected all rows successful, found {len(successful)}")

    for display_condition, source_condition in AUXILIARY_CONDITION_MAP.items():
        selected = successful[successful["condition"] == source_condition]
        expected_runs = set(
            expected_run_names("single_pass" if source_condition == "single_pass" else "main")
        )
        reports = set(selected["report_id"])
        runs = set(selected["run"].astype(str))
        report_counts = Counter(selected["report_id"])
        duplicates = int(selected.duplicated(subset=["report_id", "run"]).sum())
        local: list[str] = []
        if len(selected) != EXPECTED_REPORTS * EXPECTED_RUNS:
            local.append(f"expected 560 rows, found {len(selected)}")
        if len(reports) != EXPECTED_REPORTS:
            local.append(f"expected 112 reports, found {len(reports)}")
        if runs != expected_runs:
            local.append(f"expected runs {sorted(expected_runs)}, found {sorted(runs)}")
        if report_counts and set(report_counts.values()) != {EXPECTED_RUNS}:
            local.append("reports do not all have five observations")
        if duplicates:
            local.append(f"found {duplicates} duplicate report-run rows")
        for column in AUXILIARY_METRICS.values():
            if selected[column].isna().any():
                local.append(f"missing values in {column}")
        if local:
            problems.extend(f"{display_condition}: {problem}" for problem in local)
        condition_audits[display_condition] = {
            "source_condition": source_condition,
            "rows": int(len(selected)),
            "independent_reports": int(len(reports)),
            "runs": sorted(runs),
            "complete": not local,
        }

    if problems:
        raise RuntimeError("Auxiliary input audit failed: " + "; ".join(problems))
    return successful, {
        "path": str(path),
        "total_rows": int(len(frame)),
        "successful_rows": int(len(successful)),
        "conditions": condition_audits,
        "complete": True,
    }


def audit_paired_report_sets(
    structural: dict[str, pd.DataFrame],
    auxiliary: pd.DataFrame,
) -> list[str]:
    report_sets = {
        f"structural_{name}": set(frame["report_id"])
        for name, frame in structural.items()
    }
    for display_condition, source_condition in AUXILIARY_CONDITION_MAP.items():
        report_sets[f"auxiliary_{display_condition}"] = set(
            auxiliary.loc[auxiliary["condition"] == source_condition, "report_id"]
        )
    reference = report_sets["structural_no_revision"]
    mismatches = [name for name, values in report_sets.items() if values != reference]
    if mismatches:
        raise RuntimeError(f"Paired report sets differ for {mismatches}")
    return sorted(reference)


def summarize_runs(
    frame: pd.DataFrame,
    value_column: str,
    runs: tuple[str, ...],
) -> dict[str, object]:
    run_stats: dict[str, dict[str, float | int]] = {}
    run_means: list[float] = []
    for run in runs:
        values = pd.to_numeric(
            frame.loc[frame["run"] == run, value_column], errors="raise"
        ).to_numpy(dtype=float)
        if len(values) != EXPECTED_REPORTS:
            raise RuntimeError(
                f"Expected 112 values for {value_column} in {run}, found {len(values)}"
            )
        mean = float(np.mean(values))
        sd = float(np.std(values, ddof=1))
        run_stats[run] = {"mean": mean, "sd": sd, "n": int(len(values))}
        run_means.append(mean)
    overall_mean = float(np.mean(run_means))
    between_run_sd = float(np.std(run_means, ddof=1))
    between_run_cv = (
        between_run_sd / overall_mean * 100.0 if overall_mean else float("nan")
    )
    return {
        "runs": run_stats,
        "overall_mean": overall_mean,
        "between_run_sd": between_run_sd,
        "between_run_cv_percent": between_run_cv,
    }


def format_mean_sd(stat: dict[str, float | int]) -> str:
    return f"{float(stat['mean']):.3f}±{float(stat['sd']):.3f}"


def main() -> int:
    args = parse_args()
    structural_paths = {
        "single_pass": args.single_pass_csv,
        "no_revision": args.no_revision_csv,
        "revision": args.revision_csv,
        "few_shot": args.few_shot_csv,
    }
    structural: dict[str, pd.DataFrame] = {}
    structural_audits: dict[str, object] = {}
    for name, path in structural_paths.items():
        frame, audit = load_structural_input(path, name)
        structural[name] = frame
        structural_audits[name] = audit
    auxiliary, auxiliary_audit = load_auxiliary_input(args.auxiliary_csv)
    paired_reports = audit_paired_report_sets(structural, auxiliary)

    table_data: dict[str, dict[str, dict[str, object]]] = {
        metric: {} for metric in METRIC_ORDER
    }
    for condition in CONDITION_ORDER:
        structural_source, variant = STRUCTURAL_CONDITION_MAP[condition]
        structural_frame = structural[structural_source]
        structural_runs = expected_run_names(structural_source)
        wl_column = (
            "structural_similarity"
            if variant == "generated"
            else "structural_similarity_accept_all_vs_updated"
        )
        ges_column = (
            "graph_edit_similarity"
            if variant == "generated"
            else "graph_edit_similarity_accept_all_vs_updated"
        )
        table_data["WLS"][condition] = summarize_runs(
            structural_frame, wl_column, structural_runs
        )
        table_data["GES"][condition] = summarize_runs(
            structural_frame, ges_column, structural_runs
        )

        auxiliary_condition = AUXILIARY_CONDITION_MAP[condition]
        auxiliary_frame = auxiliary[auxiliary["condition"] == auxiliary_condition]
        auxiliary_runs = expected_run_names(
            "single_pass" if auxiliary_condition == "single_pass" else "main"
        )
        for metric, column in AUXILIARY_METRICS.items():
            table_data[metric][condition] = summarize_runs(
                auxiliary_frame, column, auxiliary_runs
            )

    output_csv = args.output_csv.resolve()
    audit_json = args.audit_json.resolve()
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    audit_json.parent.mkdir(parents=True, exist_ok=True)
    header = [
        "Metric",
        "Condition",
        "Run 1",
        "Run 2",
        "Run 3",
        "Run 4",
        "Run 5",
        "Overall mean",
        "Between-run CV (%)",
        "Reports per run",
    ]
    with output_csv.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for metric in METRIC_ORDER:
            for condition in CONDITION_ORDER:
                summary = table_data[metric][condition]
                runs = expected_run_names(
                    "single_pass" if condition == "Single Pass" else "main"
                )
                writer.writerow(
                    [
                        metric,
                        condition,
                        *[format_mean_sd(summary["runs"][run]) for run in runs],
                        f"{float(summary['overall_mean']):.3f}",
                        f"{float(summary['between_run_cv_percent']):.2f}%",
                        EXPECTED_REPORTS,
                    ]
                )

    audit = {
        "analysis_type": "descriptive repeated-run summary",
        "independent_unit": "report",
        "independent_reports": EXPECTED_REPORTS,
        "runs_per_condition": EXPECTED_RUNS,
        "report_run_rows_per_condition": EXPECTED_REPORTS * EXPECTED_RUNS,
        "conditions": list(CONDITION_ORDER),
        "metrics": list(METRIC_ORDER),
        "run_cell_definition": "mean ± sample SD across 112 reports",
        "overall_mean_definition": "mean of five run-specific means",
        "between_run_cv_definition": (
            "sample SD of five run-specific means divided by their mean, multiplied by 100"
        ),
        "inferential_use": (
            "none; paired and mixed-effects analyses are required for condition contrasts"
        ),
        "paired_report_sets_identical": True,
        "paired_report_ids": paired_reports,
        "structural_inputs": structural_audits,
        "auxiliary_input": auxiliary_audit,
        "output_csv": str(output_csv),
        "table_values": table_data,
    }
    audit_json.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"CSV saved: {output_csv}")
    print(f"Audit saved: {audit_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
