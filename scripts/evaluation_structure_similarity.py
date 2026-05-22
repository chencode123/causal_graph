from __future__ import annotations

import argparse
import os
import csv
import json
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Iterable, List, Tuple

import networkx as nx
from grakel import Graph, GraphKernel
from tqdm import tqdm

try:
    from scipy.optimize import linear_sum_assignment
except ImportError:
    linear_sum_assignment = None


NODE_GROUP_KEYS = (
    "hazard_consequence_node",
    "entity_nodes",
    "condition_nodes",
    "event_nodes",
)

CASE_SCORE_COLUMNS = [
    "round",
    "batch_id",
    "case_id",
    "hazard_consequence_type",
    "structural_similarity",
    "graph_edit_distance",
    "normalized_graph_edit_distance",
    "graph_edit_similarity",
    "structural_similarity_accept_all_vs_updated",
    "graph_edit_distance_accept_all_vs_updated",
    "normalized_graph_edit_distance_accept_all_vs_updated",
    "graph_edit_similarity_accept_all_vs_updated",
    "verified_construction_steps",
    "max_path_length",
    "method",
    "status",
    "warnings",
]

GED_ALGORITHM_EXACT = "exact"
GED_ALGORITHM_FAST = "fast"
GED_ALGORITHM_BIPARTITE = "bipartite"
GED_ALGORITHM_CHOICES = (
    GED_ALGORITHM_EXACT,
    GED_ALGORITHM_FAST,
    GED_ALGORITHM_BIPARTITE,
)

BATCH_SCORE_COLUMNS = [
    "batch_id",
    "case_count",
    "success_case_count",
    "failed_case_count",
    "mean_structural_similarity",
    "mean_graph_edit_distance",
    "mean_normalized_graph_edit_distance",
    "mean_graph_edit_similarity",
    "mean_structural_similarity_accept_all_vs_updated",
    "mean_graph_edit_distance_accept_all_vs_updated",
    "mean_normalized_graph_edit_distance_accept_all_vs_updated",
    "mean_graph_edit_similarity_accept_all_vs_updated",
    "mean_generated_node_count",
    "mean_accept_all_node_count",
    "mean_updated_node_count",
    "mean_generated_edge_count",
    "mean_accept_all_edge_count",
    "mean_updated_edge_count",
    "mean_verified_construction_steps",
    "mean_max_path_length",
    "total_ged_node_insertion_count",
    "total_ged_node_deletion_count",
    "total_ged_node_substitution_count",
    "total_ged_edge_insertion_count",
    "total_ged_edge_deletion_count",
    "total_ged_edge_substitution_count",
    "total_ged_node_insertion_count_accept_all_vs_updated",
    "total_ged_node_deletion_count_accept_all_vs_updated",
    "total_ged_node_substitution_count_accept_all_vs_updated",
    "total_ged_edge_insertion_count_accept_all_vs_updated",
    "total_ged_edge_deletion_count_accept_all_vs_updated",
    "total_ged_edge_substitution_count_accept_all_vs_updated",
    "mean_ged_node_insertion_count",
    "mean_ged_node_deletion_count",
    "mean_ged_node_substitution_count",
    "mean_ged_edge_insertion_count",
    "mean_ged_edge_deletion_count",
    "mean_ged_edge_substitution_count",
    "mean_ged_node_insertion_count_accept_all_vs_updated",
    "mean_ged_node_deletion_count_accept_all_vs_updated",
    "mean_ged_node_substitution_count_accept_all_vs_updated",
    "mean_ged_edge_insertion_count_accept_all_vs_updated",
    "mean_ged_edge_deletion_count_accept_all_vs_updated",
    "mean_ged_edge_substitution_count_accept_all_vs_updated",
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
    "overall_mean_structural_similarity_accept_all_vs_updated",
    "overall_mean_graph_edit_distance_accept_all_vs_updated",
    "overall_mean_normalized_graph_edit_distance_accept_all_vs_updated",
    "overall_mean_graph_edit_similarity_accept_all_vs_updated",
    "overall_mean_generated_node_count",
    "overall_mean_accept_all_node_count",
    "overall_mean_updated_node_count",
    "overall_mean_generated_edge_count",
    "overall_mean_accept_all_edge_count",
    "overall_mean_updated_edge_count",
    "overall_mean_verified_construction_steps",
    "overall_mean_max_path_length",
    "overall_total_ged_node_insertion_count",
    "overall_total_ged_node_deletion_count",
    "overall_total_ged_node_substitution_count",
    "overall_total_ged_edge_insertion_count",
    "overall_total_ged_edge_deletion_count",
    "overall_total_ged_edge_substitution_count",
    "overall_total_ged_node_insertion_count_accept_all_vs_updated",
    "overall_total_ged_node_deletion_count_accept_all_vs_updated",
    "overall_total_ged_node_substitution_count_accept_all_vs_updated",
    "overall_total_ged_edge_insertion_count_accept_all_vs_updated",
    "overall_total_ged_edge_deletion_count_accept_all_vs_updated",
    "overall_total_ged_edge_substitution_count_accept_all_vs_updated",
    "overall_mean_ged_node_insertion_count",
    "overall_mean_ged_node_deletion_count",
    "overall_mean_ged_node_substitution_count",
    "overall_mean_ged_edge_insertion_count",
    "overall_mean_ged_edge_deletion_count",
    "overall_mean_ged_edge_substitution_count",
    "overall_mean_ged_node_insertion_count_accept_all_vs_updated",
    "overall_mean_ged_node_deletion_count_accept_all_vs_updated",
    "overall_mean_ged_node_substitution_count_accept_all_vs_updated",
    "overall_mean_ged_edge_insertion_count_accept_all_vs_updated",
    "overall_mean_ged_edge_deletion_count_accept_all_vs_updated",
    "overall_mean_ged_edge_substitution_count_accept_all_vs_updated",
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
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help=(
            "Number of worker processes for parallel case evaluation. "
            "Defaults to min(CPU count, number of cases). Use 1 to disable parallelism."
        ),
    )
    parser.add_argument(
        "--compute-ged",
        dest="compute_ged",
        action="store_true",
        help="Compute GED-based metrics such as graph_edit_distance and normalized_graph_edit_distance.",
    )
    parser.add_argument(
        "--skip-ged",
        dest="compute_ged",
        action="store_false",
        help="Skip GED-based metrics and leave GED-related CSV fields blank.",
    )
    parser.add_argument(
        "--compute-ged-operation-counts",
        dest="compute_ged_operation_counts",
        action="store_true",
        help="Compute per-case node/edge insertion, deletion, and substitution counts.",
    )
    parser.add_argument(
        "--skip-ged-operation-counts",
        dest="compute_ged_operation_counts",
        action="store_false",
        help="Skip the expensive GED operation-count calculation.",
    )
    parser.add_argument(
        "--show-progress",
        dest="show_progress",
        action="store_true",
        help="Show the live tqdm progress bar during evaluation.",
    )
    parser.add_argument(
        "--hide-progress",
        dest="show_progress",
        action="store_false",
        help="Hide the live tqdm progress bar and only print summary output.",
    )
    parser.add_argument(
        "--ged-algorithm",
        choices=GED_ALGORITHM_CHOICES,
        default=GED_ALGORITHM_EXACT,
        help=(
            "GED algorithm to use: "
            "'exact' exhausts candidates, "
            "'fast' uses the first NetworkX candidate, "
            "and 'bipartite' uses a faster structure-aware assignment approximation."
        ),
    )
    parser.add_argument(
        "--exact-ged",
        dest="ged_algorithm",
        action="store_const",
        const=GED_ALGORITHM_EXACT,
        help="Legacy alias for --ged-algorithm exact.",
    )
    parser.add_argument(
        "--fast-ged",
        dest="ged_algorithm",
        action="store_const",
        const=GED_ALGORITHM_FAST,
        help="Legacy alias for --ged-algorithm fast.",
    )
    parser.add_argument(
        "--bipartite-ged",
        dest="ged_algorithm",
        action="store_const",
        const=GED_ALGORITHM_BIPARTITE,
        help="Legacy alias for --ged-algorithm bipartite.",
    )
    parser.add_argument(
        "--ged-timeout",
        type=float,
        default=None,
        help=(
            "Maximum seconds for each exact GED calculation. "
            "When set, NetworkX returns the current best GED after the timeout."
        ),
    )
    parser.set_defaults(compute_ged=True)
    parser.set_defaults(compute_ged_operation_counts=True)
    parser.set_defaults(show_progress=True)
    return parser.parse_args()


