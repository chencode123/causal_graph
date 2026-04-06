from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    import networkx as nx
except ImportError:  # pragma: no cover
    nx = None

try:
    from grakel import Graph, GraphKernel
except ImportError:  # pragma: no cover
    Graph = None
    GraphKernel = None


NODE_GROUP_KEYS = (
    "hazard_consequence_node",
    "entity_nodes",
    "condition_nodes",
    "event_nodes",
)


@dataclass
class RoundScore:
    round_index: int
    node_precision: float
    node_recall: float
    node_f1: float
    edge_precision: float
    edge_recall: float
    edge_f1: float
    overall_score: float
    structural_similarity: float | None
    graph_edit_distance: float | None
    normalized_graph_edit_distance: float | None
    graph_edit_similarity: float | None


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _flatten_nodes(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    nodes: List[Dict[str, Any]] = []
    for key in NODE_GROUP_KEYS:
        group = data.get(key, [])
        if isinstance(group, list):
            nodes.extend(group)
    return nodes


def _node_group(node: Dict[str, Any]) -> str:
    node_type = _norm(node.get("node_type"))
    if node_type:
        return node_type
    node_id = str(node.get("node_id") or "")
    if node_id.startswith("En"):
        return "entity"
    if node_id.startswith("C"):
        return "condition"
    if node_id.startswith("Ev"):
        return "event"
    if node_id.startswith("H"):
        return "hazardconsequence"
    return ""


def _node_sig(node: Dict[str, Any]) -> Tuple[str, str, str]:
    return (
        _norm(node.get("label")),
        _node_group(node),
        _norm(node.get("node_id")),
    )


def _f1(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _edge_sig(edge: Dict[str, Any], node_map: Dict[str, Dict[str, Any]]) -> Tuple[str, str, str, str, str]:
    source_id = str(edge.get("source") or "")
    target_id = str(edge.get("target") or "")
    source = node_map.get(source_id, {})
    target = node_map.get(target_id, {})
    return (
        _norm(source.get("label")),
        _norm(source_id),
        _norm(edge.get("relation")),
        _norm(target.get("label")),
        _norm(target_id),
    )


def _build_directed_graph(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]):
    if nx is None:
        return None
    graph = nx.DiGraph()
    for node in nodes:
        node_id = str(node.get("node_id") or "").strip()
        if not node_id:
            continue
        graph.add_node(node_id, label=str(node.get("label") or "").strip() or "UNKNOWN_LABEL")
    for edge in edges:
        source = str(edge.get("source") or "").strip()
        target = str(edge.get("target") or "").strip()
        if not source or not target:
            continue
        if not graph.has_node(source) or not graph.has_node(target):
            continue
        graph.add_edge(source, target)
    return graph


def _to_grakel_graph(graph):
    adjacency = {
        node: {neighbor: 1.0 for neighbor in graph.successors(node)}
        for node in graph.nodes()
    }
    node_labels = {node: graph.nodes[node].get("label", "UNKNOWN_LABEL") for node in graph.nodes()}
    return Graph(initialization_object=adjacency, node_labels=node_labels)


def _compute_structural_similarity(generated_graph, updated_graph) -> float | None:
    if GraphKernel is None:
        return None
    kernel = GraphKernel(
        kernel=[
            {"name": "weisfeiler_lehman", "n_iter": 2},
            {"name": "vertex_histogram"},
        ],
        normalize=True,
    )
    similarity_matrix = kernel.fit_transform(
        [_to_grakel_graph(generated_graph), _to_grakel_graph(updated_graph)]
    )
    return float(similarity_matrix[0, 1])


def _compute_graph_edit_metrics(generated_graph, updated_graph) -> Tuple[float | None, float | None, float | None]:
    if nx is None:
        return None, None, None
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


def score_case(case_dir: Path, round_index: int) -> RoundScore:
    generated = _read_json(case_dir / "causal_graph.json")
    updated = _read_json(case_dir / "updated_causal_graph.json")

    generated_nodes = _flatten_nodes(generated)
    updated_nodes = _flatten_nodes(updated)
    generated_node_set = {_node_sig(node) for node in generated_nodes}
    updated_node_set = {_node_sig(node) for node in updated_nodes}

    node_tp = len(generated_node_set & updated_node_set)
    node_precision = node_tp / len(generated_node_set) if generated_node_set else 0.0
    node_recall = node_tp / len(updated_node_set) if updated_node_set else 0.0
    node_f1 = _f1(node_precision, node_recall)

    generated_node_map = {str(node.get("node_id")): node for node in generated_nodes}
    updated_node_map = {str(node.get("node_id")): node for node in updated_nodes}
    generated_edge_set = {
        _edge_sig(edge, generated_node_map) for edge in generated.get("edges", [])
    }
    updated_edge_set = {
        _edge_sig(edge, updated_node_map) for edge in updated.get("edges", [])
    }

    edge_tp = len(generated_edge_set & updated_edge_set)
    edge_precision = edge_tp / len(generated_edge_set) if generated_edge_set else 0.0
    edge_recall = edge_tp / len(updated_edge_set) if updated_edge_set else 0.0
    edge_f1 = _f1(edge_precision, edge_recall)

    overall_score = (node_f1 + edge_f1) / 2
    generated_graph = _build_directed_graph(generated_nodes, generated.get("edges", []))
    updated_graph = _build_directed_graph(updated_nodes, updated.get("edges", []))
    if generated_graph is not None and updated_graph is not None:
        structural_similarity = _compute_structural_similarity(generated_graph, updated_graph)
        (
            graph_edit_distance,
            normalized_graph_edit_distance,
            graph_edit_similarity,
        ) = _compute_graph_edit_metrics(generated_graph, updated_graph)
    else:
        structural_similarity = None
        graph_edit_distance = None
        normalized_graph_edit_distance = None
        graph_edit_similarity = None
    return RoundScore(
        round_index=round_index,
        node_precision=node_precision,
        node_recall=node_recall,
        node_f1=node_f1,
        edge_precision=edge_precision,
        edge_recall=edge_recall,
        edge_f1=edge_f1,
        overall_score=overall_score,
        structural_similarity=structural_similarity,
        graph_edit_distance=graph_edit_distance,
        normalized_graph_edit_distance=normalized_graph_edit_distance,
        graph_edit_similarity=graph_edit_similarity,
    )


def write_score(path: Path, score: RoundScore) -> None:
    path.write_text(json.dumps(asdict(score), ensure_ascii=False, indent=2), encoding="utf-8")
