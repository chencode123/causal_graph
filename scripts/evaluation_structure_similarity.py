from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Iterable, List, Tuple

import networkx as nx
from grakel import Graph, GraphKernel


NODE_GROUP_KEYS = (
    "hazard_consequence_node",
    "entity_nodes",
    "condition_nodes",
    "event_nodes",
)

CASE_SCORE_COLUMNS = [
    "case_id",
    "batch_id",
    "hazard_consequence_type",
    "structural_similarity",
    "graph_edit_distance",
    "normalized_graph_edit_distance",
    "graph_edit_similarity",
    "generated_node_count",
    "updated_node_count",
    "generated_edge_count",
    "updated_edge_count",
    "verified_construction_steps",
    "max_path_length",
    "method",
    "status",
    "warnings",
]

BATCH_SCORE_COLUMNS = [
    "batch_id",
    "case_count",
    "success_case_count",
    "failed_case_count",
    "mean_structural_similarity",
    "mean_graph_edit_distance",
    "mean_normalized_graph_edit_distance",
    "mean_graph_edit_similarity",
    "mean_generated_node_count",
    "mean_updated_node_count",
    "mean_generated_edge_count",
    "mean_updated_edge_count",
    "mean_verified_construction_steps",
    "mean_max_path_length",
]

OVERALL_SUMMARY_COLUMNS = [
    "total_batch_count",
    "total_case_count",
    "successful_case_count",
    "failed_case_count",
    "overall_mean_structural_similarity",
    "overall_mean_graph_edit_distance",
    "overall_mean_normalized_graph_edit_distance",
    "overall_mean_graph_edit_similarity",
    "overall_mean_generated_node_count",
    "overall_mean_updated_node_count",
    "overall_mean_generated_edge_count",
    "overall_mean_updated_edge_count",
    "overall_mean_verified_construction_steps",
    "overall_mean_max_path_length",
]


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the batch evaluation script."""
    parser = argparse.ArgumentParser(
        description=(
            "Compare structural similarity between causal_graph.json and "
            "updated_causal_graph.json across case folders."
        )
    )
    parser.add_argument(
        "--parent-dir",
        type=Path,
        default=Path("runs/batch_api_test_1"),
        help="Parent directory to recursively scan for case folders.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("runs/batch_api_test_1/results"),
        help="Directory where CSV result files will be written.",
    )
    return parser.parse_args()


def resolve_updated_graph_path(case_folder: Path) -> Path | None:
    """Resolve the updated graph file with strict priority."""
    exact_path = case_folder / "updated_causal_graph.json"
    if exact_path.exists():
        return exact_path

    fallback_candidates = sorted(case_folder.glob("updated_causal_graph*.json"))
    return fallback_candidates[0] if fallback_candidates else None


def find_case_folders(parent_dir: Path) -> List[Path]:
    """Recursively find folders containing both required JSON files."""
    valid_folders: List[Path] = []
    for folder in parent_dir.rglob("*"):
        if not folder.is_dir():
            continue
        if (folder / "causal_graph.json").exists() and resolve_updated_graph_path(folder) is not None:
            valid_folders.append(folder)
    return sorted(valid_folders)


def load_json(path: Path) -> Dict[str, Any]:
    """Load a JSON file into a dictionary."""
    with path.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def flatten_nodes(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Flatten all supported node groups into a single node list."""
    nodes: List[Dict[str, Any]] = []
    for key in NODE_GROUP_KEYS:
        group_nodes = data.get(key, [])
        if isinstance(group_nodes, list):
            nodes.extend(group_nodes)
    return nodes


