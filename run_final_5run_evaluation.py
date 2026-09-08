from __future__ import annotations

"""Run and audit the final five-run structural evaluation for all conditions."""

import csv
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
REFERENCE_ROOT = PROJECT_ROOT / "runs/stability_test/rounds/round_1"
EXCLUSION_PATH = PROJECT_ROOT / "evaluation_excluded_few_shot_cases.json"
OUTPUT_ROOT = PROJECT_ROOT / "runs/stability_test/final_5run_evaluation"
EXPECTED_REPORTS = 124
EXPECTED_EXCLUSIONS = 12
EXPECTED_HELD_OUT_REPORTS = 112
EXPECTED_RUNS = 5
MAIN_STEP_OUTPUTS = (
    "causal_narrative_extraction_output.json",
    "scenario_candidate_extraction_output.json",
    "scenario_structure_validation_output.json",
    "identify_accident_scenario_output.json",
    "edge_candidate_extraction_output.json",
    "edge_structure_validation_output.json",
    "causal_edge_linking_output.json",
    "graph_diagnosis_output.json",
    "graph_revision_planning_output.json",
)

DATASETS = (
    {
        "name": "no_revision",
        "root": PROJECT_ROOT / "runs/stability_test/no_revision",
        "run_labels": tuple(f"round_{index}" for index in range(1, 6)),
        "prediction_file": "no_revision_causal_graph.json",
        "require_accept_all": False,
        "held_out_only": True,
    },
    {
        "name": "revision",
        "root": PROJECT_ROOT / "runs/stability_test/rounds",
        "run_labels": tuple(f"round_{index}" for index in range(1, 6)),
        "prediction_file": "causal_graph.json",
        "require_accept_all": True,
        "held_out_only": False,
    },
    {
        "name": "revision_fs",
        "root": PROJECT_ROOT / "runs/stability_test/rounds_with_few_shot",
        "run_labels": tuple(f"round_{index}" for index in range(1, 6)),
        "prediction_file": "causal_graph.json",
        "require_accept_all": True,
        "held_out_only": False,
    },
    {
        "name": "single_pass",
        "root": PROJECT_ROOT / "runs/stability_test/single_pass_baseline_all_batches",
        "run_labels": tuple(f"run_{index:02d}" for index in range(1, 6)),
        "prediction_file": "causal_graph.json",
        "require_accept_all": False,
        "held_out_only": False,
    },
)


def case_key(case_dir: Path) -> str:
    return f"{case_dir.parent.name.lower()}/{case_dir.name.lower()}"


def discover_run_cases(run_dir: Path, prediction_file: str) -> dict[str, Path]:
    return {
        case_key(graph.parent): graph.parent
        for graph in run_dir.glob(f"batch_*/*/{prediction_file}")
    }


def preflight() -> None:
    payload = json.loads(EXCLUSION_PATH.read_text(encoding="utf-8"))
    exclusions = {str(value).lower() for value in payload["excluded_cases"]}
    if len(exclusions) != EXPECTED_EXCLUSIONS:
        raise RuntimeError(
            f"Expected {EXPECTED_EXCLUSIONS} exclusions, found {len(exclusions)}."
        )

    reference_keys = {
        case_key(path.parent)
        for path in REFERENCE_ROOT.glob("batch_*/*/updated_causal_graph.json")
    }
    if len(reference_keys) != EXPECTED_REPORTS:
        raise RuntimeError(
            f"Expected {EXPECTED_REPORTS} reference reports, found {len(reference_keys)}."
        )
    if not exclusions <= reference_keys:
        raise RuntimeError(f"Exclusions absent from reference set: {sorted(exclusions-reference_keys)}")
    held_out_keys = reference_keys - exclusions

    problems: list[str] = []
    for dataset in DATASETS:
        for run_label in dataset["run_labels"]:
            run_dir = dataset["root"] / run_label
            cases = (
                discover_run_cases(run_dir, str(dataset["prediction_file"]))
                if run_dir.is_dir()
                else {}
            )
            expected_keys = held_out_keys if dataset["held_out_only"] else reference_keys
            if set(cases) != expected_keys:
                missing = sorted(expected_keys - set(cases))
                extra = sorted(set(cases) - expected_keys)
                problems.append(
                    f"{dataset['name']}/{run_label}: reports={len(cases)}, "
                    f"missing={missing}, extra={extra}"
                )
                continue
            if dataset["require_accept_all"]:
                incomplete_steps = sorted(
                    key
                    for key, folder in cases.items()
                    if any(not (folder / name).is_file() for name in MAIN_STEP_OUTPUTS)
                )
                if incomplete_steps:
                    problems.append(
                        f"{dataset['name']}/{run_label}: incomplete pipeline outputs for "
                        f"{incomplete_steps}"
                    )
                missing_accept_all = sorted(
                    key
                    for key, folder in cases.items()
                    if not (folder / "updated_causal_graph_accept_all.json").is_file()
                )
                if missing_accept_all:
                    problems.append(
                        f"{dataset['name']}/{run_label}: missing accept-all for "
                        f"{missing_accept_all}"
                    )
    if problems:
        raise RuntimeError("Five-run evaluation preflight failed:\n- " + "\n- ".join(problems))


