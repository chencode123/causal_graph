from __future__ import annotations

from typing import Any, Dict, List, Tuple


NODE_KEYS = (
    "hazard_consequence_node",
    "entity_nodes",
    "condition_nodes",
    "event_nodes",
)

MANIFESTATION_KEYWORDS = (
    "explosion",
    "overpressure",
    "blast",
    "rupture",
    "detonation",
    "flash fire",
    "jet fire",
    "pool fire",
)


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _flatten_nodes(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    nodes: List[Dict[str, Any]] = []
    for key in NODE_KEYS:
        group = data.get(key, [])
        if isinstance(group, list):
            nodes.extend(group)
        elif isinstance(group, dict):
            nodes.append(group)
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
    return (_norm(node.get("label")), _norm(node.get("name")), _node_group(node))


def summarize_scenario_diff(current_output: Dict[str, Any], gold_nodes: Dict[str, Any]) -> Dict[str, Any]:
    current_nodes = _flatten_nodes(current_output)
    gold_node_list = _flatten_nodes(gold_nodes)
    current_set = {_node_sig(node) for node in current_nodes}
    gold_set = {_node_sig(node) for node in gold_node_list}

    extra_nodes = sorted(current_set - gold_set)
    missing_nodes = sorted(gold_set - current_set)
    extra_event_count = max(
        0,
        sum(1 for node in current_nodes if _node_group(node) == "event")
        - sum(1 for node in gold_node_list if _node_group(node) == "event"),
    )
    manifestation_as_cause = 0
    notes: List[str] = []

    for node in current_nodes:
        if _node_group(node) != "event":
            continue
        text = " ".join(
            [
                str(node.get("name") or ""),
                str(node.get("evidence") or ""),
                str(node.get("explanation") or ""),
            ]
        ).lower()
        if any(keyword in text for keyword in MANIFESTATION_KEYWORDS):
            manifestation_as_cause += 1

    if manifestation_as_cause:
        notes.append("Event nodes include consequence-level manifestation wording.")
    if extra_event_count:
        notes.append("Current output has more event nodes than the gold nodes.")
    if extra_nodes:
        notes.append("Current output contains extra nodes not present in the gold nodes.")
    if missing_nodes:
        notes.append("Current output misses nodes that exist in the gold nodes.")

    return {
        "extra_nodes": extra_nodes,
        "missing_nodes": missing_nodes,
        "extra_event_count": extra_event_count,
        "manifestation_as_cause_count": manifestation_as_cause,
        "notes": notes,
    }


def summarize_edge_diff(current_output: Dict[str, Any], gold_graph: Dict[str, Any]) -> Dict[str, Any]:
    gold_nodes = _flatten_nodes(gold_graph)
    gold_node_map = {str(node.get("node_id")): node for node in gold_nodes}

    def edge_sig(edge: Dict[str, Any], node_map: Dict[str, Dict[str, Any]]) -> Tuple[str, str, str, str, str]:
        source = node_map.get(str(edge.get("source") or ""), {})
        target = node_map.get(str(edge.get("target") or ""), {})
        return (
            _norm(source.get("label")),
            _norm(source.get("name")),
            _norm(edge.get("relation")),
            _norm(target.get("label")),
            _norm(target.get("name")),
        )

    current_edges = current_output.get("edges", [])
    gold_edges = gold_graph.get("edges", [])

    current_set = {(_norm(edge.get("source")), _norm(edge.get("relation")), _norm(edge.get("target"))) for edge in current_edges}
    gold_set = {(_norm(edge.get("source")), _norm(edge.get("relation")), _norm(edge.get("target"))) for edge in gold_edges}

    gold_edge_sigs = {edge_sig(edge, gold_node_map) for edge in gold_edges}
    current_node_map = {str(node.get("node_id")): node for node in gold_nodes}
    current_edge_sigs = {edge_sig(edge, current_node_map) for edge in current_edges}

    has_misuse = 0
    manifestation_as_cause = 0
    notes: List[str] = []
    for edge in current_edges:
        relation = _norm(edge.get("relation"))
        source_node = gold_node_map.get(str(edge.get("source") or ""), {})
        target_node = gold_node_map.get(str(edge.get("target") or ""), {})
        source_group = _node_group(source_node)
        target_group = _node_group(target_node)
        if relation == "has" and not (source_group == "entity" and target_group == "condition"):
            has_misuse += 1
        if source_group == "event":
            text = " ".join(
                [
                    str(source_node.get("name") or ""),
                    str(source_node.get("evidence") or ""),
                    str(source_node.get("explanation") or ""),
                ]
            ).lower()
            if any(keyword in text for keyword in MANIFESTATION_KEYWORDS):
                manifestation_as_cause += 1

    if has_misuse:
        notes.append("Relation 'has' is used outside Entity -> Condition edges.")
    if manifestation_as_cause:
        notes.append("Event-like manifestations are used as upstream edge sources.")

    return {
        "extra_edges_by_id": sorted(current_set - gold_set),
        "missing_edges_by_id": sorted(gold_set - current_set),
        "extra_edges_by_semantics": sorted(current_edge_sigs - gold_edge_sigs),
        "missing_edges_by_semantics": sorted(gold_edge_sigs - current_edge_sigs),
        "has_relation_misuse_count": has_misuse,
        "manifestation_as_cause_count": manifestation_as_cause,
        "notes": notes,
    }