def resolve_updated_graph_path(case_folder: Path) -> Path | None:
    """Resolve the updated graph file by exact filename only."""
    exact_path = case_folder / "updated_causal_graph.json"
    if exact_path.exists():
        return exact_path
    return None


def resolve_accept_all_graph_path(case_folder: Path) -> Path | None:
    """Resolve the accept-all updated graph file with strict priority."""
    exact_path = case_folder / "updated_causal_graph_accept_all.json"
    if exact_path.exists():
        return exact_path
    fallback_candidates = sorted(case_folder.glob("updated_causal_graph_accept_all*.json"))
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


def to_float(value: str) -> float | None:
    """Convert a string value to float when possible."""
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


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
        relation = str(edge.get("relation") or edge.get("label") or "").strip()
        graph.add_edge(source, target, relation=relation, label=relation)

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


def node_labels_match(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    """Match nodes using the same label-only rule as the GED score."""
    return left.get("label", "") == right.get("label", "")


def edge_labels_match(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    """Match edges by relation/label when extracting edit-operation counts."""
    left_relation = str(left.get("relation") or left.get("label") or "").strip()
    right_relation = str(right.get("relation") or right.get("label") or "").strip()
    return left_relation == right_relation


def make_blank_operation_counts() -> Dict[str, int]:
    """Return zeroed GED operation counts."""
    return {
        "ged_node_insertion_count": 0,
        "ged_node_deletion_count": 0,
        "ged_node_substitution_count": 0,
        "ged_edge_insertion_count": 0,
        "ged_edge_deletion_count": 0,
        "ged_edge_substitution_count": 0,
    }


def compute_component_depths(graph: nx.DiGraph) -> Tuple[Dict[int, int], Dict[int, int], Dict[str, int]]:
    """Compute SCC-level forward/backward depths for structure-aware matching."""
    if graph.number_of_nodes() == 0:
        return {}, {}, {}

    condensation_graph = nx.condensation(graph)
    component_by_node = condensation_graph.graph.get("mapping", {})
    topological_nodes = list(nx.topological_sort(condensation_graph))
    forward_depth = {node: 0 for node in topological_nodes}
    for node in topological_nodes:
        for successor in condensation_graph.successors(node):
            forward_depth[successor] = max(forward_depth[successor], forward_depth[node] + 1)

    backward_depth = {node: 0 for node in topological_nodes}
    for node in reversed(topological_nodes):
        for predecessor in condensation_graph.predecessors(node):
            backward_depth[predecessor] = max(backward_depth[predecessor], backward_depth[node] + 1)

    return forward_depth, backward_depth, component_by_node


def compute_structural_node_profiles(graph: nx.DiGraph, iterations: int = 2) -> Dict[str, Dict[str, Any]]:
    """Build structure-only node profiles for bipartite GED matching."""
    forward_depth, backward_depth, component_by_node = compute_component_depths(graph)
    scc_size_by_component: Dict[int, int] = {}
    for component_id in component_by_node.values():
        scc_size_by_component[component_id] = scc_size_by_component.get(component_id, 0) + 1
    weak_component_by_node: Dict[str, int] = {}
    for component_nodes in nx.weakly_connected_components(graph):
        component_size = len(component_nodes)
        for node in component_nodes:
            weak_component_by_node[str(node)] = component_size

    refinement_tokens = {
        node: f"in{graph.in_degree(node)}|out{graph.out_degree(node)}"
        for node in graph.nodes()
    }
    for _ in range(iterations):
        next_tokens: Dict[str, str] = {}
        for node in graph.nodes():
            predecessor_tokens = sorted(refinement_tokens[pred] for pred in graph.predecessors(node))
            successor_tokens = sorted(refinement_tokens[succ] for succ in graph.successors(node))
            next_tokens[node] = (
                f"{refinement_tokens[node]}|pred:{'|'.join(predecessor_tokens)}"
                f"|succ:{'|'.join(successor_tokens)}"
            )
        refinement_tokens = next_tokens

    profiles: Dict[str, Dict[str, Any]] = {}
    for node in graph.nodes():
        component_id = component_by_node.get(node, -1)
        profiles[str(node)] = {
            "in_degree": graph.in_degree(node),
            "out_degree": graph.out_degree(node),
            "total_degree": graph.in_degree(node) + graph.out_degree(node),
            "scc_size": scc_size_by_component.get(component_id, 1),
            "weak_component_size": weak_component_by_node.get(str(node), 1),
            "forward_depth": forward_depth.get(component_id, 0),
            "backward_depth": backward_depth.get(component_id, 0),
            "signature": refinement_tokens[node],
        }
    return profiles


def node_substitution_cost(
    generated_profile: Dict[str, Any],
    updated_profile: Dict[str, Any],
) -> float:
    """Return a structure-first substitution cost for bipartite GED."""
    degree_cost = (
        abs(int(generated_profile["in_degree"]) - int(updated_profile["in_degree"]))
        + abs(int(generated_profile["out_degree"]) - int(updated_profile["out_degree"]))
    )
    topology_cost = (
        abs(int(generated_profile["forward_depth"]) - int(updated_profile["forward_depth"]))
        + abs(int(generated_profile["backward_depth"]) - int(updated_profile["backward_depth"]))
    )
    component_cost = abs(
        int(generated_profile["weak_component_size"]) - int(updated_profile["weak_component_size"])
    ) + abs(int(generated_profile["scc_size"]) - int(updated_profile["scc_size"]))
    signature_cost = 0.0 if generated_profile["signature"] == updated_profile["signature"] else 0.75
    return (
        (0.35 * float(degree_cost))
        + (0.2 * float(topology_cost))
        + (0.1 * float(component_cost))
        + signature_cost
    )


def compute_bipartite_operation_counts(
    generated_graph: nx.DiGraph,
    updated_graph: nx.DiGraph,
) -> Dict[str, int]:
    """Approximate GED edit operations using structure-aware bipartite matching."""
    if linear_sum_assignment is None:
        raise RuntimeError(
            "Bipartite GED requires scipy. Install scipy or use --ged-algorithm exact/fast."
        )

    generated_nodes = list(generated_graph.nodes())
    updated_nodes = list(updated_graph.nodes())
    generated_count = len(generated_nodes)
    updated_count = len(updated_nodes)

    if generated_count == 0 and updated_count == 0:
        return make_blank_operation_counts()

    generated_profiles = compute_structural_node_profiles(generated_graph)
    updated_profiles = compute_structural_node_profiles(updated_graph)
    matrix_size = generated_count + updated_count
    impossible_cost = float(
        (
            generated_count
            + updated_count
            + generated_graph.number_of_edges()
            + updated_graph.number_of_edges()
            + 1
        )
        * 1000
    )
    cost_matrix = [[0.0 for _ in range(matrix_size)] for _ in range(matrix_size)]

    for row_index, generated_node in enumerate(generated_nodes):
        for col_index, updated_node in enumerate(updated_nodes):
            cost_matrix[row_index][col_index] = node_substitution_cost(
                generated_profiles[str(generated_node)],
                updated_profiles[str(updated_node)],
            )
        for deletion_dummy_index in range(generated_count):
            cost_matrix[row_index][updated_count + deletion_dummy_index] = impossible_cost
        cost_matrix[row_index][updated_count + row_index] = 1.0

    for insertion_dummy_index in range(updated_count):
        row_index = generated_count + insertion_dummy_index
        for col_index in range(updated_count):
            cost_matrix[row_index][col_index] = impossible_cost
        cost_matrix[row_index][insertion_dummy_index] = 1.0
        for deletion_dummy_index in range(generated_count):
            cost_matrix[row_index][updated_count + deletion_dummy_index] = 0.0

    row_ind, col_ind = linear_sum_assignment(cost_matrix)
    assignment = {int(row): int(col) for row, col in zip(row_ind, col_ind)}

    counts = make_blank_operation_counts()
    generated_to_updated: Dict[str, str] = {}

    for row_index, generated_node in enumerate(generated_nodes):
        assigned_column = assignment[row_index]
        if assigned_column < updated_count:
            updated_node = updated_nodes[assigned_column]
            generated_to_updated[generated_node] = updated_node
        else:
            counts["ged_node_deletion_count"] += 1

    for insertion_dummy_index in range(updated_count):
        assigned_column = assignment[generated_count + insertion_dummy_index]
        if assigned_column < updated_count:
            counts["ged_node_insertion_count"] += 1

    matched_updated_edges = set()
    for source, target in generated_graph.edges():
        mapped_source = generated_to_updated.get(source)
        mapped_target = generated_to_updated.get(target)
        if mapped_source is None or mapped_target is None:
            counts["ged_edge_deletion_count"] += 1
            continue
        if updated_graph.has_edge(mapped_source, mapped_target):
            matched_updated_edges.add((mapped_source, mapped_target))
        else:
            counts["ged_edge_deletion_count"] += 1

    for source, target in updated_graph.edges():
        if (source, target) not in matched_updated_edges:
            counts["ged_edge_insertion_count"] += 1

    return counts


def summarize_graph_edit_metrics(
    generated_graph: nx.DiGraph,
    updated_graph: nx.DiGraph,
    graph_edit_distance: float,
) -> Tuple[float, float, float]:
    """Convert a raw GED value into normalized distance and similarity."""
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


def compute_bipartite_graph_edit_metrics(
    generated_graph: nx.DiGraph,
    updated_graph: nx.DiGraph,
) -> Tuple[float, float, float, Dict[str, int]]:
    """Compute bipartite GED metrics and return the reused operation counts."""
    operation_counts = compute_bipartite_operation_counts(generated_graph, updated_graph)
    graph_edit_distance = float(
        operation_counts["ged_node_insertion_count"]
        + operation_counts["ged_node_deletion_count"]
        + operation_counts["ged_node_substitution_count"]
        + operation_counts["ged_edge_insertion_count"]
        + operation_counts["ged_edge_deletion_count"]
    )
    metrics = summarize_graph_edit_metrics(
        generated_graph,
        updated_graph,
        graph_edit_distance,
    )
    return metrics[0], metrics[1], metrics[2], operation_counts


def compute_graph_edit_metrics(
    generated_graph: nx.DiGraph,
    updated_graph: nx.DiGraph,
    *,
    ged_algorithm: str = GED_ALGORITHM_EXACT,
    ged_timeout_seconds: float | None = None,
) -> Tuple[float, float, float]:
    """Compute GED, normalized GED, and GED-based similarity."""
    if ged_algorithm == GED_ALGORITHM_BIPARTITE:
        graph_edit_distance, normalized_graph_edit_distance, graph_edit_similarity, _ = (
            compute_bipartite_graph_edit_metrics(
                generated_graph,
                updated_graph,
            )
        )
        return graph_edit_distance, normalized_graph_edit_distance, graph_edit_similarity
    elif ged_algorithm == GED_ALGORITHM_EXACT and ged_timeout_seconds is not None:
        graph_edit_distance_raw = nx.graph_edit_distance(
            generated_graph,
            updated_graph,
            node_match=node_labels_match,
            timeout=ged_timeout_seconds,
        )
        if graph_edit_distance_raw is None:
            raise TimeoutError(
                f"No GED candidate was found before timeout={ged_timeout_seconds}s."
            )
        graph_edit_distance = float(graph_edit_distance_raw)
    else:
        ged_candidates = nx.optimize_graph_edit_distance(
            generated_graph,
            updated_graph,
            node_match=node_labels_match,
        )
        try:
            graph_edit_distance = float(
                min(ged_candidates)
                if ged_algorithm == GED_ALGORITHM_EXACT
                else next(ged_candidates)
            )
        except ValueError:
            graph_edit_distance = 0.0
    return summarize_graph_edit_metrics(
        generated_graph,
        updated_graph,
        graph_edit_distance,
    )


def compute_graph_edit_operation_counts(
    generated_graph: nx.DiGraph,
    updated_graph: nx.DiGraph,
) -> Dict[str, int]:
    """Count the six GED edit-operation categories for one optimal edit path."""
    optimal_paths, _ = nx.optimal_edit_paths(
        generated_graph,
        updated_graph,
        node_match=node_labels_match,
        edge_match=edge_labels_match,
    )
    if not optimal_paths:
        return {
            "ged_node_insertion_count": 0,
            "ged_node_deletion_count": 0,
            "ged_node_substitution_count": 0,
            "ged_edge_insertion_count": 0,
            "ged_edge_deletion_count": 0,
            "ged_edge_substitution_count": 0,
        }

    node_path, edge_path = optimal_paths[0]
    counts = {
        "ged_node_insertion_count": 0,
        "ged_node_deletion_count": 0,
        "ged_node_substitution_count": 0,
        "ged_edge_insertion_count": 0,
        "ged_edge_deletion_count": 0,
        "ged_edge_substitution_count": 0,
    }

    for left_node, right_node in node_path:
        if left_node is None and right_node is not None:
            counts["ged_node_insertion_count"] += 1
        elif left_node is not None and right_node is None:
            counts["ged_node_deletion_count"] += 1
        elif left_node is not None and right_node is not None and not node_labels_match(
            generated_graph.nodes[left_node],
            updated_graph.nodes[right_node],
        ):
            counts["ged_node_substitution_count"] += 1

    for left_edge, right_edge in edge_path:
        if left_edge is None and right_edge is not None:
            counts["ged_edge_insertion_count"] += 1
        elif left_edge is not None and right_edge is None:
            counts["ged_edge_deletion_count"] += 1
        elif left_edge is not None and right_edge is not None and not edge_labels_match(
            generated_graph.edges[left_edge],
            updated_graph.edges[right_edge],
        ):
            counts["ged_edge_substitution_count"] += 1

    return counts


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


def sum_or_zero(values: List[float]) -> int:
    """Return an integer sum for numeric values, defaulting to zero."""
    return int(round(sum(values))) if values else 0


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


def empty_operation_counts(suffix: str = "") -> Dict[str, str]:
    """Return blank GED operation counts when the expensive computation is skipped."""
    return {
        f"ged_node_insertion_count{suffix}": "",
        f"ged_node_deletion_count{suffix}": "",
        f"ged_node_substitution_count{suffix}": "",
        f"ged_edge_insertion_count{suffix}": "",
        f"ged_edge_deletion_count{suffix}": "",
        f"ged_edge_substitution_count{suffix}": "",
    }


def collect_numeric_values(rows: Iterable[Dict[str, Any]], key: str) -> List[float]:
    """Collect numeric values from rows while skipping blanks and invalid cells."""
    values: List[float] = []
    for row in rows:
        value = to_float(str(row.get(key, "")))
        if value is not None:
            values.append(value)
    return values


def evaluate_case(
    case_folder: Path,
    parent_dir: Path,
    compute_ged: bool = True,
    compute_ged_operation_counts: bool = True,
    ged_algorithm: str = GED_ALGORITHM_EXACT,
    ged_timeout_seconds: float | None = None,
) -> Dict[str, Any]:
    """Evaluate one case folder and return a CSV-ready row."""
    import re as _re
    case_id = case_folder.name
    _parts = case_folder.relative_to(parent_dir).parts
    if len(_parts) >= 3:
        round_label = _parts[0]
        batch_id = _re.sub(r"_output_round_\d+$", "", _parts[1])
    else:
        batch_id = infer_batch_id(case_folder, parent_dir)
        _m = _re.search(r"(round_\d+)", str(batch_id))
        round_label = _m.group(1) if _m else ""
    ged_method = f"ged_{ged_algorithm}" if compute_ged else "ged_skipped"
    method = "grakel_weisfeiler_lehman_n_iter_2_generated_vs_updated_label_only_" + ged_method

    row: Dict[str, Any] = {
        "round": round_label,
        "case_id": case_id,
        "batch_id": batch_id,
        "hazard_consequence_type": "",
        "structural_similarity": "",
        "graph_edit_distance": "",
        "normalized_graph_edit_distance": "",
        "graph_edit_similarity": "",
        "structural_similarity_accept_all_vs_updated": "",
        "graph_edit_distance_accept_all_vs_updated": "",
        "normalized_graph_edit_distance_accept_all_vs_updated": "",
        "graph_edit_similarity_accept_all_vs_updated": "",
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
            raise FileNotFoundError("No updated_causal_graph.json file found.")
        updated_data = load_json(updated_graph_path)
        accept_all_graph_path = resolve_accept_all_graph_path(case_folder)

        generated_nodes = flatten_nodes(generated_data)
        updated_nodes = flatten_nodes(updated_data)
        generated_edges = read_edges(generated_data)
        updated_edges = read_edges(updated_data)

        generated_graph, generated_warnings = build_directed_graph(generated_nodes, generated_edges)
        updated_graph, updated_warnings = build_directed_graph(updated_nodes, updated_edges)

        similarity = compute_structural_similarity(generated_graph, updated_graph)
        if compute_ged:
            if ged_algorithm == GED_ALGORITHM_BIPARTITE:
                (
                    graph_edit_distance,
                    normalized_graph_edit_distance,
                    graph_edit_similarity,
                    bipartite_operation_counts,
                ) = compute_bipartite_graph_edit_metrics(
                    generated_graph,
                    updated_graph,
                )
                operation_counts = (
                    bipartite_operation_counts if compute_ged_operation_counts else empty_operation_counts()
                )
            else:
                (
                    graph_edit_distance,
                    normalized_graph_edit_distance,
                    graph_edit_similarity,
                ) = compute_graph_edit_metrics(
                    generated_graph,
                    updated_graph,
                    ged_algorithm=ged_algorithm,
                    ged_timeout_seconds=ged_timeout_seconds,
                )
                if compute_ged_operation_counts:
                    operation_counts = compute_graph_edit_operation_counts(generated_graph, updated_graph)
                else:
                    operation_counts = empty_operation_counts()
        else:
            graph_edit_distance = None
            normalized_graph_edit_distance = None
            graph_edit_similarity = None
            operation_counts = empty_operation_counts()

        accept_all_warnings: List[str] = []
        accept_all_metrics: Dict[str, Any] = {
            "structural_similarity_accept_all_vs_updated": "",
            "graph_edit_distance_accept_all_vs_updated": "",
            "normalized_graph_edit_distance_accept_all_vs_updated": "",
            "graph_edit_similarity_accept_all_vs_updated": "",
            "accept_all_node_count": "",
            "accept_all_edge_count": "",
            **empty_operation_counts("_accept_all_vs_updated"),
        }
        if accept_all_graph_path is None:
            accept_all_warnings.append("Missing updated_causal_graph_accept_all.json.")
        else:
            accept_all_data = load_json(accept_all_graph_path)
            accept_all_nodes = flatten_nodes(accept_all_data)
            accept_all_edges = read_edges(accept_all_data)
            accept_all_graph, accept_all_graph_warnings = build_directed_graph(accept_all_nodes, accept_all_edges)
            accept_all_warnings.extend(accept_all_graph_warnings)
            accept_all_similarity = compute_structural_similarity(accept_all_graph, updated_graph)
            if compute_ged:
                if ged_algorithm == GED_ALGORITHM_BIPARTITE:
                    (
                        accept_all_graph_edit_distance,
                        accept_all_normalized_graph_edit_distance,
                        accept_all_graph_edit_similarity,
                        raw_accept_all_operation_counts,
                    ) = compute_bipartite_graph_edit_metrics(
                        accept_all_graph,
                        updated_graph,
                    )
                    accept_all_operation_counts = (
                        {
                            f"{key}_accept_all_vs_updated": value
                            for key, value in raw_accept_all_operation_counts.items()
                        }
                        if compute_ged_operation_counts
                        else empty_operation_counts("_accept_all_vs_updated")
                    )
                else:
                    (
                        accept_all_graph_edit_distance,
                        accept_all_normalized_graph_edit_distance,
                        accept_all_graph_edit_similarity,
                    ) = compute_graph_edit_metrics(
                        accept_all_graph,
                        updated_graph,
                        ged_algorithm=ged_algorithm,
                        ged_timeout_seconds=ged_timeout_seconds,
                    )
                    if compute_ged_operation_counts:
                        raw_accept_all_operation_counts = compute_graph_edit_operation_counts(
                            accept_all_graph,
                            updated_graph,
                        )
                        accept_all_operation_counts = {
                            f"{key}_accept_all_vs_updated": value
                            for key, value in raw_accept_all_operation_counts.items()
                        }
                    else:
                        accept_all_operation_counts = empty_operation_counts("_accept_all_vs_updated")
            else:
                accept_all_graph_edit_distance = None
                accept_all_normalized_graph_edit_distance = None
                accept_all_graph_edit_similarity = None
                accept_all_operation_counts = empty_operation_counts("_accept_all_vs_updated")
            accept_all_metrics.update(
                {
                    "structural_similarity_accept_all_vs_updated": f"{accept_all_similarity:.6f}",
                    "graph_edit_distance_accept_all_vs_updated": (
                        f"{accept_all_graph_edit_distance:.6f}"
                        if accept_all_graph_edit_distance is not None
                        else ""
                    ),
                    "normalized_graph_edit_distance_accept_all_vs_updated": (
                        f"{accept_all_normalized_graph_edit_distance:.6f}"
                        if accept_all_normalized_graph_edit_distance is not None
                        else ""
                    ),
                    "graph_edit_similarity_accept_all_vs_updated": (
                        f"{accept_all_graph_edit_similarity:.6f}"
                        if accept_all_graph_edit_similarity is not None
                        else ""
                    ),
                    "accept_all_node_count": accept_all_graph.number_of_nodes(),
                    "accept_all_edge_count": accept_all_graph.number_of_edges(),
                    **accept_all_operation_counts,
                }
            )
            if accept_all_graph_path.name != "updated_causal_graph_accept_all.json":
                accept_all_warnings.append(
                    f"Used fallback accept-all graph file: {accept_all_graph_path.name}."
                )
        verified_construction_steps = compute_verified_construction_steps(updated_graph)
        topology_metrics = compute_topology_metrics(updated_graph)
        hazard_consequence_type = load_hazard_consequence_type(case_folder)
        row.update(
            {
                "hazard_consequence_type": hazard_consequence_type,
                "structural_similarity": f"{similarity:.6f}",
                "graph_edit_distance": f"{graph_edit_distance:.6f}" if graph_edit_distance is not None else "",
                "normalized_graph_edit_distance": (
                    f"{normalized_graph_edit_distance:.6f}"
                    if normalized_graph_edit_distance is not None
                    else ""
                ),
                "graph_edit_similarity": f"{graph_edit_similarity:.6f}" if graph_edit_similarity is not None else "",
                **operation_counts,
                **accept_all_metrics,
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
                    + accept_all_warnings
                    + ([] if compute_ged else ["Skipped GED-based metrics."])
                    + (
                        []
                        if compute_ged or not compute_ged_operation_counts
                        else ["Skipped GED operation counts because GED was disabled."]
                    )
                ),
            }
        )
    except Exception as exc:
        row["warnings"] = f"{type(exc).__name__}: {exc}"

    return row


def evaluate_case_with_timing(
    case_folder: Path,
    parent_dir: Path,
    compute_ged: bool = True,
    compute_ged_operation_counts: bool = True,
    ged_algorithm: str = GED_ALGORITHM_EXACT,
    ged_timeout_seconds: float | None = None,
) -> Tuple[Dict[str, Any], float]:
    """Evaluate one case and return both the row and elapsed seconds."""
    started_at = time.perf_counter()
    row = evaluate_case(
        case_folder,
        parent_dir,
        compute_ged,
        compute_ged_operation_counts,
        ged_algorithm=ged_algorithm,
        ged_timeout_seconds=ged_timeout_seconds,
    )
    elapsed_seconds = time.perf_counter() - started_at
    return row, elapsed_seconds


def write_csv(path: Path, fieldnames: List[str], rows: List[Dict[str, Any]]) -> None:
    """Write rows to a CSV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames, extrasaction="ignore")
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
        ged_node_insertion_values = collect_numeric_values(success_rows, "ged_node_insertion_count")
        ged_node_deletion_values = collect_numeric_values(success_rows, "ged_node_deletion_count")
        ged_node_substitution_values = collect_numeric_values(success_rows, "ged_node_substitution_count")
        ged_edge_insertion_values = collect_numeric_values(success_rows, "ged_edge_insertion_count")
        ged_edge_deletion_values = collect_numeric_values(success_rows, "ged_edge_deletion_count")
        ged_edge_substitution_values = collect_numeric_values(success_rows, "ged_edge_substitution_count")
        ged_node_insertion_values_accept_all = collect_numeric_values(
            success_rows, "ged_node_insertion_count_accept_all_vs_updated"
        )
        ged_node_deletion_values_accept_all = collect_numeric_values(
            success_rows, "ged_node_deletion_count_accept_all_vs_updated"
        )
        ged_node_substitution_values_accept_all = collect_numeric_values(
            success_rows, "ged_node_substitution_count_accept_all_vs_updated"
        )
        ged_edge_insertion_values_accept_all = collect_numeric_values(
            success_rows, "ged_edge_insertion_count_accept_all_vs_updated"
        )
        ged_edge_deletion_values_accept_all = collect_numeric_values(
            success_rows, "ged_edge_deletion_count_accept_all_vs_updated"
        )
        ged_edge_substitution_values_accept_all = collect_numeric_values(
            success_rows, "ged_edge_substitution_count_accept_all_vs_updated"
        )

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
                    collect_numeric_values(success_rows, "graph_edit_distance")
                ),
                "mean_normalized_graph_edit_distance": mean_or_blank(
                    collect_numeric_values(success_rows, "normalized_graph_edit_distance")
                ),
                "mean_graph_edit_similarity": mean_or_blank(
                    collect_numeric_values(success_rows, "graph_edit_similarity")
                ),
                "mean_structural_similarity_accept_all_vs_updated": mean_or_blank(
                    collect_numeric_values(success_rows, "structural_similarity_accept_all_vs_updated")
                ),
                "mean_graph_edit_distance_accept_all_vs_updated": mean_or_blank(
                    collect_numeric_values(success_rows, "graph_edit_distance_accept_all_vs_updated")
                ),
                "mean_normalized_graph_edit_distance_accept_all_vs_updated": mean_or_blank(
                    collect_numeric_values(success_rows, "normalized_graph_edit_distance_accept_all_vs_updated")
                ),
                "mean_graph_edit_similarity_accept_all_vs_updated": mean_or_blank(
                    collect_numeric_values(success_rows, "graph_edit_similarity_accept_all_vs_updated")
                ),
                "mean_generated_node_count": mean_or_blank(
                    [float(row["generated_node_count"]) for row in success_rows]
                ),
                "mean_accept_all_node_count": mean_or_blank(
                    collect_numeric_values(success_rows, "accept_all_node_count")
                ),
                "mean_updated_node_count": mean_or_blank(
                    [float(row["updated_node_count"]) for row in success_rows]
                ),
                "mean_generated_edge_count": mean_or_blank(
                    [float(row["generated_edge_count"]) for row in success_rows]
                ),
                "mean_accept_all_edge_count": mean_or_blank(
                    collect_numeric_values(success_rows, "accept_all_edge_count")
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
                "total_ged_node_insertion_count": sum_or_zero(ged_node_insertion_values),
                "total_ged_node_deletion_count": sum_or_zero(ged_node_deletion_values),
                "total_ged_node_substitution_count": sum_or_zero(ged_node_substitution_values),
                "total_ged_edge_insertion_count": sum_or_zero(ged_edge_insertion_values),
                "total_ged_edge_deletion_count": sum_or_zero(ged_edge_deletion_values),
                "total_ged_edge_substitution_count": sum_or_zero(ged_edge_substitution_values),
                "total_ged_node_insertion_count_accept_all_vs_updated": sum_or_zero(
                    ged_node_insertion_values_accept_all
                ),
                "total_ged_node_deletion_count_accept_all_vs_updated": sum_or_zero(
                    ged_node_deletion_values_accept_all
                ),
                "total_ged_node_substitution_count_accept_all_vs_updated": sum_or_zero(
                    ged_node_substitution_values_accept_all
                ),
                "total_ged_edge_insertion_count_accept_all_vs_updated": sum_or_zero(
                    ged_edge_insertion_values_accept_all
                ),
                "total_ged_edge_deletion_count_accept_all_vs_updated": sum_or_zero(
                    ged_edge_deletion_values_accept_all
                ),
                "total_ged_edge_substitution_count_accept_all_vs_updated": sum_or_zero(
                    ged_edge_substitution_values_accept_all
                ),
                "mean_ged_node_insertion_count": mean_or_blank(ged_node_insertion_values),
                "mean_ged_node_deletion_count": mean_or_blank(ged_node_deletion_values),
                "mean_ged_node_substitution_count": mean_or_blank(ged_node_substitution_values),
                "mean_ged_edge_insertion_count": mean_or_blank(ged_edge_insertion_values),
                "mean_ged_edge_deletion_count": mean_or_blank(ged_edge_deletion_values),
                "mean_ged_edge_substitution_count": mean_or_blank(ged_edge_substitution_values),
                "mean_ged_node_insertion_count_accept_all_vs_updated": mean_or_blank(
                    ged_node_insertion_values_accept_all
                ),
                "mean_ged_node_deletion_count_accept_all_vs_updated": mean_or_blank(
                    ged_node_deletion_values_accept_all
                ),
                "mean_ged_node_substitution_count_accept_all_vs_updated": mean_or_blank(
                    ged_node_substitution_values_accept_all
                ),
                "mean_ged_edge_insertion_count_accept_all_vs_updated": mean_or_blank(
                    ged_edge_insertion_values_accept_all
                ),
                "mean_ged_edge_deletion_count_accept_all_vs_updated": mean_or_blank(
                    ged_edge_deletion_values_accept_all
                ),
                "mean_ged_edge_substitution_count_accept_all_vs_updated": mean_or_blank(
                    ged_edge_substitution_values_accept_all
                ),
            }
        )

    return batch_rows


def build_overall_summary(case_rows: List[Dict[str, Any]], batch_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build a single-row overall summary table."""
    success_rows = [row for row in case_rows if row["status"] == "ok"]
    ged_node_insertion_values = collect_numeric_values(success_rows, "ged_node_insertion_count")
    ged_node_deletion_values = collect_numeric_values(success_rows, "ged_node_deletion_count")
    ged_node_substitution_values = collect_numeric_values(success_rows, "ged_node_substitution_count")
    ged_edge_insertion_values = collect_numeric_values(success_rows, "ged_edge_insertion_count")
    ged_edge_deletion_values = collect_numeric_values(success_rows, "ged_edge_deletion_count")
    ged_edge_substitution_values = collect_numeric_values(success_rows, "ged_edge_substitution_count")
    ged_node_insertion_values_accept_all = collect_numeric_values(
        success_rows, "ged_node_insertion_count_accept_all_vs_updated"
    )
    ged_node_deletion_values_accept_all = collect_numeric_values(
        success_rows, "ged_node_deletion_count_accept_all_vs_updated"
    )
    ged_node_substitution_values_accept_all = collect_numeric_values(
        success_rows, "ged_node_substitution_count_accept_all_vs_updated"
    )
    ged_edge_insertion_values_accept_all = collect_numeric_values(
        success_rows, "ged_edge_insertion_count_accept_all_vs_updated"
    )
    ged_edge_deletion_values_accept_all = collect_numeric_values(
        success_rows, "ged_edge_deletion_count_accept_all_vs_updated"
    )
    ged_edge_substitution_values_accept_all = collect_numeric_values(
        success_rows, "ged_edge_substitution_count_accept_all_vs_updated"
    )
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
                collect_numeric_values(success_rows, "graph_edit_distance")
            ),
            "overall_mean_normalized_graph_edit_distance": mean_or_blank(
                collect_numeric_values(success_rows, "normalized_graph_edit_distance")
            ),
            "overall_mean_graph_edit_similarity": mean_or_blank(
                collect_numeric_values(success_rows, "graph_edit_similarity")
            ),
            "overall_mean_structural_similarity_accept_all_vs_updated": mean_or_blank(
                collect_numeric_values(success_rows, "structural_similarity_accept_all_vs_updated")
            ),
            "overall_mean_graph_edit_distance_accept_all_vs_updated": mean_or_blank(
                collect_numeric_values(success_rows, "graph_edit_distance_accept_all_vs_updated")
            ),
            "overall_mean_normalized_graph_edit_distance_accept_all_vs_updated": mean_or_blank(
                collect_numeric_values(success_rows, "normalized_graph_edit_distance_accept_all_vs_updated")
            ),
            "overall_mean_graph_edit_similarity_accept_all_vs_updated": mean_or_blank(
                collect_numeric_values(success_rows, "graph_edit_similarity_accept_all_vs_updated")
            ),
            "overall_mean_generated_node_count": mean_or_blank(
                [float(row["generated_node_count"]) for row in success_rows]
            ),
            "overall_mean_accept_all_node_count": mean_or_blank(
                collect_numeric_values(success_rows, "accept_all_node_count")
            ),
            "overall_mean_updated_node_count": mean_or_blank(
                [float(row["updated_node_count"]) for row in success_rows]
            ),
            "overall_mean_generated_edge_count": mean_or_blank(
                [float(row["generated_edge_count"]) for row in success_rows]
            ),
            "overall_mean_accept_all_edge_count": mean_or_blank(
                collect_numeric_values(success_rows, "accept_all_edge_count")
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
            "overall_total_ged_node_insertion_count": sum_or_zero(ged_node_insertion_values),
            "overall_total_ged_node_deletion_count": sum_or_zero(ged_node_deletion_values),
            "overall_total_ged_node_substitution_count": sum_or_zero(ged_node_substitution_values),
            "overall_total_ged_edge_insertion_count": sum_or_zero(ged_edge_insertion_values),
            "overall_total_ged_edge_deletion_count": sum_or_zero(ged_edge_deletion_values),
            "overall_total_ged_edge_substitution_count": sum_or_zero(ged_edge_substitution_values),
            "overall_total_ged_node_insertion_count_accept_all_vs_updated": sum_or_zero(
                ged_node_insertion_values_accept_all
            ),
            "overall_total_ged_node_deletion_count_accept_all_vs_updated": sum_or_zero(
                ged_node_deletion_values_accept_all
            ),
            "overall_total_ged_node_substitution_count_accept_all_vs_updated": sum_or_zero(
                ged_node_substitution_values_accept_all
            ),
            "overall_total_ged_edge_insertion_count_accept_all_vs_updated": sum_or_zero(
                ged_edge_insertion_values_accept_all
            ),
            "overall_total_ged_edge_deletion_count_accept_all_vs_updated": sum_or_zero(
                ged_edge_deletion_values_accept_all
            ),
            "overall_total_ged_edge_substitution_count_accept_all_vs_updated": sum_or_zero(
                ged_edge_substitution_values_accept_all
            ),
            "overall_mean_ged_node_insertion_count": mean_or_blank(ged_node_insertion_values),
            "overall_mean_ged_node_deletion_count": mean_or_blank(ged_node_deletion_values),
            "overall_mean_ged_node_substitution_count": mean_or_blank(ged_node_substitution_values),
            "overall_mean_ged_edge_insertion_count": mean_or_blank(ged_edge_insertion_values),
            "overall_mean_ged_edge_deletion_count": mean_or_blank(ged_edge_deletion_values),
            "overall_mean_ged_edge_substitution_count": mean_or_blank(ged_edge_substitution_values),
            "overall_mean_ged_node_insertion_count_accept_all_vs_updated": mean_or_blank(
                ged_node_insertion_values_accept_all
            ),
            "overall_mean_ged_node_deletion_count_accept_all_vs_updated": mean_or_blank(
                ged_node_deletion_values_accept_all
            ),
            "overall_mean_ged_node_substitution_count_accept_all_vs_updated": mean_or_blank(
                ged_node_substitution_values_accept_all
            ),
            "overall_mean_ged_edge_insertion_count_accept_all_vs_updated": mean_or_blank(
                ged_edge_insertion_values_accept_all
            ),
            "overall_mean_ged_edge_deletion_count_accept_all_vs_updated": mean_or_blank(
                ged_edge_deletion_values_accept_all
            ),
            "overall_mean_ged_edge_substitution_count_accept_all_vs_updated": mean_or_blank(
                ged_edge_substitution_values_accept_all
            ),
        }
    ]