def read_edges(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Read the edge list from a graph JSON payload."""
    edges = data.get("edges", [])
    return edges if isinstance(edges, list) else []


def build_directed_graph(
    nodes: Iterable[Dict[str, Any]],
    edges: Iterable[Dict[str, Any]],
) -> Tuple[nx.DiGraph, List[str]]:
    """Build a directed NetworkX graph using only node label for GraKeL labels."""
    graph = nx.DiGraph()
    warnings: List[str] = []
    fallback_index = 0

    for node in nodes:
        node_id = str(node.get("node_id") or "").strip()
        if not node_id:
            fallback_index += 1
            node_id = f"missing_node_id_{fallback_index}"
            warnings.append("Node without node_id found; generated fallback id.")

        label = str(node.get("label") or "").strip()
        if not label:
            label = "UNKNOWN_LABEL"
            warnings.append(f"Node {node_id} missing label; replaced with UNKNOWN_LABEL.")

        if graph.has_node(node_id):
            warnings.append(f"Duplicate node_id detected and overwritten: {node_id}.")
        graph.add_node(node_id, label=label)

    for edge in edges:
        source = str(edge.get("source") or "").strip()
        target = str(edge.get("target") or "").strip()
        if not source or not target:
            warnings.append("Edge with missing source or target was skipped.")
            continue
        if not graph.has_node(source) or not graph.has_node(target):
            warnings.append(f"Edge {source}->{target} references missing node and was skipped.")
            continue
        graph.add_edge(source, target)

    return graph, warnings


def to_grakel_graph(graph: nx.DiGraph) -> Graph:
    """Convert a NetworkX directed graph into a GraKeL graph."""
    adjacency = {
        node: {neighbor: 1.0 for neighbor in graph.successors(node)}
        for node in graph.nodes()
    }
    node_labels = {node: graph.nodes[node].get("label", "UNKNOWN_LABEL") for node in graph.nodes()}
    return Graph(initialization_object=adjacency, node_labels=node_labels)


def compute_structural_similarity(generated_graph: nx.DiGraph, updated_graph: nx.DiGraph) -> float:
    """Compute normalized Weisfeiler-Lehman structural similarity with n_iter=2."""
    kernel = GraphKernel(
        kernel=[
            {"name": "weisfeiler_lehman", "n_iter": 2},
            {"name": "vertex_histogram"},
        ],
        normalize=True,
    )
    grakel_graphs = [to_grakel_graph(generated_graph), to_grakel_graph(updated_graph)]
    similarity_matrix = kernel.fit_transform(grakel_graphs)
    return float(similarity_matrix[0, 1])


def compute_graph_edit_metrics(
    generated_graph: nx.DiGraph,
    updated_graph: nx.DiGraph,
) -> Tuple[float, float, float]:
    """Compute GED, normalized GED, and GED-based similarity."""
    ged_candidates = nx.optimize_graph_edit_distance(
        generated_graph,
        updated_graph,
        node_match=lambda left, right: left.get("label", "") == right.get("label", ""),
    )
    graph_edit_distance = float(next(ged_candidates))
    size_denominator = (
        generated_graph.number_of_nodes()
        + updated_graph.number_of_nodes()
        + generated_graph.number_of_edges()
        + updated_graph.number_of_edges()
    )
    normalized_graph_edit_distance = (
        graph_edit_distance / size_denominator if size_denominator > 0 else 0.0
    )
    graph_edit_similarity = max(0.0, 1.0 - normalized_graph_edit_distance)
    return graph_edit_distance, normalized_graph_edit_distance, graph_edit_similarity


def infer_batch_id(case_folder: Path, parent_dir: Path) -> str:
    """Infer batch id from the first relative path component under the parent directory."""
    relative_parts = case_folder.relative_to(parent_dir).parts
    if len(relative_parts) >= 2:
        return relative_parts[0]
    return "root"


def mean_or_blank(values: List[float]) -> str:
    """Return a mean string for non-empty lists, otherwise blank."""
    if not values:
        return ""
    return f"{mean(values):.6f}"


def compute_verified_construction_steps(updated_graph: nx.DiGraph) -> int:
    """Compute the minimal from-scratch drawing steps for the verified graph."""
    return updated_graph.number_of_nodes() + updated_graph.number_of_edges()


def compute_topology_metrics(graph: nx.DiGraph) -> Dict[str, float]:
    """Compute path-length topology metrics on the verified graph."""
    if graph.number_of_nodes() == 0:
        return {"max_path_length": 0.0}

    condensation_graph = nx.condensation(graph)
    if condensation_graph.number_of_nodes() == 0:
        max_path_length = 0.0
    else:
        topological_nodes = list(nx.topological_sort(condensation_graph))
        longest_path_by_node = {node: 0.0 for node in topological_nodes}
        for node in reversed(topological_nodes):
            successor_lengths = [
                1.0 + longest_path_by_node[successor]
                for successor in condensation_graph.successors(node)
            ]
            longest_path_by_node[node] = max(successor_lengths, default=0.0)
        max_path_length = max(longest_path_by_node.values(), default=0.0)

    return {
        "max_path_length": max_path_length,
    }


def load_hazard_consequence_type(case_folder: Path) -> str:
    """Load the identified hazard consequence label for the case when available."""
    path = case_folder / "identify_hazard_consequence_output.json"
    if not path.exists():
        return ""
    try:
        payload = load_json(path)
    except Exception:
        return ""
    node = payload.get("hazard_consequence_node")
    if not isinstance(node, dict):
        return ""
    return str(node.get("name") or "").strip()


def evaluate_case(case_folder: Path, parent_dir: Path) -> Dict[str, Any]:
    """Evaluate one case folder and return a CSV-ready row."""
    case_id = case_folder.name
    batch_id = infer_batch_id(case_folder, parent_dir)
    method = "grakel_weisfeiler_lehman_n_iter_2_generated_vs_updated_label_only"

    row: Dict[str, Any] = {
        "case_id": case_id,
        "batch_id": batch_id,
        "hazard_consequence_type": "",
        "structural_similarity": "",
        "graph_edit_distance": "",
        "normalized_graph_edit_distance": "",
        "graph_edit_similarity": "",
        "generated_node_count": "",
        "updated_node_count": "",
        "generated_edge_count": "",
        "updated_edge_count": "",
        "verified_construction_steps": "",
        "max_path_length": "",
        "method": method,
        "status": "failed",
        "warnings": "",
    }

    try:
        generated_data = load_json(case_folder / "causal_graph.json")
        updated_graph_path = resolve_updated_graph_path(case_folder)
        if updated_graph_path is None:
            raise FileNotFoundError("No updated_causal_graph*.json file found.")
        updated_data = load_json(updated_graph_path)

        generated_nodes = flatten_nodes(generated_data)
        updated_nodes = flatten_nodes(updated_data)
        generated_edges = read_edges(generated_data)
        updated_edges = read_edges(updated_data)

        generated_graph, generated_warnings = build_directed_graph(generated_nodes, generated_edges)
        updated_graph, updated_warnings = build_directed_graph(updated_nodes, updated_edges)

        similarity = compute_structural_similarity(generated_graph, updated_graph)
        (
            graph_edit_distance,
            normalized_graph_edit_distance,
            graph_edit_similarity,
        ) = compute_graph_edit_metrics(generated_graph, updated_graph)
        verified_construction_steps = compute_verified_construction_steps(updated_graph)
        topology_metrics = compute_topology_metrics(updated_graph)
        hazard_consequence_type = load_hazard_consequence_type(case_folder)
        row.update(
            {
                "hazard_consequence_type": hazard_consequence_type,
                "structural_similarity": f"{similarity:.6f}",
                "graph_edit_distance": f"{graph_edit_distance:.6f}",
                "normalized_graph_edit_distance": f"{normalized_graph_edit_distance:.6f}",
                "graph_edit_similarity": f"{graph_edit_similarity:.6f}",
                "generated_node_count": generated_graph.number_of_nodes(),
                "updated_node_count": updated_graph.number_of_nodes(),
                "generated_edge_count": generated_graph.number_of_edges(),
                "updated_edge_count": updated_graph.number_of_edges(),
                "verified_construction_steps": verified_construction_steps,
                "max_path_length": f"{topology_metrics['max_path_length']:.6f}",
                "status": "ok",
                "warnings": " | ".join(
                    generated_warnings
                    + updated_warnings
                    + (
                        []
                        if updated_graph_path.name == "updated_causal_graph.json"
                        else [f"Used fallback updated graph file: {updated_graph_path.name}."]
                    )
                ),
            }
        )
    except Exception as exc:
        row["warnings"] = f"{type(exc).__name__}: {exc}"

    return row


def write_csv(path: Path, fieldnames: List[str], rows: List[Dict[str, Any]]) -> None:
    """Write rows to a CSV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def make_run_output_dir(base_output_dir: Path) -> Path:
    """Create a timestamped output directory for the current evaluation run."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_output_dir = base_output_dir / timestamp
    run_output_dir.mkdir(parents=True, exist_ok=True)
    return run_output_dir


def build_batch_rows(case_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Aggregate case-level rows into batch-level summary rows."""
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in case_rows:
        grouped.setdefault(str(row["batch_id"]), []).append(row)

    batch_rows: List[Dict[str, Any]] = []
    for batch_id in sorted(grouped):
        rows = grouped[batch_id]
        success_rows = [row for row in rows if row["status"] == "ok"]

        batch_rows.append(
            {
                "batch_id": batch_id,
                "case_count": len(rows),
                "success_case_count": len(success_rows),
                "failed_case_count": len(rows) - len(success_rows),
                "mean_structural_similarity": mean_or_blank(
                    [float(row["structural_similarity"]) for row in success_rows]
                ),
                "mean_graph_edit_distance": mean_or_blank(
                    [float(row["graph_edit_distance"]) for row in success_rows]
                ),
                "mean_normalized_graph_edit_distance": mean_or_blank(
                    [float(row["normalized_graph_edit_distance"]) for row in success_rows]
                ),
                "mean_graph_edit_similarity": mean_or_blank(
                    [float(row["graph_edit_similarity"]) for row in success_rows]
                ),
                "mean_generated_node_count": mean_or_blank(
                    [float(row["generated_node_count"]) for row in success_rows]
                ),
                "mean_updated_node_count": mean_or_blank(
                    [float(row["updated_node_count"]) for row in success_rows]
                ),
                "mean_generated_edge_count": mean_or_blank(
                    [float(row["generated_edge_count"]) for row in success_rows]
                ),
                "mean_updated_edge_count": mean_or_blank(
                    [float(row["updated_edge_count"]) for row in success_rows]
                ),
                "mean_verified_construction_steps": mean_or_blank(
                    [float(row["verified_construction_steps"]) for row in success_rows]
                ),
                "mean_max_path_length": mean_or_blank(
                    [float(row["max_path_length"]) for row in success_rows]
                ),
            }
        )

    return batch_rows


def build_overall_summary(case_rows: List[Dict[str, Any]], batch_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build a single-row overall summary table."""
    success_rows = [row for row in case_rows if row["status"] == "ok"]
    return [
        {
            "total_batch_count": len(batch_rows),
            "total_case_count": len(case_rows),
            "successful_case_count": len(success_rows),
            "failed_case_count": len(case_rows) - len(success_rows),
            "overall_mean_structural_similarity": mean_or_blank(
                [float(row["structural_similarity"]) for row in success_rows]
            ),
            "overall_mean_graph_edit_distance": mean_or_blank(
                [float(row["graph_edit_distance"]) for row in success_rows]
            ),
            "overall_mean_normalized_graph_edit_distance": mean_or_blank(
                [float(row["normalized_graph_edit_distance"]) for row in success_rows]
            ),
            "overall_mean_graph_edit_similarity": mean_or_blank(
                [float(row["graph_edit_similarity"]) for row in success_rows]
            ),
            "overall_mean_generated_node_count": mean_or_blank(
                [float(row["generated_node_count"]) for row in success_rows]
            ),
            "overall_mean_updated_node_count": mean_or_blank(
                [float(row["updated_node_count"]) for row in success_rows]
            ),
            "overall_mean_generated_edge_count": mean_or_blank(
                [float(row["generated_edge_count"]) for row in success_rows]
            ),
            "overall_mean_updated_edge_count": mean_or_blank(
                [float(row["updated_edge_count"]) for row in success_rows]
            ),
            "overall_mean_verified_construction_steps": mean_or_blank(
                [float(row["verified_construction_steps"]) for row in success_rows]
            ),
            "overall_mean_max_path_length": mean_or_blank(
                [float(row["max_path_length"]) for row in success_rows]
            ),
        }
    ]


def main() -> Path:
    """Run the batch structural similarity evaluation pipeline."""
    args = parse_args()
    parent_dir = args.parent_dir
    output_dir = make_run_output_dir(args.output_dir)

    case_folders = find_case_folders(parent_dir)
    case_rows = [evaluate_case(folder, parent_dir) for folder in case_folders]
    batch_rows = build_batch_rows(case_rows)
    overall_rows = build_overall_summary(case_rows, batch_rows)

    write_csv(output_dir / "case_scores.csv", CASE_SCORE_COLUMNS, case_rows)
    write_csv(output_dir / "batch_scores.csv", BATCH_SCORE_COLUMNS, batch_rows)
    write_csv(output_dir / "overall_summary.csv", OVERALL_SUMMARY_COLUMNS, overall_rows)

    print(f"Scanned {len(case_folders)} case folder(s) under {parent_dir}.")
    print(f"Saved case_scores.csv, batch_scores.csv, and overall_summary.csv to {output_dir}.")
    return output_dir


if __name__ == "__main__":
    main()
