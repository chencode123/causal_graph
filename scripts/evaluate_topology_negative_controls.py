from __future__ import annotations

"""Evaluate GES/WL sensitivity using topology-destructive negative controls."""

import argparse
import csv
import hashlib
import json
import math
import random
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from statistics import mean, stdev
from typing import Any, Iterable

import networkx as nx
from scipy import stats
from tqdm import tqdm


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.evaluation_structure_similarity import (  # noqa: E402
    GED_ALGORITHM_BIPARTITE,
    GED_BIPARTITE_METHOD_ID,
    build_directed_graph,
    compute_graph_edit_metrics,
    compute_structural_similarity,
    flatten_nodes,
    load_json,
    read_edges,
)
from utils.evaluation_case_filters import (  # noqa: E402
    DEFAULT_EXCLUDED_CASES_PATH,
    load_excluded_case_keys,
    normalize_case_key,
)


CONTROL_NAMES = (
    "node_deletion",
    "edge_deletion",
    "edge_direction_reversal",
    "edge_endpoint_rewiring",
    "combined",
)
DEFAULT_SEVERITIES = (0.25, 0.50, 0.75)
REPLICATE_COLUMNS = (
    "report_id",
    "batch_id",
    "case_id",
    "control",
    "severity",
    "replicate",
    "seed",
    "reference_node_count",
    "reference_edge_count",
    "perturbed_node_count",
    "perturbed_edge_count",
    "nodes_deleted",
    "edges_deleted",
    "edges_reversed",
    "edges_rewired",
    "actual_node_fraction",
    "actual_edge_fraction",
    "wl_similarity",
    "graph_edit_distance",
    "normalized_graph_edit_distance",
    "graph_edit_similarity",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate topology-only negative controls from held-out reference graphs "
            "and evaluate them with the frozen WL and bipartite GES implementations."
        )
    )
    parser.add_argument(
        "--reference-root",
        type=Path,
        default=Path("runs/stability_test/rounds/round_1"),
        help="Reference root containing <batch>/<case>/updated_causal_graph.json.",
    )
    parser.add_argument(
        "--excluded-cases",
        type=Path,
        default=DEFAULT_EXCLUDED_CASES_PATH,
        help="Fixed few-shot development-case exclusion JSON.",
    )
    parser.add_argument(
        "--include-excluded",
        action="store_true",
        help="Disable the held-out exclusion filter (not for the primary analysis).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory. Defaults to a timestamped topology-control directory.",
    )
    parser.add_argument("--replicates", type=int, default=100)
    parser.add_argument(
        "--severities",
        type=float,
        nargs="+",
        default=list(DEFAULT_SEVERITIES),
    )
    parser.add_argument(
        "--controls",
        nargs="+",
        choices=CONTROL_NAMES,
        default=list(CONTROL_NAMES),
    )
    parser.add_argument("--seed", type=int, default=20260828)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--expected-reports",
        type=int,
        default=112,
        help="Fail unless this many held-out reference reports are discovered.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Development-only limit applied after sorting; adjust --expected-reports too.",
    )
    parser.add_argument(
        "--overwrite-shards",
        action="store_true",
        help="Recompute report shards that already exist in the output directory.",
    )
    return parser.parse_args()


def _target_count(total: int, fraction: float) -> int:
    if total <= 0 or fraction <= 0:
        return 0
    return min(total, max(1, int(round(total * fraction))))


def _hazard_nodes(graph: nx.DiGraph) -> set[str]:
    return {
        str(node)
        for node, attributes in graph.nodes(data=True)
        if str(node) == "H1"
        or str(attributes.get("node_type") or "").strip().lower()
        == "hazardconsequence"
    }


def delete_nodes(
    graph: nx.DiGraph,
    fraction: float,
    rng: random.Random,
) -> tuple[nx.DiGraph, dict[str, int]]:
    perturbed = graph.copy()
    eligible = sorted(str(node) for node in graph.nodes() if str(node) not in _hazard_nodes(graph))
    count = _target_count(len(eligible), fraction)
    selected = rng.sample(eligible, count) if count else []
    before_edges = perturbed.number_of_edges()
    perturbed.remove_nodes_from(selected)
    return perturbed, {
        "nodes_deleted": len(selected),
        "edges_deleted": before_edges - perturbed.number_of_edges(),
        "edges_reversed": 0,
        "edges_rewired": 0,
    }