def newest_result_dir(base: Path) -> Path:
    candidates = sorted(
        (path for path in base.iterdir() if path.is_dir()),
        key=lambda path: path.name,
        reverse=True,
    )
    if not candidates:
        raise RuntimeError(f"No result directory created under {base}")
    return candidates[0]


def run_dataset(dataset: dict[str, object], session_root: Path) -> Path:
    output_base = session_root / "individual" / str(dataset["name"])
    command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts/evaluation_structure_similarity.py"),
        "--parent-dir",
        str(dataset["root"]),
        "--output-dir",
        str(output_base),
        "--reference-root",
        str(REFERENCE_ROOT),
        "--generated-graph-name",
        str(dataset["prediction_file"]),
        "--exclude-case-list",
        str(EXCLUSION_PATH),
        "--run-labels",
        *dataset["run_labels"],
        "--workers",
        "8",
        "--ged-algorithm",
        "bipartite",
        "--compute-ged-operation-counts",
        "--show-progress",
    ]
    print(f"\n=== Evaluating {dataset['name']} ===", flush=True)
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)
    return newest_result_dir(output_base)


def normalize_report_id(row: dict[str, str]) -> str:
    batch_id = re.sub(r"_output_round_\d+$", "", row["batch_id"], flags=re.I)
    return f"{batch_id.lower()}/{row['case_id'].lower()}"


def append_condition_rows(
    combined: list[dict[str, str]],
    source_csv: Path,
    mappings: tuple[tuple[str, str, str], ...],
) -> None:
    with source_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for condition, wl_column, ges_column in mappings:
        for row in rows:
            combined.append(
                {
                    "condition": condition,
                    "run": row["round"],
                    "report_id": normalize_report_id(row),
                    "structural_similarity": row[wl_column],
                    "graph_edit_similarity": row[ges_column],
                    "source_case_scores": str(source_csv),
                }
            )


def audit_combined(rows: list[dict[str, str]]) -> dict[str, object]:
    audit: dict[str, object] = {}
    for condition in sorted({row["condition"] for row in rows}):
        selected = [row for row in rows if row["condition"] == condition]
        report_counts = Counter(row["report_id"] for row in selected)
        if len(selected) != EXPECTED_HELD_OUT_REPORTS * EXPECTED_RUNS:
            raise RuntimeError(f"{condition}: expected 560 rows, found {len(selected)}")
        if len(report_counts) != EXPECTED_HELD_OUT_REPORTS:
            raise RuntimeError(
                f"{condition}: expected 112 reports, found {len(report_counts)}"
            )
        if set(report_counts.values()) != {EXPECTED_RUNS}:
            raise RuntimeError(f"{condition}: run counts are not exactly five per report")
        audit[condition] = {
            "report_run_observations": len(selected),
            "independent_reports": len(report_counts),
            "runs_per_report": EXPECTED_RUNS,
        }
    return audit


def main() -> None:
    preflight()
    session_root = OUTPUT_ROOT / datetime.now().strftime("%Y%m%d_%H%M%S")
    session_root.mkdir(parents=True, exist_ok=False)
    result_dirs = {
        str(dataset["name"]): run_dataset(dataset, session_root)
        for dataset in DATASETS
    }

    combined: list[dict[str, str]] = []
    append_condition_rows(
        combined,
        result_dirs["no_revision"] / "case_scores.csv",
        (("no_revision", "structural_similarity", "graph_edit_similarity"),),
    )
    append_condition_rows(
        combined,
        result_dirs["revision"] / "case_scores.csv",
        ((
            "revision",
            "structural_similarity_accept_all_vs_updated",
            "graph_edit_similarity_accept_all_vs_updated",
        ),),
    )
    append_condition_rows(
        combined,
        result_dirs["revision_fs"] / "case_scores.csv",
        ((
            "revision_fs",
            "structural_similarity_accept_all_vs_updated",
            "graph_edit_similarity_accept_all_vs_updated",
        ),),
    )
    append_condition_rows(
        combined,
        result_dirs["single_pass"] / "case_scores.csv",
        (("single_pass", "structural_similarity", "graph_edit_similarity"),),
    )

    audit = audit_combined(combined)
    csv_path = session_root / "combined_case_scores.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=combined[0].keys())
        writer.writeheader()
        writer.writerows(combined)
    audit_path = session_root / "combined_evaluation_audit.json"
    audit_path.write_text(
        json.dumps(
            {
                "eligible_reports": EXPECTED_REPORTS,
                "excluded_development_reports": EXPECTED_EXCLUSIONS,
                "held_out_reports": EXPECTED_HELD_OUT_REPORTS,
                "runs_per_condition": EXPECTED_RUNS,
                "conditions": audit,
                "individual_result_dirs": {
                    key: str(value) for key, value in result_dirs.items()
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nCombined scores: {csv_path}")
    print(f"Audit: {audit_path}")


if __name__ == "__main__":
    main()
