from __future__ import annotations

import csv
import importlib.util
import json
import re
import sys
from datetime import datetime
from itertools import combinations
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Iterable, List, Tuple
from tqdm import tqdm

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STRUCTURE_EVAL_PATH = PROJECT_ROOT / "scripts" / "evaluation_structure_similarity.py"


def _load_structure_eval_module():
    spec = importlib.util.spec_from_file_location(
        "evaluation_structure_similarity",
        STRUCTURE_EVAL_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load evaluation module from {STRUCTURE_EVAL_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_STRUCTURE_EVAL_MODULE = _load_structure_eval_module()
build_directed_graph = _STRUCTURE_EVAL_MODULE.build_directed_graph
compute_graph_edit_metrics = _STRUCTURE_EVAL_MODULE.compute_graph_edit_metrics
compute_structural_similarity = _STRUCTURE_EVAL_MODULE.compute_structural_similarity
flatten_nodes = _STRUCTURE_EVAL_MODULE.flatten_nodes
read_edges = _STRUCTURE_EVAL_MODULE.read_edges

CASE_SCORE_COLUMNS = [
    "case_group",
    "round_a",
    "round_b",
    "graph_file",
    "node_count_a",
    "edge_count_a",
    "node_count_b",
    "edge_count_b",
    "wl_similarity",
    "graph_edit_distance",
    "normalized_graph_edit_distance",
    "graph_edit_similarity",
    "status",
    "warnings",
]

CASE_SUMMARY_COLUMNS = [
    "case_group",
    "pair_count",
    "mean_wl_similarity",
    "mean_graph_edit_distance",
    "mean_normalized_graph_edit_distance",
    "mean_graph_edit_similarity",
]

OVERALL_SUMMARY_COLUMNS = [
    "case_group_count",
    "pair_count",
    "overall_mean_wl_similarity",
    "overall_mean_graph_edit_distance",
    "overall_mean_normalized_graph_edit_distance",
    "overall_mean_graph_edit_similarity",
]


def make_run_output_dir(base_dir: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = base_dir / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def write_csv(path: Path, fieldnames: List[str], rows: Iterable[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def infer_round_index(path: Path) -> int | None:
    for part in path.parts:
        match = re.fullmatch(r"round_(\d+)", part.lower())
        if match:
            return int(match.group(1))
    return None


def normalize_case_group(graph_path: Path, round_dir: Path) -> str:
    relative_parts = list(graph_path.relative_to(round_dir).parts[:-1])
    if not relative_parts:
        return "root"
    relative_parts[0] = re.sub(
        r"_output_round_\d+$", "", relative_parts[0], flags=re.IGNORECASE
    )
    return "/".join(relative_parts)


def discover_round_graphs(
    stability_root: Path,
    graph_file: str,
) -> Dict[str, List[Tuple[int, Path]]]:
    grouped: Dict[str, List[Tuple[int, Path]]] = {}
    round_dirs = sorted(
        path
        for path in stability_root.iterdir()
        if path.is_dir() and re.fullmatch(r"round_\d+", path.name.lower())
    )
    for round_dir in round_dirs:
        round_index = infer_round_index(round_dir)
        if round_index is None:
            continue
        for graph_path in round_dir.rglob(graph_file):
            case_group = normalize_case_group(graph_path, round_dir)
            grouped.setdefault(case_group, []).append((round_index, graph_path))
    for paths in grouped.values():
        paths.sort(key=lambda item: item[0])
    return grouped


def count_round_dirs(stability_root: Path) -> int:
    return sum(
        1
        for path in stability_root.iterdir()
        if path.is_dir() and re.fullmatch(r"round_\d+", path.name.lower())
    )


def evaluate_pair(
    *,
    case_group: str,
    round_a: int,
    path_a: Path,
    round_b: int,
    path_b: Path,
    exact_ged: bool,
) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "case_group": case_group,
        "round_a": round_a,
        "round_b": round_b,
        "graph_file": path_a.name,
        "node_count_a": "",
        "edge_count_a": "",
        "node_count_b": "",
        "edge_count_b": "",
        "wl_similarity": "",
        "graph_edit_distance": "",
        "normalized_graph_edit_distance": "",
        "graph_edit_similarity": "",
        "status": "failed",
        "warnings": "",
    }
    try:
        data_a = load_json(path_a)
        data_b = load_json(path_b)
        nodes_a = flatten_nodes(data_a)
        nodes_b = flatten_nodes(data_b)
        edges_a = read_edges(data_a)
        edges_b = read_edges(data_b)
        graph_a, warnings_a = build_directed_graph(nodes_a, edges_a)
        graph_b, warnings_b = build_directed_graph(nodes_b, edges_b)
        wl_similarity = compute_structural_similarity(graph_a, graph_b)
        ged, norm_ged, ged_sim = compute_graph_edit_metrics(
            graph_a,
            graph_b,
            exact_ged=exact_ged,
        )
        row.update(
            {
                "node_count_a": graph_a.number_of_nodes(),
                "edge_count_a": graph_a.number_of_edges(),
                "node_count_b": graph_b.number_of_nodes(),
                "edge_count_b": graph_b.number_of_edges(),
                "wl_similarity": f"{wl_similarity:.6f}",
                "graph_edit_distance": f"{ged:.6f}",
                "normalized_graph_edit_distance": f"{norm_ged:.6f}",
                "graph_edit_similarity": f"{ged_sim:.6f}",
                "status": "ok",
                "warnings": " | ".join(warnings_a + warnings_b),
            }
        )
    except Exception as exc:
        row["warnings"] = str(exc)
    return row


def collect_case_rows(
    grouped: Dict[str, List[Tuple[int, Path]]],
    *,
    exact_ged: bool,
) -> List[Dict[str, Any]]:
    case_rows: List[Dict[str, Any]] = []
    total_pairs = sum(
        len(list(combinations(round_graphs, 2)))
        for round_graphs in grouped.values()
        if len(round_graphs) >= 2
    )
    progress = tqdm(total=total_pairs, desc="Comparing graph pairs", unit="pair")
    for case_group, round_graphs in sorted(grouped.items()):
        if len(round_graphs) < 2:
            continue
        for (round_a, path_a), (round_b, path_b) in combinations(round_graphs, 2):
            case_rows.append(
                evaluate_pair(
                    case_group=case_group,
                    round_a=round_a,
                    path_a=path_a,
                    round_b=round_b,
                    path_b=path_b,
                    exact_ged=exact_ged,
                )
            )
            progress.update(1)
            progress.set_postfix(case_group=case_group, rounds=f"{round_a}-{round_b}")
    progress.close()
    return case_rows


def summarize_case_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_case: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        if row.get("status") != "ok":
            continue
        by_case.setdefault(str(row["case_group"]), []).append(row)

    summaries: List[Dict[str, Any]] = []
    for case_group, case_rows in sorted(by_case.items()):
        summaries.append(
            {
                "case_group": case_group,
                "pair_count": len(case_rows),
                "mean_wl_similarity": f"{mean(float(row['wl_similarity']) for row in case_rows):.6f}",
                "mean_graph_edit_distance": f"{mean(float(row['graph_edit_distance']) for row in case_rows):.6f}",
                "mean_normalized_graph_edit_distance": f"{mean(float(row['normalized_graph_edit_distance']) for row in case_rows):.6f}",
                "mean_graph_edit_similarity": f"{mean(float(row['graph_edit_similarity']) for row in case_rows):.6f}",
            }
        )
    return summaries


def build_overall_summary(case_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    ok_rows = [row for row in case_rows if row.get("status") == "ok"]
    if not ok_rows:
        return {
            "case_group_count": 0,
            "pair_count": 0,
            "overall_mean_wl_similarity": "",
            "overall_mean_graph_edit_distance": "",
            "overall_mean_normalized_graph_edit_distance": "",
            "overall_mean_graph_edit_similarity": "",
        }
    return {
        "case_group_count": len({str(row["case_group"]) for row in ok_rows}),
        "pair_count": len(ok_rows),
        "overall_mean_wl_similarity": f"{mean(float(row['wl_similarity']) for row in ok_rows):.6f}",
        "overall_mean_graph_edit_distance": f"{mean(float(row['graph_edit_distance']) for row in ok_rows):.6f}",
        "overall_mean_normalized_graph_edit_distance": f"{mean(float(row['normalized_graph_edit_distance']) for row in ok_rows):.6f}",
        "overall_mean_graph_edit_similarity": f"{mean(float(row['graph_edit_similarity']) for row in ok_rows):.6f}",
    }


def run_stability_evaluation(
    *,
    stability_root: Path,
    graph_file: str,
    output_dir: Path | None = None,
    exact_ged: bool = True,
) -> Path:
    base_output_dir = output_dir or (stability_root / "stability_results")
    run_output_dir = make_run_output_dir(base_output_dir)
    round_count = count_round_dirs(stability_root)
    grouped = discover_round_graphs(stability_root, graph_file)
    comparable_case_count = sum(1 for paths in grouped.values() if len(paths) >= 2)
    print(f"Discovered {round_count} round folder(s) under {stability_root}.")
    print(f"Discovered {len(grouped)} case group(s), {comparable_case_count} with at least two rounds.")
    case_rows = collect_case_rows(grouped, exact_ged=exact_ged)
    case_summaries = summarize_case_rows(case_rows)
    overall_summary = build_overall_summary(case_rows)

    write_csv(run_output_dir / "case_stability_scores.csv", CASE_SCORE_COLUMNS, case_rows)
    write_csv(run_output_dir / "case_stability_summary.csv", CASE_SUMMARY_COLUMNS, case_summaries)
    write_csv(
        run_output_dir / "overall_stability_summary.csv",
        OVERALL_SUMMARY_COLUMNS,
        [overall_summary],
    )

    print(f"Compared {len(case_rows)} round pair(s) under {stability_root}.")
    print(f"Saved stability CSV files to {run_output_dir}.")
    return run_output_dir