def delete_edges(
    graph: nx.DiGraph,
    fraction: float,
    rng: random.Random,
) -> tuple[nx.DiGraph, dict[str, int]]:
    perturbed = graph.copy()
    edges = sorted((str(source), str(target)) for source, target in graph.edges())
    count = _target_count(len(edges), fraction)
    selected = rng.sample(edges, count) if count else []
    perturbed.remove_edges_from(selected)
    return perturbed, {
        "nodes_deleted": 0,
        "edges_deleted": len(selected),
        "edges_reversed": 0,
        "edges_rewired": 0,
    }


def reverse_edge_directions(
    graph: nx.DiGraph,
    fraction: float,
    rng: random.Random,
) -> tuple[nx.DiGraph, dict[str, int]]:
    """Reverse sampled directed edges without creating duplicates or self-loops."""
    perturbed = graph.copy()
    candidates = sorted(
        (str(source), str(target))
        for source, target in graph.edges()
        if source != target and not graph.has_edge(target, source)
    )
    requested = _target_count(graph.number_of_edges(), fraction)
    count = min(requested, len(candidates))
    selected = rng.sample(candidates, count) if count else []
    saved = [(source, target, dict(perturbed.edges[source, target])) for source, target in selected]
    perturbed.remove_edges_from((source, target) for source, target, _ in saved)
    for source, target, attributes in saved:
        perturbed.add_edge(target, source, **attributes)
    return perturbed, {
        "nodes_deleted": 0,
        "edges_deleted": 0,
        "edges_reversed": len(saved),
        "edges_rewired": 0,
    }


def rewire_edge_endpoints(
    graph: nx.DiGraph,
    fraction: float,
    rng: random.Random,
) -> tuple[nx.DiGraph, dict[str, int]]:
    """Apply directed double-edge swaps while preserving in/out degree exactly."""
    perturbed = graph.copy()
    target_edges = _target_count(graph.number_of_edges(), fraction)
    target_swaps = int(math.ceil(target_edges / 2.0))
    successful_swaps = 0
    attempts = 0
    max_attempts = max(100, target_swaps * 100)
    # Only untouched original edges remain eligible. Newly created edges are
    # deliberately excluded so that later swaps cannot undo earlier swaps and
    # silently return the randomized graph to its original edge set.
    available_edges = set(perturbed.edges())

    while successful_swaps < target_swaps and attempts < max_attempts:
        attempts += 1
        if len(available_edges) < 2:
            break
        (a, b), (c, d) = rng.sample(sorted(available_edges), 2)
        # A->B, C->D becomes A->D, C->B. This preserves every node's
        # in-degree and out-degree while disrupting adjacency.
        if a == d or c == b:
            continue
        if (a, d) == (c, b):
            continue
        if perturbed.has_edge(a, d) or perturbed.has_edge(c, b):
            continue
        first_attributes = dict(perturbed.edges[a, b])
        second_attributes = dict(perturbed.edges[c, d])
        perturbed.remove_edge(a, b)
        perturbed.remove_edge(c, d)
        perturbed.add_edge(a, d, **first_attributes)
        perturbed.add_edge(c, b, **second_attributes)
        available_edges.remove((a, b))
        available_edges.remove((c, d))
        successful_swaps += 1

    return perturbed, {
        "nodes_deleted": 0,
        "edges_deleted": 0,
        "edges_reversed": 0,
        "edges_rewired": successful_swaps * 2,
    }


def combined_perturbation(
    graph: nx.DiGraph,
    fraction: float,
    rng: random.Random,
) -> tuple[nx.DiGraph, dict[str, int]]:
    current, node_changes = delete_nodes(graph, fraction, rng)
    current, direction_changes = reverse_edge_directions(current, fraction, rng)
    current, rewire_changes = rewire_edge_endpoints(current, fraction, rng)
    return current, {
        "nodes_deleted": node_changes["nodes_deleted"],
        "edges_deleted": node_changes["edges_deleted"],
        "edges_reversed": direction_changes["edges_reversed"],
        "edges_rewired": rewire_changes["edges_rewired"],
    }


