from __future__ import annotations

import asyncio
import json
import os
import time
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Tuple

from openai import AsyncOpenAI, OpenAI
from tqdm import tqdm

import utils.prompt_manager as prompt_manager
from utils.causal_graph_interactive_pkg.causal_graph_interactive import (
    draw_causal_graph_interactive_from_json,
    draw_updated_causal_graph_interactive_from_json,
)
from utils.prompt_validator import assert_prompt_step_configuration_valid

from .io_utils import (
    extract_text_from_responses_body,
    get_response_dir,
    render_prompt,
    save_step_input_snapshot,
    write_text,
)
from .step_factory import Step, build_pipeline
from .step_registry import STEP_REGISTRY


def _mask(key: str | None) -> str:
    if not key:
        return "<None>"
    return key[:8] + "..." + key[-4:]


def _normalize_node_type(node_type: str) -> str:
    text = str(node_type or "").strip().lower()
    if text in {"hazardconsequence", "hazard_consequence"}:
        return "hazardconsequence"
    if text == "entity":
        return "entity"
    if text == "condition":
        return "condition"
    if text == "event":
        return "event"
    return text


def _node_type_to_prefix(node_type: str) -> str:
    normalized = _normalize_node_type(node_type)
    if normalized == "hazardconsequence":
        return "H"
    if normalized == "entity":
        return "En"
    if normalized == "condition":
        return "C"
    if normalized == "event":
        return "Ev"
    return "N"