def resolve_worker_count(requested_workers: int | None, total_cases: int) -> int:
    """Choose a safe worker count for the current run."""
    if total_cases <= 0:
        return 1
    if requested_workers is not None:
        return max(1, min(requested_workers, total_cases))
    cpu_count = os.cpu_count() or 1
    # On Windows, importing scipy/sklearn/grakel in too many processes can
    # exhaust virtual memory/page file and crash the process pool.
    if os.name == "nt":
        cpu_count = min(cpu_count, 4)
    return max(1, min(cpu_count, total_cases))


def report_case_runtime_summary(
    case_rows: List[Dict[str, Any]],
    case_timings: List[Tuple[float, str, str, str]],
    total_elapsed_seconds: float,
) -> None:
    """Print overall runtime stats plus the slowest cases."""
    total_cases = len(case_rows)
    success_rows = [row for row in case_rows if row["status"] == "ok"]
    failed_rows = [row for row in case_rows if row["status"] != "ok"]
    overall_cases_per_second = total_cases / total_elapsed_seconds if total_elapsed_seconds > 0 else 0.0
    average_case_seconds = total_elapsed_seconds / total_cases if total_cases > 0 else 0.0
    print(
        "Evaluation runtime: "
        f"total={total_elapsed_seconds:.2f}s, "
        f"avg_case={average_case_seconds:.2f}s, "
        f"throughput={overall_cases_per_second:.2f} case/s, "
        f"ok={len(success_rows)}, fail={len(failed_rows)}"
    )

    for rank, (elapsed_seconds, batch_id, case_id, status) in enumerate(
        sorted(case_timings, reverse=True)[: min(5, len(case_timings))],
        start=1,
    ):
        print(
            f"Slow case #{rank}: batch={batch_id}, case={case_id}, "
            f"status={status}, elapsed={elapsed_seconds:.2f}s"
        )