def perturb_graph(
    graph: nx.DiGraph,
    control: str,
    fraction: float,
    rng: random.Random,
) -> tuple[nx.DiGraph, dict[str, int]]:
    if control == "node_deletion":
        return delete_nodes(graph, fraction, rng)
    if control == "edge_deletion":
        return delete_edges(graph, fraction, rng)
    if control == "edge_direction_reversal":
        return reverse_edge_directions(graph, fraction, rng)
    if control == "edge_endpoint_rewiring":
        return rewire_edge_endpoints(graph, fraction, rng)
    if control == "combined":
        return combined_perturbation(graph, fraction, rng)
    raise ValueError(f"Unknown control: {control}")


def stable_seed(base_seed: int, report_id: str, control: str, severity: float, replicate: int) -> int:
    material = f"{base_seed}|{report_id}|{control}|{severity:.8f}|{replicate}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


def evaluate_graph_pair(perturbed: nx.DiGraph, reference: nx.DiGraph) -> dict[str, float]:
    wl = compute_structural_similarity(perturbed, reference)
    ged, normalized_ged, ges = compute_graph_edit_metrics(
        perturbed,
        reference,
        ged_algorithm=GED_ALGORITHM_BIPARTITE,
    )
    return {
        "wl_similarity": wl,
        "graph_edit_distance": ged,
        "normalized_graph_edit_distance": normalized_ged,
        "graph_edit_similarity": ges,
    }


def _actual_edge_fraction(changes: dict[str, int], reference_edges: int) -> float:
    if reference_edges <= 0:
        return 0.0
    changed = (
        changes["edges_deleted"]
        + changes["edges_reversed"]
        + changes["edges_rewired"]
    )
    return min(1.0, changed / reference_edges)


def evaluate_report(
    reference_path_text: str,
    report_id: str,
    controls: tuple[str, ...],
    severities: tuple[float, ...],
    replicates: int,
    base_seed: int,
) -> list[dict[str, Any]]:
    reference_path = Path(reference_path_text)
    payload = load_json(reference_path)
    reference, warnings = build_directed_graph(flatten_nodes(payload), read_edges(payload))
    if warnings:
        raise ValueError(f"{report_id}: invalid reference graph: {'; '.join(warnings)}")
    batch_id, case_id = report_id.split("/", 1)
    reference_nodes = reference.number_of_nodes()
    reference_edges = reference.number_of_edges()
    positive_metrics = evaluate_graph_pair(reference, reference)
    rows: list[dict[str, Any]] = [
        {
            "report_id": report_id,
            "batch_id": batch_id,
            "case_id": case_id,
            "control": "positive_control",
            "severity": 0.0,
            "replicate": 0,
            "seed": base_seed,
            "reference_node_count": reference_nodes,
            "reference_edge_count": reference_edges,
            "perturbed_node_count": reference_nodes,
            "perturbed_edge_count": reference_edges,
            "nodes_deleted": 0,
            "edges_deleted": 0,
            "edges_reversed": 0,
            "edges_rewired": 0,
            "actual_node_fraction": 0.0,
            "actual_edge_fraction": 0.0,
            **positive_metrics,
        }
    ]

    for control in controls:
        for severity in severities:
            for replicate in range(1, replicates + 1):
                seed = stable_seed(base_seed, report_id, control, severity, replicate)
                perturbed, changes = perturb_graph(
                    reference,
                    control,
                    severity,
                    random.Random(seed),
                )
                metrics = evaluate_graph_pair(perturbed, reference)
                eligible_nodes = max(0, reference_nodes - len(_hazard_nodes(reference)))
                rows.append(
                    {
                        "report_id": report_id,
                        "batch_id": batch_id,
                        "case_id": case_id,
                        "control": control,
                        "severity": severity,
                        "replicate": replicate,
                        "seed": seed,
                        "reference_node_count": reference_nodes,
                        "reference_edge_count": reference_edges,
                        "perturbed_node_count": perturbed.number_of_nodes(),
                        "perturbed_edge_count": perturbed.number_of_edges(),
                        **changes,
                        "actual_node_fraction": (
                            changes["nodes_deleted"] / eligible_nodes if eligible_nodes else 0.0
                        ),
                        "actual_edge_fraction": _actual_edge_fraction(changes, reference_edges),
                        **metrics,
                    }
                )
    return rows


def discover_references(reference_root: Path) -> list[tuple[str, Path]]:
    references: list[tuple[str, Path]] = []
    for path in sorted(reference_root.glob("batch_*/*/updated_causal_graph.json")):
        report_id = normalize_case_key(f"{path.parent.parent.name}/{path.parent.name}")
        references.append((report_id, path))
    if len({report_id for report_id, _ in references}) != len(references):
        raise RuntimeError("Duplicate report IDs were discovered under the reference root.")
    return references