def _flatten_graph_nodes(graph_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    nodes: List[Dict[str, Any]] = []
    for key in ("hazard_consequence_node", "entity_nodes", "condition_nodes", "event_nodes"):
        group = graph_data.get(key, [])
        if isinstance(group, dict):
            group = [group]
        if isinstance(group, list):
            nodes.extend(group)
    return nodes


def _build_node_maps(graph_data: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    nodes = _flatten_graph_nodes(graph_data)
    node_by_id = {
        str(node.get("node_id") or "").strip(): node
        for node in nodes
        if str(node.get("node_id") or "").strip()
    }
    return nodes, node_by_id


def _next_node_id(existing_ids: List[str], node_type: str) -> str:
    prefix = _node_type_to_prefix(node_type)
    max_index = 0
    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    for node_id in existing_ids:
        match = pattern.match(node_id)
        if match:
            max_index = max(max_index, int(match.group(1)))
    return f"{prefix}{max_index + 1}"


def _parse_field_from_suggested_state(suggested_state: Any, field: str) -> str:
    if isinstance(suggested_state, dict):
        value = suggested_state.get(field)
        if value is None and field == "node_type":
            value = suggested_state.get("type")
        return str(value or "").strip()

    text = str(suggested_state or "").strip()
    if not text:
        return ""
    match = re.search(
        rf"(?im)(?:^|[;\n])\s*{re.escape(field)}\s*[:=]\s*(.+?)(?=\s*(?:[;\n]|$))",
        text,
    )
    return match.group(1).strip() if match else ""


def _resolve_suggested_state_value(
    suggested_state: Any,
    *,
    preferred_fields: List[str],
    current_value: str,
) -> str:
    if isinstance(suggested_state, dict):
        for field in preferred_fields:
            value = suggested_state.get(field)
            if value is None and field == "node_type":
                value = suggested_state.get("type")
            parsed = str(value or "").strip()
            if not parsed:
                continue
            lowered = parsed.lower()
            if lowered in {"retained", "keep", "unchanged", "no change", "same"}:
                return current_value
            return parsed
        return current_value

    text = str(suggested_state or "").strip()
    if not text:
        return current_value

    for field in preferred_fields:
        parsed = _parse_field_from_suggested_state(text, field)
        if parsed:
            lowered = parsed.strip().lower()
            if lowered in {"retained", "keep", "unchanged", "no change", "same"}:
                return current_value
            return parsed

    lowered_text = text.lower()
    if "label" in preferred_fields:
        match = re.search(
            r"(?i)\brelabel\b.*?\bas\s+\"?([^\".;\n]+)\"?",
            text,
        )
        if match:
            return match.group(1).strip()
    if "name" in preferred_fields:
        match = re.search(
            r'(?is)^\s*(?:name\s*[-=]>\s*)?(?:[A-Za-z]+\d+\s*)?=\s*[^:\n]+:\s*"([^"]+)"\s*$',
            text,
        )
        if match:
            return match.group(1).strip()
        match = re.search(
            r"(?i)\brename\b.*?\b(?:to|as)\b\s+\"?([^\".;\n]+)\"?",
            text,
        )
        if match:
            return match.group(1).strip()
    if "node_type" in preferred_fields or "type" in preferred_fields:
        match = re.search(
            r"(?i)\b(?:retype|change\s+the\s+type|change\s+type)\b.*?\bas\s+\"?([^\".;\n]+)\"?",
            text,
        )
        if match:
            return match.group(1).strip()

    if lowered_text in {"retained", "keep", "unchanged", "no change", "same"}:
        return current_value
    return text


def _group_key_for_node_type(node_type: str) -> str:
    normalized = _normalize_node_type(node_type)
    if normalized == "hazardconsequence":
        return "hazard_consequence_node"
    if normalized == "entity":
        return "entity_nodes"
    if normalized == "condition":
        return "condition_nodes"
    return "event_nodes"


def _has_edge(edges: List[Dict[str, Any]], source: str, target: str, relation: str) -> bool:
    for edge in edges:
        edge_source = str(edge.get("source") or "").strip()
        edge_target = str(edge.get("target") or "").strip()
        edge_relation = str(edge.get("relation") or edge.get("label") or "").strip()
        if edge_source == source and edge_target == target and edge_relation == relation:
            return True
    return False


def _has_alternative_directed_path(
    *,
    source: str,
    target: str,
    edges: List[Dict[str, Any]],
    skipped_index: int,
) -> bool:
    adjacency: Dict[str, List[str]] = {}
    for index, edge in enumerate(edges):
        if index == skipped_index:
            continue
        edge_source = str(edge.get("source") or "").strip()
        edge_target = str(edge.get("target") or "").strip()
        if not edge_source or not edge_target:
            continue
        adjacency.setdefault(edge_source, []).append(edge_target)

    stack = list(adjacency.get(source, []))
    visited = {source}
    while stack:
        current = stack.pop()
        if current == target:
            return True
        if current in visited:
            continue
        visited.add(current)
        stack.extend(adjacency.get(current, []))
    return False


def _remove_shortcut_edges(edges: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    pruned: List[Dict[str, Any]] = []
    for index, edge in enumerate(edges):
        source = str(edge.get("source") or "").strip()
        target = str(edge.get("target") or "").strip()
        if not source or not target:
            continue
        if _has_alternative_directed_path(
            source=source,
            target=target,
            edges=edges,
            skipped_index=index,
        ):
            continue
        pruned.append(edge)
    return pruned


def _apply_review_accept_all(
    causal_graph_data: Dict[str, Any],
    review_data: Dict[str, Any],
    *,
    remove_shortcut_edges: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    updated = deepcopy(causal_graph_data)
    updated.setdefault("edges", [])
    for key in ("hazard_consequence_node", "entity_nodes", "condition_nodes", "event_nodes"):
        updated.setdefault(key, [])

    nodes, node_by_id = _build_node_maps(updated)
    edges: List[Dict[str, Any]] = list(updated.get("edges", []))
    accepted_decisions: Dict[str, str] = {}
    deleted_nodes: List[str] = []
    deleted_edges: List[Dict[str, str]] = []
    generated_edge_keys_by_node_addition: Dict[str, List[str]] = {}

    node_updates = review_data.get("node_updates", []) if isinstance(review_data.get("node_updates"), list) else []
    for index, item in enumerate(node_updates):
        key = f"node_update_{index}"
        target_id = str(item.get("target_id") or "").strip()
        node = node_by_id.get(target_id)
        if node is None:
            continue
        change_type = str(item.get("change_type") or "").strip().lower()
        suggested_state = item.get("suggested_state") or ""
        if change_type == "rename":
            node["name"] = _resolve_suggested_state_value(
                suggested_state,
                preferred_fields=["name"],
                current_value=str(node.get("name", "")),
            )
        elif change_type == "relabel":
            node["label"] = _resolve_suggested_state_value(
                suggested_state,
                preferred_fields=["label"],
                current_value=str(node.get("label", "")),
            )
        elif change_type == "retype":
            node["node_type"] = _resolve_suggested_state_value(
                suggested_state,
                preferred_fields=["node_type", "type"],
                current_value=str(node.get("node_type", "")),
            )
        elif change_type == "update_evidence":
            node["evidence"] = (
                _parse_field_from_suggested_state(suggested_state, "evidence")
                or (suggested_state if isinstance(suggested_state, str) else "")
                or node.get("evidence", "")
            )
        elif change_type == "update_explanation":
            node["explanation"] = (
                _parse_field_from_suggested_state(suggested_state, "explanation")
                or (suggested_state if isinstance(suggested_state, str) else "")
                or node.get("explanation", "")
            )
        elif change_type == "clarify_role":
            node["explanation"] = (
                suggested_state if isinstance(suggested_state, str) else ""
            ) or node.get("explanation", "")
        accepted_decisions[key] = "accepted"

    node_additions = review_data.get("node_additions", []) if isinstance(review_data.get("node_additions"), list) else []
    for index, item in enumerate(node_additions):
        key = f"node_addition_{index}"
        suggested_label = str(item.get("suggested_label") or "").strip()
        suggested_name = str(item.get("suggested_name") or "").strip()
        suggested_node_type = str(item.get("suggested_node_type") or "").strip()
        if not (suggested_label and suggested_name and suggested_node_type):
            continue
        existing_ids = list(node_by_id.keys())
        new_node_id = _next_node_id(existing_ids, suggested_node_type)
        new_node = {
            "label": suggested_label,
            "name": suggested_name,
            "node_id": new_node_id,
            "node_type": suggested_node_type,
            "evidence": str(item.get("evidence") or "").strip(),
            "explanation": str(item.get("reason") or item.get("explanation") or "").strip(),
            "source": "updated_graph_accept_all",
        }
        updated[_group_key_for_node_type(suggested_node_type)].append(new_node)
        node_by_id[new_node_id] = new_node
        generated_edge_keys: List[str] = []

        upstream_links = item.get("suggested_upstream_links", []) if isinstance(item.get("suggested_upstream_links"), list) else []
        for link in upstream_links:
            source_id = str(link.get("source") or "").strip()
            relation = str(link.get("relation") or "enables").strip()
            if not source_id or source_id not in node_by_id:
                continue
            if _has_edge(edges, source_id, new_node_id, relation):
                continue
            edges.append(
                {
                    "source": source_id,
                    "target": new_node_id,
                    "relation": relation,
                    "evidence": str(link.get("evidence") or "").strip(),
                    "explanation": str(link.get("explanation") or link.get("reason") or "").strip(),
                }
            )
            generated_edge_keys.append(f"{source_id}|{new_node_id}|{relation}")

        downstream_links = item.get("suggested_downstream_links", []) if isinstance(item.get("suggested_downstream_links"), list) else []
        for link in downstream_links:
            target_id = str(link.get("target") or "").strip()
            relation = str(link.get("relation") or "enables").strip()
            if not target_id or target_id not in node_by_id:
                continue
            if _has_edge(edges, new_node_id, target_id, relation):
                continue
            edges.append(
                {
                    "source": new_node_id,
                    "target": target_id,
                    "relation": relation,
                    "evidence": str(link.get("evidence") or "").strip(),
                    "explanation": str(link.get("explanation") or link.get("reason") or "").strip(),
                }
            )
            generated_edge_keys.append(f"{new_node_id}|{target_id}|{relation}")

        generated_edge_keys_by_node_addition[key] = generated_edge_keys
        accepted_decisions[key] = "accepted"

    node_deletions = review_data.get("node_deletions", []) if isinstance(review_data.get("node_deletions"), list) else []
    for index, item in enumerate(node_deletions):
        key = f"node_deletion_{index}"
        target_id = str(item.get("target_id") or "").strip()
        if not target_id:
            continue
        if target_id in node_by_id:
            deleted_nodes.append(target_id)
        accepted_decisions[key] = "accepted"

    edge_additions = review_data.get("edge_additions", []) if isinstance(review_data.get("edge_additions"), list) else []
    covered_edge_keys = {
        edge_key
        for edge_keys in generated_edge_keys_by_node_addition.values()
        for edge_key in edge_keys
    }
    for index, item in enumerate(edge_additions):
        key = f"edge_addition_{index}"
        source = str(item.get("source") or "").strip()
        target = str(item.get("target") or "").strip()
        relation = str(item.get("relation") or "").strip()
        edge_key = f"{source}|{target}|{relation}"
        if source and target and relation and source in node_by_id and target in node_by_id and edge_key not in covered_edge_keys:
            if not _has_edge(edges, source, target, relation):
                edges.append(
                    {
                        "source": source,
                        "target": target,
                        "relation": relation,
                        "evidence": str(item.get("evidence") or "").strip(),
                        "explanation": str(item.get("explanation") or item.get("reason") or "").strip(),
                    }
                )
        accepted_decisions[key] = "accepted"

    edge_deletions = review_data.get("edge_deletions", []) if isinstance(review_data.get("edge_deletions"), list) else []
    edge_delete_set = set()
    for index, item in enumerate(edge_deletions):
        key = f"edge_deletion_{index}"
        source = str(item.get("source") or "").strip()
        target = str(item.get("target") or "").strip()
        relation = str(item.get("relation") or "").strip()
        if source and target and relation:
            edge_delete_set.add((source, target, relation))
            deleted_edges.append({"source": source, "target": target, "relation": relation})
        accepted_decisions[key] = "accepted"

    edge_updates = review_data.get("edge_updates", []) if isinstance(review_data.get("edge_updates"), list) else []
    for index, item in enumerate(edge_updates):
        key = f"edge_update_{index}"
        source = str(item.get("source") or "").strip()
        target = str(item.get("target") or "").strip()
        current_relation = str(item.get("current_relation") or "").strip()
        suggested_relation = str(item.get("suggested_relation") or "").strip()
        for edge in edges:
            edge_source = str(edge.get("source") or "").strip()
            edge_target = str(edge.get("target") or "").strip()
            edge_relation = str(edge.get("relation") or edge.get("label") or "").strip()
            if edge_source == source and edge_target == target and edge_relation == current_relation:
                if suggested_relation:
                    edge["relation"] = suggested_relation
                    edge["label"] = suggested_relation
                if str(item.get("evidence") or "").strip():
                    edge["evidence"] = str(item.get("evidence") or "").strip()
                if str(item.get("explanation") or item.get("reason") or "").strip():
                    edge["explanation"] = str(item.get("explanation") or item.get("reason") or "").strip()
                break
        accepted_decisions[key] = "accepted"

    deleted_node_set = set(deleted_nodes)
    filtered_edges: List[Dict[str, Any]] = []
    for edge in edges:
        source = str(edge.get("source") or "").strip()
        target = str(edge.get("target") or "").strip()
        relation = str(edge.get("relation") or edge.get("label") or "").strip()
        if source in deleted_node_set or target in deleted_node_set:
            continue
        if (source, target, relation) in edge_delete_set:
            continue
        filtered_edges.append(edge)
    if remove_shortcut_edges:
        filtered_edges = _remove_shortcut_edges(filtered_edges)

    for group_key in ("hazard_consequence_node", "entity_nodes", "condition_nodes", "event_nodes"):
        group_nodes = updated.get(group_key, [])
        if not isinstance(group_nodes, list):
            updated[group_key] = []
            continue
        updated[group_key] = [
            node
            for node in group_nodes
            if str(node.get("node_id") or "").strip() not in deleted_node_set
        ]
    updated["edges"] = filtered_edges

    review_state = {
        "review_decisions": accepted_decisions,
        "deleted_nodes": deleted_nodes,
        "deleted_edges": deleted_edges,
        "deleted_visible": True,
    }
    return updated, review_state


def resolve_review_output_path(folder: Path) -> Path | None:
    candidates = (
        folder / "graph_revision_planning_output.json",
        folder / "review_causal_graph_output.json",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def generate_accept_all_review_outputs(
    *,
    folder: Path,
    accident_scenario_schema_path: Path,
    remove_shortcut_edges: bool = True,
) -> None:
    causal_graph_path = folder / "causal_graph.json"
    review_path = resolve_review_output_path(folder)
    if not causal_graph_path.exists() or review_path is None:
        return

    with causal_graph_path.open("r", encoding="utf-8") as fp:
        causal_graph_data = json.load(fp)
    with review_path.open("r", encoding="utf-8") as fp:
        review_data = json.load(fp)

    if not isinstance(causal_graph_data, dict) or not isinstance(review_data, dict):
        return

    updated_graph, review_state = _apply_review_accept_all(
        causal_graph_data,
        review_data,
        remove_shortcut_edges=remove_shortcut_edges,
    )

    updated_graph_path = folder / "updated_causal_graph_accept_all.json"
    review_state_path = folder / "updated_causal_graph_review_state_accept_all.json"
    updated_html_path = folder / "updated_causal_graph_accept_all.html"

    write_text(updated_graph_path, json.dumps(updated_graph, ensure_ascii=False, indent=2))
    write_text(review_state_path, json.dumps(review_state, ensure_ascii=False, indent=2))

    draw_updated_causal_graph_interactive_from_json(
        updated_causal_graph=updated_graph_path,
        save_path=updated_html_path,
        accident_scenario_schema=accident_scenario_schema_path,
        review_causal_graph=review_path,
        revision_decisions=review_state_path,

        case_id=folder.name,
    )


def _build_causal_graph_json(
    *,
    identify_accident_scenario_path: Path,
    causal_edge_linking_path: Path,
    output_path: Path,
    remove_shortcut_edges: bool = True,
) -> None:
    with identify_accident_scenario_path.open("r", encoding="utf-8") as fp:
        scenario_data = json.load(fp)
    with causal_edge_linking_path.open("r", encoding="utf-8") as fp:
        edge_data = json.load(fp)

    edges = edge_data.get("edges", [])
    linked_node_ids = {
        node_id
        for edge in edges
        for node_id in (edge.get("source"), edge.get("target"))
        if node_id
    }

    graph_data = {
        "hazard_consequence_node": [],
        "entity_nodes": [],
        "condition_nodes": [],
        "event_nodes": [],
        "edges": [],
    }

    for key in (
        "hazard_consequence_node",
        "entity_nodes",
        "condition_nodes",
        "event_nodes",
    ):
        group = scenario_data.get(key, [])
        if isinstance(group, dict):
            group = [group]
        if not isinstance(group, list):
            group = []
        graph_data[key] = [
            node
            for node in group
            if isinstance(node, dict) and node.get("node_id") in linked_node_ids
        ]

    valid_node_ids = {
        node.get("node_id")
        for key in (
            "hazard_consequence_node",
            "entity_nodes",
            "condition_nodes",
            "event_nodes",
        )
        for node in graph_data[key]
        if node.get("node_id")
    }
    graph_data["edges"] = [
        edge
        for edge in edges
        if edge.get("source") in valid_node_ids and edge.get("target") in valid_node_ids
    ]
    if remove_shortcut_edges:
        graph_data["edges"] = _remove_shortcut_edges(graph_data["edges"])

    write_text(output_path, json.dumps(graph_data, ensure_ascii=False, indent=2))


def _format_causal_narrative_markdown(payload: Dict[str, Any], case_id: str) -> str:
    """Render causal_narrative_extraction JSON into a readable Markdown file."""
    steps = payload.get("causal_steps", [])
    lines: List[str] = [
        "# Causal Narrative Extraction",
        "",
        f"- Case: `{case_id}`",
        f"- Step count: `{len(steps) if isinstance(steps, list) else 0}`",
        "",
    ]

    if not isinstance(steps, list) or not steps:
        lines.extend(
            [
                "## Narrative",
                "",
                "_No causal steps found in `causal_narrative_extraction_output.json`._",
                "",
            ]
        )
        return "\n".join(lines)

    lines.extend(["## Narrative", ""])
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            lines.append(f"{index}. {str(step).strip()}")
            continue
        step_number = step.get("step_number", index)
        description = str(step.get("description") or "").strip()
        lines.append(
            f"{step_number}. {description}" if description else f"{step_number}. _No description provided._"
        )
    lines.append("")
    return "\n".join(lines)


def _format_review_feedback_analysis_markdown(payload: Dict[str, Any], case_id: str) -> str:
    case_summary = payload.get("case_summary", {})
    planning_patterns = payload.get("planning_patterns", [])
    diagnosis_patterns = payload.get("diagnosis_patterns", [])
    coverage_notes = payload.get("coverage_notes", [])
    unresolved = payload.get("unresolved_decisions", [])

    lines: List[str] = [
        "# Review Feedback Analysis",
        "",
        f"- Case: `{case_id}`",
        f"- Accepted: `{case_summary.get('accepted_count', 0)}`",
        f"- Rejected: `{case_summary.get('rejected_count', 0)}`",
        f"- Unresolved: `{case_summary.get('unresolved_count', 0)}`",
        "",
    ]

    summary_text = str(case_summary.get("summary") or "").strip()
    if summary_text:
        lines.extend(["## Summary", "", summary_text, ""])

    lines.extend(["## Planning Patterns", ""])
    if isinstance(planning_patterns, list) and planning_patterns:
        for index, item in enumerate(planning_patterns, start=1):
            if not isinstance(item, dict):
                continue
            lines.extend(
                [
                    f"### {index}. `{item.get('decision_key', '')}`",
                    "",
                    f"Decision: `{item.get('decision', '')}`",
                    "",
                    f"Proposed change: {str(item.get('proposed_change') or '').strip()}",
                    "",
                ]
            )
            reviewer_reason = str(item.get("reviewer_reason") or "").strip()
            matched_rule = str(item.get("matched_rule") or "").strip()
            takeaway = str(item.get("few_shot_takeaway") or "").strip()
            if reviewer_reason:
                lines.extend(["Reviewer reason:", reviewer_reason, ""])
            if matched_rule:
                lines.extend(["Matched rule:", matched_rule, ""])
            if takeaway:
                lines.extend(["Few-shot takeaway:", takeaway, ""])
    else:
        lines.extend(["_No planning patterns._", ""])

    lines.extend(["## Diagnosis Patterns", ""])
    if isinstance(diagnosis_patterns, list) and diagnosis_patterns:
        for index, item in enumerate(diagnosis_patterns, start=1):
            if not isinstance(item, dict):
                continue
            lines.extend(
                [
                    f"### {index}. `{item.get('derived_from_decision_key', '')}`",
                    "",
                    f"Decision: `{item.get('decision', '')}`",
                    "",
                    f"Observed pattern: {str(item.get('observed_pattern') or '').strip()}",
                    "",
                ]
            )
            interpretation = str(item.get("diagnosis_interpretation") or "").strip()
            supporting_rule = str(item.get("supporting_rule") or "").strip()
            takeaway = str(item.get("few_shot_takeaway") or "").strip()
            if interpretation:
                lines.extend(["Diagnosis interpretation:", interpretation, ""])
            if supporting_rule:
                lines.extend(["Supporting rule:", supporting_rule, ""])
            if takeaway:
                lines.extend(["Few-shot takeaway:", takeaway, ""])
    else:
        lines.extend(["_No diagnosis patterns._", ""])

    lines.extend(["## Coverage Notes", ""])
    if isinstance(coverage_notes, list) and coverage_notes:
        for note in coverage_notes:
            note_text = str(note).strip()
            if note_text:
                lines.append(f"- {note_text}")
        lines.append("")
    else:
        lines.extend(["_No coverage notes._", ""])

    lines.extend(["## Unresolved Decisions", ""])
    if isinstance(unresolved, list) and unresolved:
        for item in unresolved:
            if not isinstance(item, dict):
                continue
            key = str(item.get("decision_key") or "").strip()
            status = str(item.get("status") or "").strip()
            note = str(item.get("note") or "").strip()
            lines.append(f"- `{key}` [{status}] {note}".rstrip())
        lines.append("")
    else:
        lines.extend(["_No unresolved decisions._", ""])

    return "\n".join(lines)


def write_causal_narrative_markdown(folder: Path) -> None:
    """Create a Markdown companion file for causal_narrative_extraction output."""
    json_path = folder / "causal_narrative_extraction_output.json"
    if not json_path.exists():
        return
    with json_path.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)
    write_text(
        folder / "causal_narrative_extraction_output.md",
        _format_causal_narrative_markdown(payload, folder.name),
    )


def write_review_feedback_analysis_markdown(folder: Path) -> None:
    json_path = folder / "review_feedback_analysis_output.json"
    if not json_path.exists():
        return
    with json_path.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)
    write_text(
        folder / "review_feedback_analysis_output.md",
        _format_review_feedback_analysis_markdown(payload, folder.name),
    )


def write_causal_narrative_markdown_from_source(*, source_folder: Path, output_folder: Path) -> None:
    json_path = source_folder / "causal_narrative_extraction_output.json"
    if not json_path.exists():
        return
    with json_path.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)
    write_text(
        output_folder / "causal_narrative_extraction_output.md",
        _format_causal_narrative_markdown(payload, output_folder.name),
    )


def ensure_causal_graph_json(folder: Path, *, remove_shortcut_edges: bool = True) -> None:
    """Build causal_graph.json if the required upstream step outputs are present."""
    identify_accident_scenario_path = folder / "identify_accident_scenario_output.json"
    causal_edge_linking_path = folder / "causal_edge_linking_output.json"
    if not identify_accident_scenario_path.exists():
        raise FileNotFoundError(
            f"Missing identify_accident_scenario_output.json for {folder.name}"
        )
    if not causal_edge_linking_path.exists():
        raise FileNotFoundError(
            f"Missing causal_edge_linking_output.json for {folder.name}"
        )
    _build_causal_graph_json(
        identify_accident_scenario_path=identify_accident_scenario_path,
        causal_edge_linking_path=causal_edge_linking_path,
        output_path=folder / "causal_graph.json",
        remove_shortcut_edges=remove_shortcut_edges,
    )


def _prepare_step_inputs(
    *,
    all_prompts: Dict[str, str],
    folder: Path,
    step: Step,
    config: Any,
) -> tuple[Dict[str, Any], List[Dict[str, str]]]:
    template = all_prompts[step.key]
    vars_dict = step.build_vars(folder)
    prompt_text = render_prompt(template, vars_dict)
    messages = [
        {"role": "system", "content": "You are a professional process safety analyst."},
        {"role": "user", "content": prompt_text},
    ]
    save_step_input_snapshot(
        folder=folder,
        step_key=step.key,
        template=template,
        vars_dict=vars_dict,
        prompt_text=prompt_text,
        messages=messages,
        truncate_limit=80000,
    )
    return vars_dict, messages


def _build_responses_request_payload(
    *,
    messages: List[Dict[str, str]],
    step: Step,
    config: Any,
) -> Dict[str, Any]:
    reasoning_effort = step.reasoning_effort or config.reasoning_effort
    step_temperature = step.temperature
    verbosity = step.verbosity or config.verbosity
    force_json_output = getattr(config, "force_json_output", False)
    structured_schema = (
        getattr(config, "structured_output_schemas", None) or {}
    ).get(step.key)

    text_cfg: Dict[str, Any] = {"verbosity": verbosity}
    if structured_schema is not None:
        text_cfg["format"] = {
            "type": "json_schema",
            "name": f"{step.key}_output",
            "strict": True,
            "schema": structured_schema,
        }
    elif force_json_output:
        text_cfg["format"] = {"type": "json_object"}

    request_payload: Dict[str, Any] = {
        "model": config.model_name,
        "input": messages,
        "max_output_tokens": config.max_output_tokens,
        "text": text_cfg,
    }
    if step_temperature is not None:
        request_payload["temperature"] = step_temperature
    else:
        request_payload["reasoning"] = {"effort": reasoning_effort}
    return request_payload


def _persist_step_response(
    *,
    folder: Path,
    step: Step,
    body: Dict[str, Any],
    config: Any,
) -> None:
    out_text = extract_text_from_responses_body(body)
    write_text(step.output_path(folder), out_text)
    if step.key == "review_feedback_analysis":
        write_review_feedback_analysis_markdown(folder)
    if config.save_raw_response:
        response_dir = get_response_dir(folder)
        write_text(
            response_dir / f"{step.key}_response_raw.json",
            json.dumps(body, ensure_ascii=False, indent=2),
        )


def _prepare_graph_inputs_if_needed(
    *,
    folders: List[Path],
    step: Step,
    config: Any,
) -> None:
    if step.key not in {"review_causal_graph", "graph_diagnosis", "graph_revision_planning"}:
        return
    prep_ok = 0
    prep_fail = 0
    for folder in folders:
        try:
            ensure_causal_graph_json(
                folder,
                remove_shortcut_edges=getattr(config, "remove_shortcut_edges", True),
            )
            prep_ok += 1
        except Exception as exc:
            prep_fail += 1
            write_text(folder / f"{step.key}_error.txt", f"Graph prep failed: {exc}\n")
    print(f"[{step.key}] Graph prep done. ok={prep_ok}, fail={prep_fail}")


def run_step_sync(
    client: OpenAI,
    all_prompts: Dict[str, str],
    folders: List[Path],
    step: Step,
    config: Any,
    call_sleep_seconds: float = 0.0,
) -> None:
    _prepare_graph_inputs_if_needed(folders=folders, step=step, config=config)
    ok, fail = 0, 0

    for folder in folders:
        try:
            _, messages = _prepare_step_inputs(
                all_prompts=all_prompts,
                folder=folder,
                step=step,
                config=config,
            )
        except Exception as exc:
            fail += 1
            write_text(folder / f"{step.key}_error.txt", f"Prompt build failed: {exc}\n")
            continue

        try:
            request_payload = _build_responses_request_payload(
                messages=messages,
                step=step,
                config=config,
            )
            resp = client.responses.create(**request_payload)
            body = resp.model_dump() if hasattr(resp, "model_dump") else dict(resp)
            _persist_step_response(
                folder=folder,
                step=step,
                body=body,
                config=config,
            )
            ok += 1
        except Exception as exc:
            fail += 1
            write_text(folder / f"{step.key}_error.txt", f"API call failed: {exc}\n")

        if call_sleep_seconds > 0:
            time.sleep(call_sleep_seconds)

    print(f"[{step.key}] Sync done. ok={ok}, fail={fail}")


async def run_step_async(
    client: AsyncOpenAI,
    all_prompts: Dict[str, str],
    folders: List[Path],
    step: Step,
    config: Any,
) -> None:
    _prepare_graph_inputs_if_needed(folders=folders, step=step, config=config)
    progress = tqdm(total=len(folders), desc=f"{step.key} (async)", unit="req", leave=False)
    max_concurrency = max(1, int(getattr(config, "responses_max_concurrency", 10)))
    semaphore = asyncio.Semaphore(max_concurrency)

    async def one_folder(folder: Path) -> bool:
        try:
            _, messages = _prepare_step_inputs(
                all_prompts=all_prompts,
                folder=folder,
                step=step,
                config=config,
            )
        except Exception as exc:
            write_text(folder / f"{step.key}_error.txt", f"Prompt build failed: {exc}\n")
            return False

        try:
            request_payload = _build_responses_request_payload(
                messages=messages,
                step=step,
                config=config,
            )
            async with semaphore:
                resp = await client.responses.create(**request_payload)
            body = resp.model_dump() if hasattr(resp, "model_dump") else dict(resp)
            _persist_step_response(
                folder=folder,
                step=step,
                body=body,
                config=config,
            )
            return True
        except Exception as exc:
            write_text(folder / f"{step.key}_error.txt", f"API call failed: {exc}\n")
            return False
        finally:
            progress.update(1)

    tasks = [asyncio.create_task(one_folder(folder)) for folder in folders]
    ok = 0
    fail = 0
    try:
        for task in asyncio.as_completed(tasks):
            if await task:
                ok += 1
            else:
                fail += 1
    finally:
        progress.close()

    print(f"[{step.key}] Async done. ok={ok}, fail={fail}")
    if fail and getattr(config, "stop_on_step_failure", False):
        raise RuntimeError(
            f"[{step.key}] {fail} of {len(folders)} Responses requests failed; "
            "stopping before dependent steps."
        )


async def _run_pipeline_async(
    *,
    all_prompts: Dict[str, str],
    folders: List[Path],
    pipeline: List[Step],
    config: Any,
) -> None:
    client = AsyncOpenAI()
    print("[RUNTIME] responses_async_enabled = True")
    print(
        "[RUNTIME] responses_max_concurrency = "
        f"{max(1, int(getattr(config, 'responses_max_concurrency', 10)))}"
    )
    if getattr(config, "call_sleep_seconds", 0.0) > 0:
        print("[RUNTIME] call_sleep_seconds is ignored in async responses mode")
    for step in tqdm(pipeline, desc="Steps (async)", unit="step"):
        if not step.enabled:
            continue
        await run_step_async(
            client=client,
            all_prompts=all_prompts,
            folders=folders,
            step=step,
            config=config,
        )
    await client.close()


def run_local_postprocess(
    all_prompts: Dict[str, str],
    folder: Path,
    hazards_json_path: Path,
    accident_scenario_schema_path: Path,
    source_folder: Path | None = None,
    remove_shortcut_edges: bool = True,
) -> None:
    # Import lazily so extraction-only runners that disable local postprocessing
    # do not require the optional Word-report dependency.
    import utils.incident_card_to_word as incident_card_to_word

    source_folder = source_folder or folder
    write_causal_narrative_markdown_from_source(source_folder=source_folder, output_folder=folder)
    ensure_causal_graph_json(
        folder,
        remove_shortcut_edges=remove_shortcut_edges,
    )
    causal_graph_path = folder / "causal_graph.json"

    draw_causal_graph_interactive_from_json(
        identify_accident_scenario=causal_graph_path,
        causal_edge_linking=causal_graph_path,
        save_path=folder / "causal_graph.html",
        accident_scenario_schema=accident_scenario_schema_path,
        review_causal_graph=resolve_review_output_path(folder),
        revision_decisions=None,
        case_id=folder.name,
    )

    generate_accept_all_review_outputs(
        folder=folder,
        accident_scenario_schema_path=accident_scenario_schema_path,
        remove_shortcut_edges=remove_shortcut_edges,
    )

    updated_graph_path = folder / "updated_causal_graph.json"
    updated_review_state_path = folder / "updated_causal_graph_review_state.json"
    if updated_graph_path.exists() and updated_review_state_path.exists():
        # Skip generating `updated_causal_graph.html` during local postprocess.
        # Keep the updated JSON and review state files, but do not write the HTML output.
        pass

    incident_card_to_word.incident_card_to_word(
        identify_incident_prompt=all_prompts.get("identify_incident", ""),
        identify_hazard_consequence_prompt=all_prompts.get("identify_hazard_consequence", ""),
        identify_accident_scenario_prompt=all_prompts.get("identify_accident_scenario", ""),
        causal_edge_linking_prompt=all_prompts.get("causal_edge_linking", ""),
        identify_incident_output=source_folder / "identify_incident_output.json",
        identify_hazard_consequence_output=source_folder / "identify_hazard_consequence_output.json",
        identify_accident_scenario_output=folder / "identify_accident_scenario_output.json",
        causal_edge_linking_output=folder / "causal_edge_linking_output.json",
        hazard_consequence_json=str(hazards_json_path),
        accident_scenario_schema_json=str(accident_scenario_schema_path),
        output_docx_path=folder / "incident_card_report.docx",
    )


def run_batch_pipeline(config: Any) -> None:
    assert_prompt_step_configuration_valid(step_registry=STEP_REGISTRY)

    client = OpenAI()
    print("[RUNTIME] OPENAI_API_KEY =", _mask(os.getenv("OPENAI_API_KEY")))
    print("[RUNTIME] OPENAI_BASE_URL env =", os.getenv("OPENAI_BASE_URL"))
    print("[RUNTIME] client base_url =", getattr(client, "base_url", None))

    all_prompts = prompt_manager.prompts.load_all()
    configured_folders = getattr(config, "target_folders", None)
    if configured_folders is not None:
        folders = list(configured_folders)
    else:
        folders = [
            folder
            for folder in config.base_dir.iterdir()
            if folder.is_dir() and not folder.name.startswith("_")
        ]
    print(f"Found {len(folders)} folders under {config.base_dir}")

    for folder in folders:
        get_response_dir(folder)

    pipeline = build_pipeline(
        hazards_json=config.hazards_json_path,
        conditions_json=config.conditions_json_path,
        use_few_shot=getattr(config, "use_few_shot", False),
        few_shot_cases_by_step=getattr(config, "few_shot_cases_by_step", None),
        few_shot_pattern_files_by_step=getattr(
            config, "few_shot_pattern_files_by_step", None
        ),
        active_step_keys=getattr(config, "active_step_keys", None),
        source_folder_map=getattr(config, "source_folder_map", None),
    )
    if getattr(config, "responses_async_enabled", False):
        asyncio.run(
            _run_pipeline_async(
                all_prompts=all_prompts,
                folders=folders,
                pipeline=pipeline,
                config=config,
            )
        )
    else:
        for step in tqdm(pipeline, desc="Steps (sync)", unit="step"):
            if not step.enabled:
                continue
            run_step_sync(
                client=client,
                all_prompts=all_prompts,
                folders=folders,
                step=step,
                config=config,
                call_sleep_seconds=config.call_sleep_seconds,
            )

    if getattr(config, "enable_local_postprocess", True):
        for folder in tqdm(folders, desc="Local postprocess", unit="folder"):
            try:
                run_local_postprocess(
                    all_prompts=all_prompts,
                    folder=folder,
                    hazards_json_path=config.hazards_json_path,
                    accident_scenario_schema_path=Path("scheme/accident_scenario_schema.json"),
                    source_folder=(getattr(config, "source_folder_map", None) or {}).get(folder, folder),
                    remove_shortcut_edges=getattr(config, "remove_shortcut_edges", True),
                )
            except Exception as exc:
                print(f"Postprocess skipped for {folder.name}: {exc}")