def evaluate_cases_with_progress(
    case_folders: List[Path],
    parent_dir: Path,
    workers: int | None = None,
    compute_ged: bool = True,
    compute_ged_operation_counts: bool = True,
    show_progress: bool = True,
    ged_algorithm: str = GED_ALGORITHM_EXACT,
    ged_timeout_seconds: float | None = None,
) -> List[Dict[str, Any]]:
    """Evaluate all cases with a progress bar and runtime summary."""
    case_rows: List[Dict[str, Any]] = []
    case_timings: List[Tuple[float, str, str, str]] = []
    total_cases = len(case_folders)
    run_started_at = time.perf_counter()
    worker_count = resolve_worker_count(workers, total_cases)
    print(f"Evaluating {total_cases} case(s) with {worker_count} worker(s).")

    progress_bar = tqdm(
        total=total_cases,
        desc="Evaluating cases",
        unit="case",
        dynamic_ncols=True,
        disable=not show_progress,
    )
    if worker_count == 1:
        for index, folder in enumerate(case_folders, start=1):
            row, elapsed_seconds = evaluate_case_with_timing(
                folder,
                parent_dir,
                compute_ged,
                compute_ged_operation_counts,
                ged_algorithm=ged_algorithm,
                ged_timeout_seconds=ged_timeout_seconds,
            )
            case_rows.append(row)
            case_timings.append(
                (
                    elapsed_seconds,
                    str(row.get("batch_id", "")),
                    str(row.get("case_id", "")),
                    str(row.get("status", "")),
                )
            )
            total_elapsed_seconds = time.perf_counter() - run_started_at
            average_case_seconds = total_elapsed_seconds / index if index else 0.0
            cases_per_second = index / total_elapsed_seconds if total_elapsed_seconds > 0 else 0.0
            remaining_cases = total_cases - index
            eta_seconds = remaining_cases * average_case_seconds
            progress_bar.update(1)
            progress_bar.set_postfix(
                avg_s=f"{average_case_seconds:.2f}",
                last_s=f"{elapsed_seconds:.2f}",
                case_s=f"{cases_per_second:.2f}",
                eta_s=f"{eta_seconds:.0f}",
                refresh=False,
            )
    else:
        ordered_rows: List[Dict[str, Any] | None] = [None] * total_cases
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            futures = {}
            future_meta: Dict[Any, Tuple[int, Path, float]] = {}
            for index, folder in enumerate(case_folders):
                future = executor.submit(
                    evaluate_case_with_timing,
                    folder,
                    parent_dir,
                    compute_ged,
                    compute_ged_operation_counts,
                    ged_algorithm,
                    ged_timeout_seconds,
                )
                futures[future] = index
                future_meta[future] = (index, folder, time.perf_counter())
            completed_count = 0
            pending_futures = set(futures)
            last_heartbeat_at = 0.0
            while pending_futures:
                done_futures, pending_futures = wait(
                    pending_futures,
                    timeout=1.0,
                    return_when=FIRST_COMPLETED,
                )

                if done_futures:
                    for future in done_futures:
                        index = futures[future]
                        row, elapsed_seconds = future.result()
                        ordered_rows[index] = row
                        case_timings.append(
                            (
                                elapsed_seconds,
                                str(row.get("batch_id", "")),
                                str(row.get("case_id", "")),
                                str(row.get("status", "")),
                            )
                        )
                        completed_count += 1
                        total_elapsed_seconds = time.perf_counter() - run_started_at
                        average_case_seconds = total_elapsed_seconds / completed_count if completed_count else 0.0
                        cases_per_second = completed_count / total_elapsed_seconds if total_elapsed_seconds > 0 else 0.0
                        remaining_cases = total_cases - completed_count
                        eta_seconds = remaining_cases / cases_per_second if cases_per_second > 0 else 0.0
                        progress_bar.update(1)
                        progress_bar.set_postfix(
                            avg_s=f"{average_case_seconds:.2f}",
                            last_s=f"{elapsed_seconds:.2f}",
                            case_s=f"{cases_per_second:.2f}",
                            eta_s=f"{eta_seconds:.0f}",
                            running=len(pending_futures),
                            refresh=False,
                        )
                else:
                    now = time.perf_counter()
                    if now - last_heartbeat_at >= 1.0:
                        total_elapsed_seconds = now - run_started_at
                        cases_per_second = completed_count / total_elapsed_seconds if total_elapsed_seconds > 0 else 0.0
                        remaining_cases = total_cases - completed_count
                        eta_seconds = remaining_cases / cases_per_second if cases_per_second > 0 else 0.0
                        slowest_future = max(
                            pending_futures,
                            key=lambda item: now - future_meta[item][2],
                        )
                        _, slowest_folder, started_at = future_meta[slowest_future]
                        running_for_seconds = now - started_at
                        try:
                            relative_case = str(slowest_folder.relative_to(parent_dir))
                        except ValueError:
                            relative_case = slowest_folder.name
                        progress_bar.set_postfix(
                            case_s=f"{cases_per_second:.2f}",
                            eta_s=f"{eta_seconds:.0f}" if cases_per_second > 0 else "?",
                            running=len(pending_futures),
                            longest_s=f"{running_for_seconds:.1f}",
                            longest_case=relative_case,
                            refresh=True,
                        )
                        last_heartbeat_at = now
        case_rows = [row for row in ordered_rows if row is not None]

    progress_bar.close()
    total_elapsed_seconds = time.perf_counter() - run_started_at
    report_case_runtime_summary(case_rows, case_timings, total_elapsed_seconds)
    return case_rows


def main() -> Path:
    """Run the batch structural similarity evaluation pipeline."""
    args = parse_args()
    parent_dir = args.parent_dir
    output_dir = make_run_output_dir(args.output_dir)

    case_folders = find_case_folders(parent_dir)
    case_rows = evaluate_cases_with_progress(
        case_folders,
        parent_dir,
        args.workers,
        compute_ged=args.compute_ged,
        compute_ged_operation_counts=args.compute_ged_operation_counts,
        show_progress=args.show_progress,
        ged_algorithm=args.ged_algorithm,
        ged_timeout_seconds=args.ged_timeout,
    )
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