def write_rows(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REPLICATE_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def safe_report_filename(report_id: str) -> str:
    return report_id.replace("/", "__") + ".csv"


def summarize_report_rows(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, float], list[dict[str, str]]] = {}
    for row in rows:
        key = (row["report_id"], row["control"], float(row["severity"]))
        grouped.setdefault(key, []).append(row)
    summary: list[dict[str, Any]] = []
    for (report_id, control, severity), group in sorted(grouped.items()):
        summary.append(
            {
                "report_id": report_id,
                "control": control,
                "severity": severity,
                "replicate_count": len(group),
                "mean_actual_node_fraction": mean(float(row["actual_node_fraction"]) for row in group),
                "mean_actual_edge_fraction": mean(float(row["actual_edge_fraction"]) for row in group),
                "mean_wl_similarity": mean(float(row["wl_similarity"]) for row in group),
                "mean_graph_edit_similarity": mean(float(row["graph_edit_similarity"]) for row in group),
            }
        )
    return summary


def mean_ci(values: list[float]) -> tuple[float, float, float, float]:
    center = mean(values)
    if len(values) < 2:
        return center, 0.0, center, center
    sd = stdev(values)
    half_width = float(stats.t.ppf(0.975, len(values) - 1)) * sd / math.sqrt(len(values))
    return center, sd, center - half_width, center + half_width


def cohen_dz(differences: list[float]) -> float:
    if len(differences) < 2:
        return float("nan")
    sd = stdev(differences)
    if sd == 0:
        return math.inf if mean(differences) > 0 else 0.0
    return mean(differences) / sd


def holm_adjust(p_values: list[float]) -> list[float]:
    adjusted = [float("nan")] * len(p_values)
    finite_indices = [index for index, value in enumerate(p_values) if math.isfinite(value)]
    ordered = sorted(finite_indices, key=lambda index: p_values[index])
    running = 0.0
    total = len(ordered)
    for rank, index in enumerate(ordered):
        running = max(running, (total - rank) * p_values[index])
        adjusted[index] = min(1.0, running)
    return adjusted


def summarize_overall(report_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, float, str], list[float]] = {}
    for row in report_rows:
        if row["control"] == "positive_control":
            continue
        for metric in ("mean_wl_similarity", "mean_graph_edit_similarity"):
            key = (str(row["control"]), float(row["severity"]), metric)
            grouped.setdefault(key, []).append(float(row[metric]))

    results: list[dict[str, Any]] = []
    raw_p_values: list[float] = []
    for (control, severity, metric), values in sorted(grouped.items()):
        center, sd, ci_low, ci_high = mean_ci(values)
        decreases = [1.0 - value for value in values]
        test = stats.ttest_1samp(decreases, popmean=0.0, nan_policy="raise")
        raw_p = float(test.pvalue)
        raw_p_values.append(raw_p)
        results.append(
            {
                "control": control,
                "severity": severity,
                "metric": metric,
                "report_count": len(values),
                "mean_score": center,
                "sd_score": sd,
                "score_ci95_low": ci_low,
                "score_ci95_high": ci_high,
                "mean_decrease_from_positive": mean(decreases),
                "cohen_dz": cohen_dz(decreases),
                "raw_p_value": raw_p,
            }
        )
    for row, adjusted in zip(results, holm_adjust(raw_p_values)):
        row["holm_adjusted_p_value"] = adjusted
    return results


