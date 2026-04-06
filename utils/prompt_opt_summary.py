from __future__ import annotations

from typing import Any, Dict, List


NODE_GROUP_KEYS = (
    "hazard_consequence_node",
    "entity_nodes",
    "condition_nodes",
    "event_nodes",
)


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _flatten_nodes(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    nodes: List[Dict[str, Any]] = []
    for key in NODE_GROUP_KEYS:
        group = data.get(key, [])
        if isinstance(group, list):
            nodes.extend(group)
        elif isinstance(group, dict):
            nodes.append(group)
    return nodes


def _node_brief(node: Dict[str, Any]) -> str:
    label = _norm(node.get("label"))
    name = _norm(node.get("name"))
    node_id = _norm(node.get("node_id"))
    parts = [part for part in (node_id, label, name) if part]
    return " | ".join(parts)


def build_case_context(
    *,
    incident_description: str,
    identify_hazard_consequence_output: str,
    gold_graph: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "incident_description": incident_description,
        "identify_hazard_consequence_output": identify_hazard_consequence_output,
        "gold_graph": gold_graph,
    }


def summarize_scenario_output(current_output: Dict[str, Any], gold_target: Dict[str, Any]) -> Dict[str, Any]:
    current_nodes = _flatten_nodes(current_output)
    gold_nodes = _flatten_nodes(gold_target)
    current_ids = {str(node.get("node_id")) for node in current_nodes}
    gold_ids = {str(node.get("node_id")) for node in gold_nodes}

    return {
        "extra_nodes": [
            _node_brief(node) for node in current_nodes if str(node.get("node_id")) not in gold_ids
        ][:5],
        "missing_nodes": [
            _node_brief(node) for node in gold_nodes if str(node.get("node_id")) not in current_ids
        ][:5],
    }


def summarize_edge_output(current_output: Dict[str, Any], gold_graph: Dict[str, Any]) -> Dict[str, Any]:
    gold_nodes = {str(node.get("node_id")): node for node in _flatten_nodes(gold_graph)}
    current_edges = current_output.get("edges", [])
    gold_edges = gold_graph.get("edges", [])
    current_set = {
        (str(edge.get("source")), str(edge.get("relation")), str(edge.get("target")))
        for edge in current_edges
    }
    gold_set = {
        (str(edge.get("source")), str(edge.get("relation")), str(edge.get("target")))
        for edge in gold_edges
    }

    def edge_brief(edge: Dict[str, Any]) -> str:
        source = str(edge.get("source") or "")
        relation = str(edge.get("relation") or "")
        target = str(edge.get("target") or "")
        source_label = _norm(gold_nodes.get(source, {}).get("label"))
        target_label = _norm(gold_nodes.get(target, {}).get("label"))
        left = f"{source}:{source_label}" if source_label else source
        right = f"{target}:{target_label}" if target_label else target
        return f"{left} -[{relation}]-> {right}"

    current_by_id = {
        (str(edge.get("source")), str(edge.get("relation")), str(edge.get("target"))): edge
        for edge in current_edges
    }
    gold_by_id = {
        (str(edge.get("source")), str(edge.get("relation")), str(edge.get("target"))): edge
        for edge in gold_edges
    }

    return {
        "extra_edges": [edge_brief(current_by_id[key]) for key in sorted(current_set - gold_set)[:5]],
        "missing_edges": [edge_brief(gold_by_id[key]) for key in sorted(gold_set - current_set)[:5]],
    }


def compress_diff_summary(diff_summary: Dict[str, Any]) -> Dict[str, Any]:
    compressed: Dict[str, Any] = {}
    if "extra_nodes" in diff_summary:
        compressed["top_extra_nodes"] = [
            " | ".join(str(part) for part in item if part)
            for item in diff_summary.get("extra_nodes", [])[:5]
        ]
        compressed["top_missing_nodes"] = [
            " | ".join(str(part) for part in item if part)
            for item in diff_summary.get("missing_nodes", [])[:5]
        ]
    if "extra_edges_by_id" in diff_summary:
        compressed["top_extra_edges"] = [
            " | ".join(str(part) for part in item if part)
            for item in diff_summary.get("extra_edges_by_id", [])[:5]
        ]
        compressed["top_missing_edges"] = [
            " | ".join(str(part) for part in item if part)
            for item in diff_summary.get("missing_edges_by_id", [])[:5]
        ]
    compressed["notes"] = diff_summary.get("notes", [])
    return compressed