def write_dict_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise RuntimeError(f"No rows available for {path.name}.")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def monotonicity_audit(overall_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    audit: list[dict[str, Any]] = []
    pairs = sorted({(row["control"], row["metric"]) for row in overall_rows})
    for control, metric in pairs:
        rows = sorted(
            (
                row
                for row in overall_rows
                if row["control"] == control and row["metric"] == metric
            ),
            key=lambda row: row["severity"],
        )
        scores = [float(row["mean_score"]) for row in rows]
        audit.append(
            {
                "control": control,
                "metric": metric,
                "severities": [row["severity"] for row in rows],
                "mean_scores": scores,
                "nonincreasing_with_severity": all(
                    later <= earlier + 1e-12 for earlier, later in zip(scores, scores[1:])
                ),
            }
        )
    return audit


def main() -> int:
    args = parse_args()
    if args.replicates < 1:
        raise ValueError("--replicates must be at least 1.")
    if args.workers < 1:
        raise ValueError("--workers must be at least 1.")
    severities = tuple(sorted(set(float(value) for value in args.severities)))
    if not severities or any(value <= 0 or value > 1 for value in severities):
        raise ValueError("Every severity must be in the interval (0, 1].")

    reference_root = args.reference_root.resolve()
    references = discover_references(reference_root)
    configured_exclusions = set()
    if not args.include_excluded:
        configured_exclusions = load_excluded_case_keys(args.excluded_cases)
        references = [item for item in references if item[0] not in configured_exclusions]
    if args.limit is not None:
        references = references[: args.limit]
    if len(references) != args.expected_reports:
        raise RuntimeError(
            f"Expected {args.expected_reports} retained reports, found {len(references)}."
        )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = (
        args.output_dir
        if args.output_dir is not None
        else Path("runs/stability_test/topology_negative_controls") / timestamp
    ).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    shard_dir = output_dir / "report_shards"
    shard_dir.mkdir(parents=True, exist_ok=True)

    pending: list[tuple[str, Path]] = []
    for report_id, reference_path in references:
        shard_path = shard_dir / safe_report_filename(report_id)
        if args.overwrite_shards or not shard_path.exists():
            pending.append((report_id, reference_path))

    print(f"Reference reports: {len(references)}")
    print(f"Excluded development reports: {len(configured_exclusions)}")
    print(f"Controls: {', '.join(args.controls)}")
    print(f"Severities: {', '.join(f'{value:.0%}' for value in severities)}")
    print(f"Randomizations per report/control/severity: {args.replicates}")
    print(f"Pending report shards: {len(pending)}")
    print(f"Output: {output_dir}")

    failures: list[dict[str, str]] = []
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                evaluate_report,
                str(reference_path),
                report_id,
                tuple(args.controls),
                severities,
                args.replicates,
                args.seed,
            ): report_id
            for report_id, reference_path in pending
        }
        with tqdm(total=len(futures), desc="Topology-control reports", unit="report") as progress:
            for future in as_completed(futures):
                report_id = futures[future]
                try:
                    rows = future.result()
                    write_rows(shard_dir / safe_report_filename(report_id), rows)
                except Exception as exc:
                    failures.append({"report_id": report_id, "error": repr(exc)})
                progress.update(1)

    if failures:
        (output_dir / "failures.json").write_text(
            json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        raise RuntimeError(f"{len(failures)} report-level tasks failed; see failures.json.")

    all_replicate_rows: list[dict[str, str]] = []
    for report_id, _ in references:
        shard_path = shard_dir / safe_report_filename(report_id)
        if not shard_path.exists():
            raise RuntimeError(f"Missing completed shard: {shard_path}")
        all_replicate_rows.extend(read_rows(shard_path))
    write_rows(output_dir / "replicate_scores.csv", all_replicate_rows)

    report_summary = summarize_report_rows(all_replicate_rows)
    overall_summary = summarize_overall(report_summary)
    write_dict_csv(output_dir / "report_summary.csv", report_summary)
    write_dict_csv(output_dir / "overall_summary.csv", overall_summary)

    expected_rows_per_report = 1 + len(args.controls) * len(severities) * args.replicates
    audit = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "reference_root": str(reference_root),
        "excluded_cases_path": (
            None if args.include_excluded else str(args.excluded_cases.resolve())
        ),
        "configured_excluded_case_count": len(configured_exclusions),
        "configured_excluded_cases": sorted(configured_exclusions),
        "retained_report_count": len(references),
        "retained_reports": [report_id for report_id, _ in references],
        "controls": list(args.controls),
        "severities": list(severities),
        "replicates": args.replicates,
        "base_seed": args.seed,
        "workers": args.workers,
        "expected_rows_per_report": expected_rows_per_report,
        "replicate_row_count": len(all_replicate_rows),
        "wl_method": "grakel_weisfeiler_lehman_n_iter_2_label_only",
        "ges_method": GED_BIPARTITE_METHOD_ID,
        "topology_only": True,
        "attributes_deliberately_unchanged": [
            "node labels",
            "node types",
            "edge relations",
            "textual evidence",
        ],
        "monotonicity": monotonicity_audit(overall_summary),
    }
    (output_dir / "topology_negative_control_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Completed {len(all_replicate_rows)} graph comparisons.")
    print(f"Saved report and overall summaries to {output_dir}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
