"""
causal_graph_interactive

Generate:
1) Static causal graphs via Graphviz (PNG/SVG/PDF)
2) Interactive HTML causal graphs via Cytoscape.js + Dagre (CDN)

Primary entrypoint:
    draw_causal_graph_interactive(...)

Behavior:
- If save_path endswith ".html" (or fmt="html"), an interactive HTML file is generated.
- Otherwise, Graphviz renders a static image (requires graphviz + python-graphviz).

Color rules (aligned with your Python implementation):
- Nodes with hazard tags in angle brackets, e.g. "X <Pool fire>", are treated as CONDITION nodes
  and colored by hazard-specific colors (HAZARD_COLORS[tag]) if available; otherwise condition_color.
- Other nodes can be highlighted as:
  - hazards (hazard_color) if listed in hazards JSON/text
  - conditions (condition_color) if listed in conditions JSON/text
  - neutral otherwise
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Union, List, Optional, Dict, Set, Tuple
from copy import deepcopy
import json
import os
import re
import textwrap
import unicodedata

# ============================================================
# Color table for hazard-specific condition colors
# ============================================================
HAZARD_COLORS: Dict[str, str] = {
    "confined explosion": "#FF7EB6",
    "vce": "#FF8A3D",
    "bleve": "#FF6F61",
    "dust explosion": "#FFD966",
    "pool fire": "#D78BFF",
    "jet fire": "#63A0FF",
    "fire ball": "#9D8CFF",
    "flash fire": "#C8C6A7",
    "toxicity dispersion": "#00C2CB",
    "asphyxiation": "#4CC9A1",
}

STYLE_VERSION = "card-style-v2.1"

__all__ = [
    "HAZARD_COLORS",
    "draw_causal_graph_interactive",
    "draw_causal_graph_interactive_from_json",
    "draw_updated_causal_graph_interactive_from_json",
]


# ============================================================
# Helpers (aligned with your existing code)
# ============================================================

def _sanitize_name(name: str) -> str:
    """
    Replace ALL Unicode dash-like characters (category Pd) with underscore '_'.
    Keep ordinary '-' untouched. This targets punctuation dashes like en/em dashes.
    """
    out = []
    for ch in name:
        if unicodedata.category(ch) == "Pd":
            out.append("_")
        else:
            out.append(ch)
    return "".join(out)

def _normalize_hazard_consequence_name(s: str) -> str:
    """
    Normalize hazard consequence node label for matching HAZARD_COLORS keys.
    Examples:
      "Toxicity dispersion 1" -> "toxicity dispersion"
      "Pool fire number" -> "pool fire"
      "Pool fire (3)" -> "pool fire"
      "Jet fire-2" -> "jet fire"
    """
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace("\u00A0", " ").replace("\u2009", " ").replace("\u202F", " ")
    s = s.strip().lower()
    s = re.sub(r"\s+", " ", s).strip()

    # drop trailing "... number" / "... number 12"
    s = re.sub(r"(?:\s+number(?:\s*\d+)?)$", "", s).strip()

    # drop trailing "(12)"
    s = re.sub(r"\s*\(\s*\d+\s*\)\s*$", "", s).strip()

    # drop trailing digits with optional separators: " 12" / "-12" / "_12"
    s = re.sub(r"[\s\-_]*\d+$", "", s).strip()

    s = re.sub(r"\s+", " ", s).strip()
    return s

def _is_hazard_consequence_node(name: str) -> bool:
    norm = _normalize_hazard_consequence_name(name)
    return norm in HAZARD_COLORS

def _normalize_text_block(s: str) -> str:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s = s[1:-1]
    return s.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\r\n", "\n")

def _split_into_lines(s: str) -> List[str]:
    if "\n" in s:
        return s.splitlines()
    return re.split(r"(?<=[\.!?])\s+", s)

def _to_arrow_lines(data: Union[str, Iterable[str]]) -> List[str]:
    if isinstance(data, str):
        data = _normalize_text_block(data)
        lines = _split_into_lines(data)
    else:
        lines = list(data)

    pat = re.compile(r"(.+?)\s*->\s*(.+)")
    out: List[str] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        m = pat.match(line)
        if not m:
            continue
        src = re.sub(r"\s+", " ", m.group(1).rstrip(".").strip())
        dst = re.sub(r"\s+", " ", m.group(2).rstrip(".").strip())
        out.append(f"{src} -> {dst}")

    # de-duplicate, preserve order (case-insensitive)
    seen = set()
    dedup = []
    for x in out:
        k = x.lower()
        if k not in seen:
            seen.add(k)
            dedup.append(x)
    return dedup

def _collect_nodes_from_arrow_lines(lines: List[str]) -> List[str]:
    nodes: List[str] = []
    for line in lines:
        if "->" not in line:
            continue
        src, dst = line.split("->", 1)
        nodes.append(_sanitize_name(src.strip()))
        nodes.append(_sanitize_name(dst.strip()))

    seen_lower: Set[str] = set()
    ordered: List[str] = []
    for n in nodes:
        key = n.lower()
        if key not in seen_lower:
            seen_lower.add(key)
            ordered.append(n)
    return ordered

def _load_highlight_nodes(source: Union[str, Iterable[str], None]) -> Set[str]:
    """
    Accept:
      - path to JSON list (["node a", "node b", ...])
      - a single string (one node)
      - iterable of strings
      - None
    Returns a set of lowercase node labels.
    """
    if source is None:
        return set()

    if isinstance(source, (str, os.PathLike)):
        p = Path(source)
        if p.exists():
            with p.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                # allow {"nodes": [...]}
                data = data.get("nodes", [])
            return {str(x).strip().lower() for x in data}
        else:
            return {str(source).strip().lower()}

    # iterable
    return {str(x).strip().lower() for x in source}
def _normalize_hazard_tag(tag: str) -> str:
    """
    Normalize hazard tag inside <> to match HAZARD_COLORS keys.
    Handles:
      <Pool fire 1>      -> pool fire
      <Pool fire-2>      -> pool fire
      <Pool fire_3>      -> pool fire
      <Pool fire number> -> pool fire
      <Pool fire number 4> -> pool fire
    """
    tag = (tag or "").strip().lower()

    # collapse whitespace first
    tag = re.sub(r"\s+", " ", tag).strip()

    # remove trailing patterns:
    #   " number", " number 12", " 12", "-12", "_12"
    tag = re.sub(r"(?:\s+number(?:\s*\d+)?)$", "", tag)   # ... number / number 12
    tag = re.sub(r"[\s\-_]*\d+$", "", tag)                # ... 12 / -12 / _12

    # collapse whitespace again after removals
    tag = re.sub(r"\s+", " ", tag).strip()

    return tag


def _extract_hazard_tag(name: str) -> str | None:
    if "<" not in name or ">" not in name:
        return None
    raw = name.split("<", 1)[1].split(">", 1)[0]
    tag = _normalize_hazard_tag(raw)
    return tag or None

def _wrap_label(label: str, width: int) -> str:
    wrapped_parts: List[str] = []
    for part in str(label).splitlines() or [""]:
        chunk = textwrap.wrap(part, width=width) or [part]
        wrapped_parts.extend(chunk)
    return "\n".join(wrapped_parts)


def _load_json_payload(source: Union[str, os.PathLike, Dict, List]) -> Union[Dict, List]:
    if isinstance(source, (dict, list)):
        return source
    path = Path(source)
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _collect_scenario_nodes(payload: Dict[str, object]) -> List[Dict[str, str]]:
    nodes: List[Dict[str, str]] = []
    for key, value in payload.items():
        if not isinstance(value, list):
            continue
        if key not in {
            "hazard_consequence_node",
            "entity_nodes",
            "condition_nodes",
            "event_nodes",
        }:
            continue
        for item in value:
            if isinstance(item, dict):
                nodes.append(item)
    return nodes


def _canonicalize_node_type(node_type: str) -> str:
    normalized_type = (node_type or "").strip().lower()
    if normalized_type == "intermediateevent":
        return "event"
    return normalized_type


def _node_fill_from_type(node_type: str, name: str) -> str:
    normalized_type = _canonicalize_node_type(node_type)
    if normalized_type == "hazardconsequence":
        return "#ffd6d6"
    if normalized_type == "condition":
        if (name or "").strip().lower() == "not specified":
            return "#f2f2f2"
        return "#d8ebff"
    if normalized_type == "entity":
        return "#ddf5df"
    if normalized_type == "event":
        return "#f3e7ff"
    return "#f4f4f4"


def _should_hide_node(name: str) -> bool:
    normalized = re.sub(r"\s+", " ", (name or "").strip().lower())
    hidden_values = {
        "not specified",
        "not dispersed",
        "not dispered",
    }
    return normalized in hidden_values


def _build_elements_from_json_graph(
    scenario_payload: Dict[str, object],
    edge_payload: Dict[str, object],
    *,
    width: int = 26,
) -> Dict[str, List[Dict[str, object]]]:
    nodes_by_id: Dict[str, Dict[str, object]] = {}
    for node in _collect_scenario_nodes(scenario_payload):
        node_id = str(node.get("node_id", "")).strip()
        if not node_id:
            continue
        label = str(node.get("label", "")).strip() or node_id
        name = str(node.get("name", "")).strip() or "N/A"
        if _should_hide_node(name):
            continue
        raw_node_type = str(node.get("node_type", "")).strip()
        canonical_node_type = _canonicalize_node_type(raw_node_type)
        node_type = canonical_node_type or "Unknown"
        label_wrapped = _wrap_label(label, width=18)
        name_wrapped = _wrap_label(name, width=24)
        label_line_count = max(1, len(label_wrapped.splitlines()))
        name_line_count = max(1, len(name_wrapped.splitlines()))
        node_height = 28 + label_line_count * 18 + name_line_count * 18
        title_parts = [
            f"ID: {node_id}",
            f"Label: {label}",
            f"Name: {name}",
            f"Type: {node_type}",
        ]
        evidence = str(node.get("evidence", "")).strip()
        explanation = str(node.get("explanation", "")).strip()
        if evidence:
            title_parts.append(f"Evidence: {evidence}")
        if explanation:
            title_parts.append(f"Explanation: {explanation}")

        nodes_by_id[node_id] = {
            "data": {
                "id": node_id,
                "nodeId": node_id,
                "label": label,
                "name": name,
                "nodeType": node_type,
                "labelWrapped": label_wrapped,
                "nameWrapped": name_wrapped,
                "evidence": evidence,
                "explanation": explanation,
                "fill": _node_fill_from_type(node_type, name),
                "nodeWidth": 260,
                "nodeHeight": node_height,
                "title": "\n".join(title_parts),
            }
        }

    edges: List[Dict[str, object]] = []
    referenced_node_ids: Set[str] = set()
    seen_edges: Set[Tuple[str, str, str]] = set()
    raw_edges = edge_payload.get("edges", [])
    if not isinstance(raw_edges, list):
        raw_edges = []

    for idx, edge in enumerate(raw_edges):
        if not isinstance(edge, dict):
            continue
        source = str(edge.get("source", "")).strip()
        target = str(edge.get("target", "")).strip()
        relation = str(edge.get("relation", "")).strip()
        evidence = str(edge.get("evidence", "")).strip()
        explanation = str(edge.get("explanation", "")).strip()
        if not source or not target:
            continue
        if source not in nodes_by_id or target not in nodes_by_id:
            continue
        edge_key = (source.lower(), target.lower(), relation.lower())
        if edge_key in seen_edges:
            continue
        seen_edges.add(edge_key)
        referenced_node_ids.add(source)
        referenced_node_ids.add(target)
        edges.append(
            {
                "data": {
                    "id": f"e{idx}",
                    "source": source,
                    "target": target,
                    "label": relation,
                    "relation": relation,
                    "evidence": evidence,
                    "explanation": explanation,
                    "title": "\n".join(
                        [
                            f"{source} -> {target}",
                            f"Relation: {relation or 'N/A'}",
                            f"Evidence: {evidence}",
                            f"Explanation: {explanation}",
                        ]
                    ),
                }
            }
        )

    return {
        "nodes": [
            node_payload
            for node_id, node_payload in nodes_by_id.items()
            if node_id in referenced_node_ids
        ],
        "edges": edges,
    }


def _build_schema_form_options(schema_payload: Dict[str, object]) -> Dict[str, object]:
    label_to_type: Dict[str, str] = {}
    labels: List[str] = []
    types: List[str] = []

    for key in (
        "hazard_consequence_node",
        "entity_nodes",
        "condition_nodes",
        "event_nodes",
    ):
        items = schema_payload.get(key, [])
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label", "")).strip()
            node_type = _canonicalize_node_type(str(item.get("node_type", "")).strip())
            if label and label not in labels:
                labels.append(label)
            if node_type and node_type not in types:
                types.append(node_type)
            if label and node_type and label not in label_to_type:
                label_to_type[label] = node_type

    return {
        "labels": labels,
        "types": types,
        "label_to_type": label_to_type,
        "relations": ["has", "enables"],
    }


def _apply_deleted_marks_from_review_state(
    graph_elements: Dict[str, List[Dict[str, object]]],
    review_state_payload: Dict[str, object],
) -> None:
    if not isinstance(graph_elements, dict) or not isinstance(review_state_payload, dict):
        return

    deleted_nodes_raw = review_state_payload.get("deleted_nodes", [])
    deleted_edges_raw = review_state_payload.get("deleted_edges", [])

    deleted_node_ids: Set[str] = set()
    if isinstance(deleted_nodes_raw, list):
        for item in deleted_nodes_raw:
            if isinstance(item, str):
                node_id = item.strip()
                if node_id:
                    deleted_node_ids.add(node_id)
            elif isinstance(item, dict):
                node_id = str(item.get("node_id", "")).strip() or str(item.get("id", "")).strip()
                if node_id:
                    deleted_node_ids.add(node_id)

    deleted_edge_keys: Set[Tuple[str, str, str]] = set()
    if isinstance(deleted_edges_raw, list):
        for item in deleted_edges_raw:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source", "")).strip()
            target = str(item.get("target", "")).strip()
            relation = str(item.get("relation", "")).strip()
            if source and target:
                deleted_edge_keys.add((source, target, relation))

    for node in graph_elements.get("nodes", []):
        if not isinstance(node, dict):
            continue
        data = node.get("data", {})
        if not isinstance(data, dict):
            continue
        node_id = str(data.get("nodeId", "")).strip() or str(data.get("id", "")).strip()
        if node_id in deleted_node_ids:
            classes = str(node.get("classes", "")).strip()
            if "delete-mark" not in classes.split():
                node["classes"] = f"{classes} delete-mark".strip()

    for edge in graph_elements.get("edges", []):
        if not isinstance(edge, dict):
            continue
        data = edge.get("data", {})
        if not isinstance(data, dict):
            continue
        key = (
            str(data.get("source", "")).strip(),
            str(data.get("target", "")).strip(),
            str(data.get("relation", data.get("label", ""))).strip(),
        )
        if key in deleted_edge_keys:
            classes = str(edge.get("classes", "")).strip()
            if "delete-mark" not in classes.split():
                edge["classes"] = f"{classes} delete-mark".strip()


def _extract_deleted_marks_from_existing_html(
    html_path: Union[str, os.PathLike],
) -> Dict[str, Set[Tuple[str, str, str]]]:
    path = Path(html_path)
    if not path.exists():
        return {"nodes": set(), "edges": set()}

    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return {"nodes": set(), "edges": set()}

    match = re.search(
        r"const elements = (.*?);\s*const schemaForm =",
        text,
        flags=re.DOTALL,
    )
    if not match:
        return {"nodes": set(), "edges": set()}

    elements_json = match.group(1).strip()
    try:
        elements = json.loads(elements_json)
    except Exception:
        return {"nodes": set(), "edges": set()}
    if not isinstance(elements, dict):
        return {"nodes": set(), "edges": set()}

    deleted_node_ids: Set[Tuple[str, str, str]] = set()
    for node in elements.get("nodes", []):
        if not isinstance(node, dict):
            continue
        classes = str(node.get("classes", "")).strip().split()
        if "delete-mark" not in classes:
            continue
        data = node.get("data", {})
        if not isinstance(data, dict):
            continue
        node_id = str(data.get("nodeId", "")).strip() or str(data.get("id", "")).strip()
        if node_id:
            deleted_node_ids.add((node_id, "", ""))

    deleted_edge_keys: Set[Tuple[str, str, str]] = set()
    for edge in elements.get("edges", []):
        if not isinstance(edge, dict):
            continue
        classes = str(edge.get("classes", "")).strip().split()
        if "delete-mark" not in classes:
            continue
        data = edge.get("data", {})
        if not isinstance(data, dict):
            continue
        source = str(data.get("source", "")).strip()
        target = str(data.get("target", "")).strip()
        relation = str(data.get("relation", data.get("label", ""))).strip()
        if source and target:
            deleted_edge_keys.add((source, target, relation))

    return {"nodes": deleted_node_ids, "edges": deleted_edge_keys}


def _apply_deleted_marks_from_existing_html(
    graph_elements: Dict[str, List[Dict[str, object]]],
    existing_html_path: Union[str, os.PathLike],
) -> None:
    extracted = _extract_deleted_marks_from_existing_html(existing_html_path)
    deleted_nodes = extracted.get("nodes", set())
    deleted_edges = extracted.get("edges", set())

    if not deleted_nodes and not deleted_edges:
        return

    deleted_node_ids = {node_id for node_id, _, _ in deleted_nodes}

    for node in graph_elements.get("nodes", []):
        if not isinstance(node, dict):
            continue
        data = node.get("data", {})
        if not isinstance(data, dict):
            continue
        node_id = str(data.get("nodeId", "")).strip() or str(data.get("id", "")).strip()
        if node_id in deleted_node_ids:
            classes = str(node.get("classes", "")).strip()
            if "delete-mark" not in classes.split():
                node["classes"] = f"{classes} delete-mark".strip()

    for edge in graph_elements.get("edges", []):
        if not isinstance(edge, dict):
            continue
        data = edge.get("data", {})
        if not isinstance(data, dict):
            continue
        key = (
            str(data.get("source", "")).strip(),
            str(data.get("target", "")).strip(),
            str(data.get("relation", data.get("label", ""))).strip(),
        )
        if key in deleted_edges:
            classes = str(edge.get("classes", "")).strip()
            if "delete-mark" not in classes.split():
                edge["classes"] = f"{classes} delete-mark".strip()


def _load_elements_from_existing_html(
    html_path: Union[str, os.PathLike],
) -> Dict[str, List[Dict[str, object]]]:
    path = Path(html_path)
    if not path.exists():
        return {"nodes": [], "edges": []}
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return {"nodes": [], "edges": []}

    match = re.search(
        r"const elements = (.*?);\s*const schemaForm =",
        text,
        flags=re.DOTALL,
    )
    if not match:
        return {"nodes": [], "edges": []}

    try:
        payload = json.loads(match.group(1).strip())
    except Exception:
        return {"nodes": [], "edges": []}
    if not isinstance(payload, dict):
        return {"nodes": [], "edges": []}

    nodes = payload.get("nodes", [])
    edges = payload.get("edges", [])
    return {
        "nodes": nodes if isinstance(nodes, list) else [],
        "edges": edges if isinstance(edges, list) else [],
    }


def _merge_deleted_elements_from_existing_html(
    graph_elements: Dict[str, List[Dict[str, object]]],
    existing_html_path: Union[str, os.PathLike],
) -> None:
    existing = _load_elements_from_existing_html(existing_html_path)
    existing_nodes = existing.get("nodes", [])
    existing_edges = existing.get("edges", [])

    if not existing_nodes and not existing_edges:
        return

    nodes = graph_elements.setdefault("nodes", [])
    edges = graph_elements.setdefault("edges", [])

    node_index: Dict[str, Dict[str, object]] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        data = node.get("data", {})
        if not isinstance(data, dict):
            continue
        node_id = str(data.get("nodeId", "")).strip() or str(data.get("id", "")).strip()
        if node_id:
            node_index[node_id] = node

    for old_node in existing_nodes:
        if not isinstance(old_node, dict):
            continue
        old_classes = str(old_node.get("classes", "")).strip().split()
        if "delete-mark" not in old_classes:
            continue
        data = old_node.get("data", {})
        if not isinstance(data, dict):
            continue
        node_id = str(data.get("nodeId", "")).strip() or str(data.get("id", "")).strip()
        if not node_id:
            continue
        if node_id in node_index:
            classes = str(node_index[node_id].get("classes", "")).strip()
            if "delete-mark" not in classes.split():
                node_index[node_id]["classes"] = f"{classes} delete-mark".strip()
        else:
            copied = deepcopy(old_node)
            classes = str(copied.get("classes", "")).strip()
            if "delete-mark" not in classes.split():
                copied["classes"] = f"{classes} delete-mark".strip()
            nodes.append(copied)
            node_index[node_id] = copied

    edge_index: Dict[Tuple[str, str, str], Dict[str, object]] = {}
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        data = edge.get("data", {})
        if not isinstance(data, dict):
            continue
        key = (
            str(data.get("source", "")).strip(),
            str(data.get("target", "")).strip(),
            str(data.get("relation", data.get("label", ""))).strip(),
        )
        if key[0] and key[1]:
            edge_index[key] = edge

    existing_node_by_id: Dict[str, Dict[str, object]] = {}
    for old_node in existing_nodes:
        if not isinstance(old_node, dict):
            continue
        data = old_node.get("data", {})
        if not isinstance(data, dict):
            continue
        node_id = str(data.get("nodeId", "")).strip() or str(data.get("id", "")).strip()
        if node_id:
            existing_node_by_id[node_id] = old_node

    for old_edge in existing_edges:
        if not isinstance(old_edge, dict):
            continue
        old_classes = str(old_edge.get("classes", "")).strip().split()
        if "delete-mark" not in old_classes:
            continue
        data = old_edge.get("data", {})
        if not isinstance(data, dict):
            continue
        source = str(data.get("source", "")).strip()
        target = str(data.get("target", "")).strip()
        relation = str(data.get("relation", data.get("label", ""))).strip()
        if not source or not target:
            continue
        key = (source, target, relation)

        if source not in node_index and source in existing_node_by_id:
            copied_src = deepcopy(existing_node_by_id[source])
            src_classes = str(copied_src.get("classes", "")).strip()
            if "delete-mark" not in src_classes.split():
                copied_src["classes"] = f"{src_classes} delete-mark".strip()
            nodes.append(copied_src)
            node_index[source] = copied_src
        if target not in node_index and target in existing_node_by_id:
            copied_tgt = deepcopy(existing_node_by_id[target])
            tgt_classes = str(copied_tgt.get("classes", "")).strip()
            if "delete-mark" not in tgt_classes.split():
                copied_tgt["classes"] = f"{tgt_classes} delete-mark".strip()
            nodes.append(copied_tgt)
            node_index[target] = copied_tgt

        if key in edge_index:
            classes = str(edge_index[key].get("classes", "")).strip()
            if "delete-mark" not in classes.split():
                edge_index[key]["classes"] = f"{classes} delete-mark".strip()
        else:
            copied_edge = deepcopy(old_edge)
            classes = str(copied_edge.get("classes", "")).strip()
            if "delete-mark" not in classes.split():
                copied_edge["classes"] = f"{classes} delete-mark".strip()
            edges.append(copied_edge)
            edge_index[key] = copied_edge


def _ensure_unique_element_ids(graph_elements: Dict[str, List[Dict[str, object]]]) -> None:
    nodes = graph_elements.get("nodes", [])
    edges = graph_elements.get("edges", [])

    used_ids: Set[str] = set()
    duplicate_index = 0

    for node in nodes:
        if not isinstance(node, dict):
            continue
        data = node.get("data", {})
        if not isinstance(data, dict):
            continue
        raw_id = str(data.get("id", "")).strip()
        if not raw_id:
            duplicate_index += 1
            raw_id = f"n_auto_{duplicate_index}"
            data["id"] = raw_id
        if raw_id in used_ids:
            duplicate_index += 1
            new_id = f"{raw_id}_dup_{duplicate_index}"
            data["id"] = new_id
            raw_id = new_id
        used_ids.add(raw_id)
        node_id = str(data.get("nodeId", "")).strip()
        if not node_id:
            data["nodeId"] = raw_id

    for edge in edges:
        if not isinstance(edge, dict):
            continue
        data = edge.get("data", {})
        if not isinstance(data, dict):
            continue
        raw_id = str(data.get("id", "")).strip()
        if not raw_id:
            duplicate_index += 1
            raw_id = f"e_auto_{duplicate_index}"
            data["id"] = raw_id
        if raw_id in used_ids:
            duplicate_index += 1
            new_id = f"{raw_id}_dup_{duplicate_index}"
            data["id"] = new_id
            raw_id = new_id
        used_ids.add(raw_id)


def _append_class(element: Dict[str, object], class_name: str) -> None:
    classes = str(element.get("classes", "")).strip().split()
    if class_name not in classes:
        classes.append(class_name)
    element["classes"] = " ".join(classes).strip()


def _edge_key_from_data(data: Dict[str, object]) -> Tuple[str, str, str]:
    source = str(data.get("source", "")).strip()
    target = str(data.get("target", "")).strip()
    relation = str(data.get("relation", data.get("label", ""))).strip()
    return (source, target, relation)


def _text_field(value: object) -> str:
    return str(value or "").strip()


def _apply_diff_marks_from_baseline_html(
    graph_elements: Dict[str, List[Dict[str, object]]],
    baseline_html_path: Union[str, os.PathLike],
) -> None:
    baseline = _load_elements_from_existing_html(baseline_html_path)
    baseline_nodes = baseline.get("nodes", [])
    baseline_edges = baseline.get("edges", [])
    if not baseline_nodes and not baseline_edges:
        return

    nodes = graph_elements.setdefault("nodes", [])
    edges = graph_elements.setdefault("edges", [])

    current_node_index: Dict[str, Dict[str, object]] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        data = node.get("data", {})
        if not isinstance(data, dict):
            continue
        node_id = _text_field(data.get("nodeId")) or _text_field(data.get("id"))
        if node_id:
            current_node_index[node_id] = node

    baseline_node_index: Dict[str, Dict[str, object]] = {}
    for node in baseline_nodes:
        if not isinstance(node, dict):
            continue
        data = node.get("data", {})
        if not isinstance(data, dict):
            continue
        node_id = _text_field(data.get("nodeId")) or _text_field(data.get("id"))
        if node_id:
            baseline_node_index[node_id] = node

    # Mark node updates when node_id matches but text fields changed.
    for node_id, current_node in current_node_index.items():
        baseline_node = baseline_node_index.get(node_id)
        if not baseline_node:
            continue
        current_data = current_node.get("data", {}) if isinstance(current_node.get("data", {}), dict) else {}
        baseline_data = baseline_node.get("data", {}) if isinstance(baseline_node.get("data", {}), dict) else {}
        changed = (
            _text_field(current_data.get("name")) != _text_field(baseline_data.get("name"))
            or _text_field(current_data.get("evidence")) != _text_field(baseline_data.get("evidence"))
            or _text_field(current_data.get("explanation")) != _text_field(baseline_data.get("explanation"))
        )
        if changed:
            _append_class(current_node, "added-highlight")

    current_edge_index: Dict[Tuple[str, str, str], Dict[str, object]] = {}
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        data = edge.get("data", {})
        if not isinstance(data, dict):
            continue
        key = _edge_key_from_data(data)
        if key[0] and key[1]:
            current_edge_index[key] = edge

    baseline_edge_index: Dict[Tuple[str, str, str], Dict[str, object]] = {}
    for edge in baseline_edges:
        if not isinstance(edge, dict):
            continue
        data = edge.get("data", {})
        if not isinstance(data, dict):
            continue
        key = _edge_key_from_data(data)
        if key[0] and key[1]:
            baseline_edge_index[key] = edge

    # Mark edges as added when they exist in current graph but not in baseline.
    for key, current_edge in current_edge_index.items():
        if key not in baseline_edge_index:
            _append_class(current_edge, "added-highlight")

    # Add deleted-edge traces for edges that existed in baseline but are gone now.
    for key, baseline_edge in baseline_edge_index.items():
        if key in current_edge_index:
            continue
        source_id, target_id, _ = key
        if source_id not in current_node_index and source_id in baseline_node_index:
            copied_src = deepcopy(baseline_node_index[source_id])
            _append_class(copied_src, "delete-mark")
            nodes.append(copied_src)
            current_node_index[source_id] = copied_src
        if target_id not in current_node_index and target_id in baseline_node_index:
            copied_tgt = deepcopy(baseline_node_index[target_id])
            _append_class(copied_tgt, "delete-mark")
            nodes.append(copied_tgt)
            current_node_index[target_id] = copied_tgt

        copied_edge = deepcopy(baseline_edge)
        _append_class(copied_edge, "delete-mark")
        edges.append(copied_edge)
        current_edge_index[key] = copied_edge

# ============================================================
# HTML generation
# ============================================================

_HTML_TEMPLATE = r"""<!doctype html>
<html lang="zh">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Interactive Causal Graph (Cytoscape.js)</title>

  <!-- Cytoscape -->
  <script src="https://unpkg.com/cytoscape/dist/cytoscape.min.js"></script>

  <!-- Dagre (for hierarchical layout) -->
  <script src="https://unpkg.com/dagre@0.8.5/dist/dagre.min.js"></script>
  <script src="https://unpkg.com/cytoscape-dagre/cytoscape-dagre.js"></script>

  <style>
    :root{
      /* Page background */
      --bg: #ffffff;

      /* Panels / cards */
      --panel: #ffffff;

      /* Text colors */
      --text: #111111;
      --muted: #555555;

      /* Borders & dividers */
      --border: #dddddd;

      /* Shadows (lighter than dark theme) */
      --shadow: 0 8px 24px rgba(0,0,0,0.12);

      /* UI shape */
      --radius: 14px;

      /* Fonts */
      --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas,
              "Liberation Mono", "Courier New", monospace;
      --sans: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto,
              Helvetica, Arial, "Apple Color Emoji", "Segoe UI Emoji";
    }

    html, body { height: 100%; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: var(--sans);
    }

    .app{
      display: grid;
      grid-template-columns: 420px 1fr;
      gap: 14px;
      height: 100%;
      padding: 14px;
      box-sizing: border-box;
    }

    .panel{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      overflow: hidden;
      display: flex;
      flex-direction: column;
      min-height: 0;
    }

    .panel-header{
      padding: 14px 14px 10px 14px;
      border-bottom: 1px solid var(--border);
      background: linear-gradient(180deg, rgba(255,255,255,0.08), rgba(255,255,255,0.04));
    }

    .title{
      font-size: 14px;
      letter-spacing: 0.2px;
      font-weight: 650;
      margin: 0 0 6px 0;
    }
    .subtitle{
      font-size: 12px;
      color: var(--muted);
      margin: 0;
      line-height: 1.35;
    }

    .panel-body{
      padding: 12px 14px;
      display: grid;
      gap: 12px;
      overflow: auto;
      min-height: 0;
    }

    .row{ display: grid; gap: 8px; }
    .row label{ font-size: 12px; color: var(--muted); }

    textarea{
      width: 100%;
      box-sizing: border-box;
      background: #fdfdfd;
      border: 1px solid rgba(17,17,17,0.1);
      border-radius: 10px;
      color: var(--text);
      padding: 10px 10px;
      outline: none;
      font-family: var(--mono);
      font-size: 12px;
      line-height: 1.35;
      min-height: 210px;
      resize: vertical;
    }
    textarea:focus{
      border-color: rgba(122,162,255,0.5);
      box-shadow: 0 0 0 3px rgba(122,162,255,0.18);
    }

    .toolbar{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }
    .btn{
      cursor: pointer;
      border: 1px solid rgba(17,17,17,0.08);
      background: #f4f6fb;
      color: var(--text);
      padding: 10px 10px;
      border-radius: 12px;
      font-size: 13px;
      font-weight: 620;
      letter-spacing: 0.2px;
      transition: transform .06s ease, background .15s ease, border-color .15s ease;
      user-select: none;
    }
    .btn:hover{ background: #e8eefc; border-color: rgba(17,17,17,0.16); }
    .btn:active{ transform: translateY(1px); }
    .btn.primary{ background: rgba(122,162,255,0.18); border-color: rgba(122,162,255,0.45); }
    .btn.primary:hover{ background: rgba(122,162,255,0.28); border-color: rgba(122,162,255,0.58); }
    .btn.danger{ background: rgba(255,107,107,0.12); border-color: rgba(255,107,107,0.38); }
    .btn.danger:hover{ background: rgba(255,107,107,0.20); border-color: rgba(255,107,107,0.5); }
    .btn.ok{ background: rgba(72,199,142,0.12); border-color: rgba(72,199,142,0.38); }
    .btn.ok:hover{ background: rgba(72,199,142,0.20); border-color: rgba(72,199,142,0.5); }

    .minirow{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; align-items: center; }

    .hint{
      font-size: 12px;
      color: var(--muted);
      line-height: 1.4;
    }

    .status{
      font-family: var(--mono);
      font-size: 12px;
      color: var(--text);
      background: #f7f8fb;
      border: 1px solid rgba(17,17,17,0.08);
      border-radius: 12px;
      padding: 10px 10px;
      line-height: 1.35;
      white-space: pre-wrap;
    }

    .right{ position: relative; min-height: 0; }
    #cy{
      width: 100%;
      height: 100%;
      background: #ffffff;
      border: 1px solid var(--border);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
    }

    .legend{
      position: absolute;
      right: 16px;
      bottom: 16px;
      width: 280px;
      max-height: 45%;
      overflow: auto;
      background: rgba(255,255,255,0.92);
      border: 1px solid rgba(17,17,17,0.08);
      border-radius: 14px;
      box-shadow: 0 10px 30px rgba(0,0,0,.12);
      padding: 10px 10px;
    }

    .rb-box{
      position: absolute;
      border: 2px dashed rgba(122,162,255,0.9);
      background: rgba(122,162,255,0.12);
      border-radius: 10px;
      pointer-events: none;
      z-index: 9999;
    }

    .legend h3{
      margin: 0 0 8px 0;
      font-size: 12px;
      color: var(--text);
      letter-spacing: .2px;
    }
    .leg-item{
      display:flex;
      align-items:center;
      gap:10px;
      padding: 6px 4px;
      border-radius: 10px;
    }
    .swatch{
      width: 14px;
      height: 14px;
      border-radius: 4px;
      border: 1px solid rgba(17,17,17,0.15);
      flex: 0 0 auto;
    }
    .leg-text{
      font-size: 12px;
      color: var(--text);
    }

    @media (max-width: 1100px){
      .app{
        grid-template-columns: 1fr;
        grid-template-rows: 380px 1fr;
      }
      .legend{ width: 320px; }
    }
    /* ============================================================
      Layout stabilization (fix drifting legend)
      ============================================================ */

    /* Always reserve scrollbar width to avoid layout width jitter */
    html { 
      overflow-y: scroll; 
    }

    /* Prevent internal scrollbars from affecting absolute positioning */
    .right { 
      overflow: hidden; 
    }

    /* Stabilize legend box model and rendering */
    .legend{
      box-sizing: border-box;
      left: auto;
      transform: translateZ(0);   /* promote to its own compositing layer */
      contain: layout paint;      /* isolate layout/paint to avoid reflow coupling */
    }

  </style>
</head>

<body>
  <div class="app">
    <div class="panel">
      <div class="panel-header">
        <p class="title">Interactive causal graph editor</p>
        <p class="subtitle">
          Render from arrow-lines (e.g., <span style="font-family:var(--mono)">A -&gt; B</span>), then interactively add/delete/rename nodes and edges.
          Coloring follows your rules (hazard tags and optional highlight lists).
        </p>
      </div>

      <div class="panel-body">
        <textarea id="txtLines" spellcheck="false" style="display:none;"></textarea>

        <div class="minirow">
          <button class="btn primary" id="btnRender" type="button">Render graph</button>
          <button class="btn" id="btnRelayout" type="button">Re-layout</button>
        </div>

        <div class="toolbar">
          <button class="btn ok" id="btnAddNode" type="button">Add node</button>
          <button class="btn ok" id="btnAddEdgeMode" type="button">Add edge (click 2 nodes)</button>
          <button class="btn" id="btnRename" type="button">Rename selected node</button>
          <button class="btn" id="btnToggleDeleted" type="button">Hide or show deleted</button>
          <button class="btn danger" id="btnDelete" type="button">Delete selected</button>
          <button class="btn" id="btnImportTrack" type="button">Import track (JSON/TXT)</button>
          <button class="btn primary" id="btnSaveBoth" type="button">Save updates (TXT)</button>
        </div>
        <input id="trackFileInput" type="file" accept=".json,.txt,application/json,text/plain" style="display:none" />

        <div class="row">
          <label>Status</label>
          <div id="status" class="status">Ready.</div>
          <div class="hint">
            Tips:
            <br>• Drag nodes to adjust locally. Click empty space to clear selection.
            <br>• “Add edge” mode: click source node then target node.
            <br>• Press Ctrl+Z to undo the last graph edit.
            <br>• Hazard-tag coloring: any node label containing <span style="font-family:var(--mono)">&lt;Pool fire&gt;</span> etc. will auto-color.
            <br>• Drag with left mouse button on empty canvas to box-select.
            <br>• Hold middle mouse button and drag to pan the canvas.
            <br>• Right click on the canvas to create a new node.

          </div>
        </div>
      </div>
    </div>

    <div class="right">
      <div id="cy"></div>

      <div class="legend" id="legendBox">
        <h3>Legend</h3>
        <div class="leg-item"><div class="swatch" style="background:{{NEUTRAL_COLOR}}"></div><div class="leg-text">Event (neutral)</div></div>
        <div class="leg-item"><div class="swatch" style="background:{{CONDITION_COLOR}}"></div><div class="leg-text">Condition (generic)</div></div>
        <div class="leg-item"><div class="swatch" style="background:{{HAZARD_COLOR}}"></div><div class="leg-text">Hazard consequence (generic)</div></div>
        <div class="leg-item">
          <div class="swatch" style="background:transparent;border:2px solid #ff4d4f;border-radius:6px;"></div>
          <div class="leg-text">Added nodes/edges (red solid)</div>
        </div>
        <div class="leg-item">
          <div class="swatch" style="background:transparent;border:2px dashed #2ecc71;border-radius:6px;"></div>
          <div class="leg-text">Delete marks (green dashed)</div>
        </div>
        <div style="height:8px"></div>
        <div id="legendHazards"></div>
      </div>
    </div>
  </div>

  <script id="cySnapshot" type="application/json"></script>
  <script id="initialLinesData" type="application/json">{{INITIAL_TEXT_JSON}}</script>
  <script id="embeddedTrackDiff" type="application/json">{{TRACK_DIFF_JSON}}</script>
  <script>
    /******************************************************************
     * Embedded data from Python
     ******************************************************************/
    function parseJsonFromScript(el){
      if (!el) return null;
      const raw = (el.textContent || "").trim();
      if (!raw) return null;
      try{
        return JSON.parse(raw);
      }catch(err){
        console.warn("Failed to parse embedded JSON", err);
        return null;
      }
    }

    const cySnapshotEl = document.getElementById("cySnapshot");
    const initialLinesEl = document.getElementById("initialLinesData");
    const trackDiffEl = document.getElementById("embeddedTrackDiff");

    const initialTextFromDom = parseJsonFromScript(initialLinesEl);
    let embeddedTrackDiff = parseJsonFromScript(trackDiffEl);

    const INITIAL_TEXT = (typeof initialTextFromDom === "string") ? initialTextFromDom : {{INITIAL_TEXT_JSON}};
    const USER_CONDITIONS = new Set({{CONDITIONS_JSON}});
    const USER_HAZARDS = new Set({{HAZARDS_JSON}});
    const CASE_ID = {{CASE_ID_JSON}};

    /******************************************************************
     * Color table — hazard-specific condition colors
     ******************************************************************/
    const HAZARD_COLORS = {{HAZARD_COLORS_JSON}};

    const COLORS = {
      condition_color: "{{CONDITION_COLOR}}",
      hazard_color: "{{HAZARD_COLOR}}",
      neutral_color: "{{NEUTRAL_COLOR}}",
      border: "#aaaaaa",
      edge: "rgba(85,85,85,0.5)"
    };

    const TRACK_FILE_NAME = `track_${CASE_ID}_final_check_output.txt`;
    const VERIFIED_FILE_NAME = `verified_${CASE_ID}_final_check_output.txt`;
    const HTML_FILE_NAME = `update_${CASE_ID}_causal_graph.html`;

    // Track the baseline text to compare future additions (populated during boot)
    const INITIAL_LINE_SET = new Set();
    const BASELINE_LINE_MAP = new Map();

    function setBaselineFromLines(lines){
      BASELINE_LINE_MAP.clear();
      INITIAL_LINE_SET.clear();
      for (const raw of lines){
        const line = (raw || "").trim();
        if (!line) continue;
        const lower = line.toLowerCase();
        INITIAL_LINE_SET.add(lower);
        if (!BASELINE_LINE_MAP.has(lower)){
          BASELINE_LINE_MAP.set(lower, line);
        }
      }
    }

    function getBaselineLines(){
      return Array.from(BASELINE_LINE_MAP.values());
    }

    /******************************************************************
     * Helpers: sanitize + parse
     ******************************************************************/
    function isDashLike(ch){
      return ["\u2010","\u2011","\u2012","\u2013","\u2014","\u2015","\u2212","\uFE58","\uFE63","\uFF0D"].includes(ch);
    }

    function sanitizeName(name){
      let out = "";
      for (const ch of name){
        if (isDashLike(ch)) out += "_";
        else out += ch;
      }
      return out;
    }

    function normalizeTextBlock(s){
      if (!s) return "";
      s = s.trim();
      if ((s.startsWith('"') && s.endsWith('"')) || (s.startsWith("'") && s.endsWith("'"))){
        s = s.slice(1, -1);
      }
      return s.replaceAll("\\r\\n","\n").replaceAll("\\n","\n").replaceAll("\r\n","\n");
    }

    function toArrowLines(rawText){
      const text = normalizeTextBlock(rawText);
      const lines = text.split("\n").map(l => l.trim()).filter(Boolean);
      const pat = /^(.+?)\s*->\s*(.+)$/;
      const out = [];
      const seen = new Set();
      for (const raw of lines){
        const m = raw.match(pat);
        if (!m) continue;
        const src = m[1].replace(/\s+/g, " ").replace(/\.$/, "").trim();
        const dst = m[2].replace(/\s+/g, " ").replace(/\.$/, "").trim();
        const line = `${src} -> ${dst}`;
        const key = line.toLowerCase();
        if (!seen.has(key)){
          seen.add(key);
          out.push(line);
        }
      }
      return out;
    }

    function normalizeArrowLineInput(raw){
      if (Array.isArray(raw)){
        return toArrowLines(raw.join("\n"));
      }
      if (typeof raw === "string"){
        return toArrowLines(raw);
      }
      return [];
    }

    function normalizeHazardTag(tag){
      tag = (tag || "").trim().toLowerCase();

      // collapse whitespace
      tag = tag.replace(/\s+/g, " ").trim();

      // remove trailing " number" or " number 12"
      tag = tag.replace(/(?:\s+number(?:\s*\d+)?)$/, "");

      // remove trailing digits: " 12" / "-12" / "_12"
      tag = tag.replace(/[\s\-_]*\d+$/, "");

      // collapse again
      tag = tag.replace(/\s+/g, " ").trim();

      return tag;
    }

    function normalizeHazardConsequenceName(s){
      s = (s || "").trim().toLowerCase();
      s = s.replace(/\s+/g, " ").trim();

      // drop trailing "... number" / "... number 12"
      s = s.replace(/(?:\s+number(?:\s*\d+)?)$/, "").trim();

      // drop trailing "(12)"
      s = s.replace(/\s*\(\s*\d+\s*\)\s*$/, "").trim();

      // drop trailing digits: " 12" / "-12" / "_12"
      s = s.replace(/[\s\-_]*\d+$/, "").trim();

      s = s.replace(/\s+/g, " ").trim();
      return s;
    }

function isHazardConsequenceNode(label){
  const norm = normalizeHazardConsequenceName(label);
  return Object.prototype.hasOwnProperty.call(HAZARD_COLORS, norm);
}

    function extractHazardTag(label){
      const lt = label.indexOf("<");
      const gt = label.indexOf(">");
      if (lt !== -1 && gt !== -1 && gt > lt){
        const raw = label.slice(lt + 1, gt);
        const tag = normalizeHazardTag(raw);
        return tag || null;
      }
      return null;
    }

    function wrapLabel(label, width = 28){
      const words = label.split(" ");
      const lines = [];
      let line = "";
      for (const w of words){
        const next = line ? (line + " " + w) : w;
        if (next.length > width){
          if (line) lines.push(line);
          line = w;
        } else {
          line = next;
        }
      }
      if (line) lines.push(line);
      return lines.join("\n");
    }

    function composeLineText(sourceLabel, targetLabel){
      return `${sourceLabel} -> ${targetLabel}`;
    }

    /******************************************************************
     * Build elements from arrow lines
     ******************************************************************/
    function buildElementsFromLines(lines){
      // First, gather all node labels (sanitized) and build auto-tag condition nodes
      const labels = [];
      for (const ln of lines){
        if (!ln.includes("->")) continue;
        const parts = ln.split("->");
        const src = sanitizeName(parts[0].trim());
        const dst = sanitizeName(parts.slice(1).join("->").trim());
        labels.push(src, dst);
      }

      // De-duplicate labels case-insensitively (like Python)
      const uniq = [];
      const seen = new Set();
      for (const l of labels){
        const k = l.toLowerCase();
        if (!seen.has(k)){
          seen.add(k);
          uniq.push(l);
        }
      }

      // auto condition nodes = those containing <...>
      const autoCond = new Set();
      for (const l of uniq){
        if (extractHazardTag(l)) autoCond.add(l.toLowerCase());
      }

      // Effective conditions/hazards sets (match Python logic)
      const conditionSet = new Set([...USER_CONDITIONS, ...autoCond]);
      const hazardSet = new Set([...USER_HAZARDS].filter(x => !autoCond.has(x)));

      // ID map (label lower -> node id)
      const idMap = new Map();
      const labelById = new Map();
      function getId(label){
        const key = label.toLowerCase();
        if (!idMap.has(key)){
          const nid = "n" + idMap.size;
          idMap.set(key, nid);
          labelById.set(nid, label);
        }
        return idMap.get(key);
      }

      // nodes
      const nodes = [];
      for (const l of uniq){
        const label = l;
        const lower = label.toLowerCase();
        const hazardTag = extractHazardTag(label);

        let fill = COLORS.neutral_color;
        if (hazardTag){
          fill = (HAZARD_COLORS[hazardTag] || COLORS.condition_color);
        } else if (isHazardConsequenceNode(label)){
          fill = COLORS.hazard_color;
        } else if (hazardSet.has(lower)){
          fill = COLORS.hazard_color;
        } else if (conditionSet.has(lower)){
          fill = COLORS.condition_color;
        }

        const id = getId(label);
        nodes.push({
          data: {
            id,
            label,
            labelWrapped: wrapLabel(label, 28),
            hazardTag: hazardTag || "",
            fill
          }
        });
      }

      // edges (dedupe)
      const edges = [];
      const eSeen = new Set();
      for (const ln of lines){
        if (!ln.includes("->")) continue;
        const parts = ln.split("->");
        const srcLabel = sanitizeName(parts[0].trim());
        const dstLabel = sanitizeName(parts.slice(1).join("->").trim());
        const sId = getId(srcLabel);
        const tId = getId(dstLabel);
        const ek = (sId + "->" + tId).toLowerCase();
        if (eSeen.has(ek)) continue;
        eSeen.add(ek);
        edges.push({
          data: {
            id: "e" + edges.length,
            source: sId,
            target: tId,
            label: "",
            lineText: composeLineText(srcLabel, dstLabel)
          }
        });
      }

      return { nodes, edges };
    }

    function buildLinesFromTrackDiff(diff){
      if (!diff || typeof diff !== "object"){
        return { finalLines: [], baselineLines: [] };
      }
      const original = normalizeArrowLineInput(diff.original || diff.baseline || []);
      const additions = normalizeArrowLineInput(
        diff.added || diff.addedLines || diff.newLines || []
      );
      const deletions = normalizeArrowLineInput(
        diff.deleted || diff.deletedLines || diff.removed || []
      );
      const deletionKeys = new Set(deletions.map(line => line.toLowerCase()));

      const combined = [];
      const seen = new Set();
      function pushLine(line){
        const key = line.toLowerCase();
        if (seen.has(key)) return;
        seen.add(key);
        combined.push(line);
      }
      original.forEach(pushLine);
      additions.forEach(pushLine);
      const finalLines = combined;
      return { finalLines, baselineLines: original };
    }

    /******************************************************************
     * Cytoscape initialization
     ******************************************************************/
    cytoscape.use(cytoscapeDagre);

    const cy = cytoscape({
      container: document.getElementById("cy"),
      elements: [],
      wheelSensitivity: 3,
      selectionType: "additive",
      boxSelectionEnabled: true,
      userPanningEnabled: false,
      style: [
        {
          selector: "node",
          style: {
            "shape": "round-rectangle",
            "background-color": "transparent",
            "background-opacity": 0,
            "border-color": "transparent",
            "border-width": 0,
            "border-opacity": 0,
            "corner-radius": 0,
            "label": "data(labelWrapped)",
            "text-wrap": "wrap",
            "text-max-width": 220,
            "text-valign": "center",
            "text-halign": "center",
            "font-size": 18,
            "color": "#111",
            "padding": "10px",
            "width": "label",
            "height": "label",
          }
        },
        {
          selector: "node:selected",
          style: {
            "border-width": 0,
            "border-color": "transparent",
            "shadow-blur": 12,
            "shadow-color": "rgba(122,162,255,0.55)",
            "shadow-opacity": 0.9,
          }
        },
        {
          selector: "edge",
          style: {
            "curve-style": "bezier",
            "control-point-step-size": 40,
            "line-color": COLORS.edge,
            "target-arrow-shape": "triangle",
            "target-arrow-color": COLORS.edge,
            "arrow-scale": 0.85,
            "width": 2,
            "label": "data(label)",
            "font-size": 10,
            "text-rotation": "autorotate",
            "text-background-color": "rgba(255,255,255,0.65)",
            "text-background-opacity": 1,
            "text-background-padding": 2,
          }
        },
        {
          selector: "edge:selected",
          style: {
            "line-color": "rgba(122,162,255,0.85)",
            "target-arrow-color": "rgba(122,162,255,0.85)",
            "width": 3
          }
        },
        {
          selector: "node.added-highlight",
          style: {
            "border-width": 0,
            "border-color": "transparent",
            "border-style": "solid"
          }
        },
        {
          selector: "edge.added-highlight",
          style: {
            "line-color": "#ff4d4f",
            "target-arrow-color": "#ff4d4f",
            "line-style": "solid",
            "width": 3
          }
        },
        {
          selector: "node.delete-mark",
          style: {
            "border-width": 0,
            "border-color": "transparent",
            "border-style": "dashed"
          }
        },
        {
          selector: "edge.delete-mark",
          style: {
            "line-color": "#2ecc71",
            "target-arrow-color": "#2ecc71",
            "line-style": "dashed",
            "width": 3
          }
        }
      ],
      layout: { name: "grid" }
    });

    (function enableLeftRubberbandSelect(){
      const container = cy.container();
      const rightPane = document.querySelector(".right");
      if (!container || !rightPane) return;

      let rb = null;
      let dragging = false;
      let start = { x: 0, y: 0 };

      function ptFromEvent(e){
        const rect = container.getBoundingClientRect();
        return { x: e.clientX - rect.left, y: e.clientY - rect.top };
      }
      function rectFrom(a, b){
        const x1 = Math.min(a.x, b.x), y1 = Math.min(a.y, b.y);
        const x2 = Math.max(a.x, b.x), y2 = Math.max(a.y, b.y);
        return { x1, y1, x2, y2, w: x2 - x1, h: y2 - y1 };
      }
      function ensureBox(){
        if (rb) return rb;
        rb = document.createElement("div");
        rb.className = "rb-box";
        rightPane.appendChild(rb);
        return rb;
      }
      function removeBox(){
        if (rb && rb.parentNode) rb.parentNode.removeChild(rb);
        rb = null;
      }
      function updateBox(r){
        const box = ensureBox();
        box.style.left = (r.x1 + container.offsetLeft) + "px";
        box.style.top  = (r.y1 + container.offsetTop) + "px";
        box.style.width  = r.w + "px";
        box.style.height = r.h + "px";
      }
      function selectInRect(r){
        if (r.w < 6 && r.h < 6) return;

        cy.$(":selected").unselect(); 

        const selectedNodes = cy.nodes().filter(n => {
          const p = n.renderedPosition();
          return p.x >= r.x1 && p.x <= r.x2 && p.y >= r.y1 && p.y <= r.y2;
        });

        selectedNodes.select();
        selectedNodes.connectedEdges().select(); 
        setStatus(`Box-selected: ${selectedNodes.length} nodes (+ attached edges).`);
      }

      cy.on("mousedown", (evt) => {
        const oe = evt.originalEvent;
        if (!oe) return;
        if (oe.button !== 0) return;    
        if (evt.target !== cy) return;  

        dragging = true;
        start = ptFromEvent(oe);
        updateBox(rectFrom(start, start));
        oe.preventDefault();
      });

      cy.on("mousemove", (evt) => {
        if (!dragging) return;
        const oe = evt.originalEvent;
        if (!oe) return;
        updateBox(rectFrom(start, ptFromEvent(oe)));
        oe.preventDefault();
      });

      cy.on("mouseup", (evt) => {
        if (!dragging) return;
        const oe = evt.originalEvent;
        dragging = false;
        if (!oe){ removeBox(); return; }
        const r = rectFrom(start, ptFromEvent(oe));
        removeBox();
        selectInRect(r);
        oe.preventDefault();
      });

      container.addEventListener("mouseleave", () => {
        if (!dragging) return;
        dragging = false;
        removeBox();
      });
    })();

    /******************************************************************
    * Force wheel zoom on #cy container (robust across browsers)
    ******************************************************************/
    (function enableWheelZoom(){
      const container = cy.container();
      if (!container) return;

      // 确保 Cytoscape 本身不禁用缩放（兜底）
      cy.userZoomingEnabled(true);

      container.addEventListener("wheel", (e) => {
        // 关键：阻止页面滚动，把 wheel 留给图
        e.preventDefault();

        // deltaY > 0 通常是向下滚（缩小），< 0 放大
        const current = cy.zoom();

        // 这个系数手感比较接近常见缩放（可微调 1.001）
        const factor = Math.pow(1.001, -e.deltaY);
        let next = current * factor;

        // 限制缩放范围，避免飞走
        const minZoom = 0.08;
        const maxZoom = 5;
        next = Math.max(minZoom, Math.min(maxZoom, next));

        // 以鼠标所在点为中心缩放
        const rect = container.getBoundingClientRect();
        const rp = { x: e.clientX - rect.left, y: e.clientY - rect.top };

        cy.zoom({ level: next, renderedPosition: rp });
      }, { passive: false });
    })();


    /******************************************************************
    * Middle mouse drag => pan the canvas
    ******************************************************************/
    (function enableMiddleMousePan(){
      const container = cy.container();
      if (!container) return;

      let panning = false;
      let last = { x: 0, y: 0 };

      function onDown(e){

        if (e.button !== 1) return;


        panning = true;
        last = { x: e.clientX, y: e.clientY };

        e.preventDefault();
      }

      function onMove(e){
        if (!panning) return;

        const dx = e.clientX - last.x;
        const dy = e.clientY - last.y;
        last = { x: e.clientX, y: e.clientY };

        cy.panBy({ x: dx, y: dy });

        e.preventDefault();
      }

      function onUp(e){
        if (!panning) return;
        if (e.button !== 1) return;

        panning = false;
        e.preventDefault();
      }

      container.addEventListener("mousedown", onDown, { passive: false });
      window.addEventListener("mousemove", onMove, { passive: false });
      window.addEventListener("mouseup", onUp, { passive: false });

      container.addEventListener("mouseleave", () => { panning = false; });

      container.addEventListener("contextmenu", (e) => e.preventDefault());
    })();


    const BASELINE_NODE_MAP = new Map();

    function setBaselineNodesFromGraph(){
      BASELINE_NODE_MAP.clear();
      cy.nodes().forEach(node => {
        const label = node.data("label");
        if (!label) return;
        const key = label.toLowerCase();
        if (!BASELINE_NODE_MAP.has(key)){
          BASELINE_NODE_MAP.set(key, label);
        }
      });
    }

    const SELECTION_MODES = {
      DEFAULT: "default",
      ADD: "add",
      DELETE: "delete"
    };
    let currentSelectionMode = SELECTION_MODES.DEFAULT;

    function selectionStylesFor(mode){
      switch (mode){
        case SELECTION_MODES.ADD:
          return {
            node: {
              "border-width": 3,
              "border-color": "#ff4d4f",
              "border-style": "solid",
              "shadow-blur": 12,
              "shadow-color": "rgba(255,77,79,0.55)",
              "shadow-opacity": 0.9,
            },
            edge: {
              "line-color": "#ff4d4f",
              "target-arrow-color": "#ff4d4f",
              "line-style": "solid",
              "width": 3
            }
          };
        case SELECTION_MODES.DELETE:
          return {
            node: {
              "border-width": 3,
              "border-color": "#2ecc71",
              "border-style": "dashed",
              "shadow-blur": 12,
              "shadow-color": "rgba(46,204,113,0.55)",
              "shadow-opacity": 0.9,
            },
            edge: {
              "line-color": "#2ecc71",
              "target-arrow-color": "#2ecc71",
              "line-style": "dashed",
              "width": 3
            }
          };
        default:
          return {
            node: {
              "border-width": 3,
              "border-color": "#7aa2ff",
              "border-style": "solid",
              "shadow-blur": 12,
              "shadow-color": "rgba(122,162,255,0.55)",
              "shadow-opacity": 0.9,
            },
            edge: {
              "line-color": "rgba(122,162,255,0.85)",
              "target-arrow-color": "rgba(122,162,255,0.85)",
              "line-style": "solid",
              "width": 3
            }
          };
      }
    }

    function applySelectionModeStyles(){
      const styles = selectionStylesFor(currentSelectionMode);
      cy.style()
        .selector("node:selected").style(styles.node)
        .selector("edge:selected").style(styles.edge)
        .update();
    }

    function setSelectionMode(mode){
      if (currentSelectionMode === mode) return;
      currentSelectionMode = mode;
      applySelectionModeStyles();
    }

    applySelectionModeStyles();

    function runLayout(){
      cy.layout({
        name: "dagre",
        rankDir: "LR",
        nodeSep: 30,
        rankSep: 80,
        edgeSep: 10,
        spacingFactor: 1.05,
        padding: 30
      }).run();
    }

    function renderGraphFromArrowLines(rawInput, options = {}){
      const { updateBaseline = false, baselineLines = null, silent = false, statusMessage = null } = options;
      const lines = normalizeArrowLineInput(rawInput);
      if (!lines.length){
        if (!silent){
          alert("No valid 'A -> B' lines found.");
        }
        return false;
      }
      const { nodes, edges } = buildElementsFromLines(lines);
      if (cy.elements().length){
        pushUndoState();
      }
      cy.elements().remove();
      cy.add(nodes);
      cy.add(edges);
      runLayout();
      setBaselineNodesFromGraph();
      const textarea = document.getElementById("txtLines");
      if (textarea){
        textarea.value = lines.join("\n");
      }
      if (updateBaseline){
        const baseCandidate = baselineLines && baselineLines.length ? normalizeArrowLineInput(baselineLines) : lines;
        setBaselineFromLines(baseCandidate.length ? baseCandidate : lines);
      }
      setStatus(statusMessage || `Rendered: ${nodes.length} nodes, ${edges.length} edges (deduplicated).`);
      return true;
    }

    /******************************************************************
     * UI + interactions: add/delete/rename nodes and add edges
     ******************************************************************/
    const statusEl = document.getElementById("status");
    function setStatus(msg){ statusEl.textContent = msg; }

    const undoStack = [];
    const MAX_UNDO_STATES = 50;
    const HISTORY_DATA_KEY = "__trackHistory";

    function clearHistoryFlag(elements){
      if (!elements || !elements.length) return;
      elements.forEach(ele => ele.removeData(HISTORY_DATA_KEY));
    }

    function tagAsHistory(elements, tag){
      if (!elements || !elements.length) return;
      elements.forEach(ele => ele.data(HISTORY_DATA_KEY, tag));
    }

    function markAsAdded(elements){
      if (!elements || !elements.length) return;
      const activeElements = elements.filter(ele => !ele.hasClass("delete-mark"));
      if (!activeElements || !activeElements.length) return;
      clearHistoryFlag(activeElements);
      activeElements.addClass("added-highlight");
    }

    function markAsDeleted(elements){
      if (!elements || !elements.length) return;
      clearHistoryFlag(elements);
      elements.removeClass("added-highlight");
      elements.addClass("delete-mark");
    }

    /******************************************************************
    * Deleted (green dashed) visibility + clear marks
    ******************************************************************/
    let deletedVisible = {{DELETED_VISIBLE_JSON}};

    function setDeletedVisibility(visible){
      deletedVisible = !!visible;

      const nodeDisplay = deletedVisible ? "element" : "none";
      const edgeDisplay = deletedVisible ? "element" : "none";

      cy.style()
        .selector("node.delete-mark").style({ "display": nodeDisplay })
        .selector("edge.delete-mark").style({ "display": edgeDisplay })
        .update();

      const btn = document.getElementById("btnToggleDeleted");
      if (btn){
        btn.textContent = deletedVisible ? "Hide or show deleted" : "Show deleted";
      }

      setStatus(deletedVisible ? "Deleted marks are visible." : "Deleted marks are hidden.");
    }

    const btnToggleDeleted = document.getElementById("btnToggleDeleted");
    if (btnToggleDeleted){
      btnToggleDeleted.addEventListener("click", () => {
        setDeletedVisibility(!deletedVisible); // ✅ toggle
      });
    }

    setDeletedVisibility(true);

    function updateEdgeLineText(edge){
      if (!edge || !edge.isEdge()) return;
      const sourceLabel = edge.source().data("label");
      const targetLabel = edge.target().data("label");
      if (sourceLabel && targetLabel){
        edge.data("lineText", composeLineText(sourceLabel, targetLabel));
      }
    }

    function refreshEdgesForNode(node){
      if (!node || !node.isNode()) return;
      node.connectedEdges().forEach(updateEdgeLineText);
    }

    function cloneElementsSnapshot(){
      const elements = cy.elements().jsons().map(el => JSON.parse(JSON.stringify(el)));
      return {
        elements,
        pan: { ...cy.pan() },
        zoom: cy.zoom()
      };
    }

    function pushUndoState(snapshotOverride = null){
      const snapshot = snapshotOverride || cloneElementsSnapshot();
      undoStack.push(snapshot);
      if (undoStack.length > MAX_UNDO_STATES){
        undoStack.shift();
      }
    }

    function restoreSnapshot(snapshot){
      if (!snapshot) return;
      const currentPan = { ...cy.pan() };
      const currentZoom = cy.zoom();
      cy.$(":selected").unselect();
      cy.elements().remove();
      const elements = snapshot.elements || snapshot;
      if (Array.isArray(elements)){
        cy.add(elements);
      } else if (elements && (elements.nodes || elements.edges)){
        if (elements.nodes) cy.add(elements.nodes);
        if (elements.edges) cy.add(elements.edges);
      }
      if (currentPan) cy.pan(currentPan);
      if (typeof currentZoom === "number") cy.zoom(currentZoom);
      setSelectionMode(SELECTION_MODES.DEFAULT);
      runLayout();
    }

    function undoLastAction(){
      if (!undoStack.length){
        setStatus("Nothing to undo.");
        return;
      }
      const snapshot = undoStack.pop();
      restoreSnapshot(snapshot);
      setStatus("Undo applied.");
    }

    document.addEventListener("keydown", (evt) => {
      if (!evt.key) return;
      if ((evt.ctrlKey || evt.metaKey) && !evt.shiftKey && evt.key.toLowerCase() === "z"){
        const target = evt.target;
        const tag = target && target.tagName ? target.tagName.toUpperCase() : "";
        const isEditable = (target && target.isContentEditable) || tag === "INPUT" || tag === "TEXTAREA";
        if (isEditable) return;
        evt.preventDefault();
        undoLastAction();
      }
    });

    let edgeMode = false;
    let edgeSource = null;
    let addNodeHighlightTimer = null;

    let dragUndoSnapshot = null;
    let dragUndoCommitted = false;

    cy.on("grab", "node", (evt) => {
      const node = evt.target;
      node.scratch("_dragStartPos", { ...node.position() });
      if (!dragUndoSnapshot){
        dragUndoSnapshot = cloneElementsSnapshot();
        dragUndoCommitted = false;
      }
    });

    cy.on("dragfree", "node", (evt) => {
      const node = evt.target;
      const startPos = node.scratch("_dragStartPos");
      if (node.removeScratch){
        node.removeScratch("_dragStartPos");
      } else {
        node.scratch("_dragStartPos", null);
      }
      const pos = node.position();
      const moved = startPos && (startPos.x !== pos.x || startPos.y !== pos.y);
      if (dragUndoSnapshot && !dragUndoCommitted && moved){
        pushUndoState(dragUndoSnapshot);
        dragUndoCommitted = true;
        setStatus("Node position updated (Ctrl+Z to undo).");
      }
      if (!cy.$(":grabbed").length){
        dragUndoSnapshot = null;
        dragUndoCommitted = false;
      }
    });

    document.getElementById("btnAddEdgeMode").addEventListener("click", () => {
      if (edgeSource){
        edgeSource.unselect();
      }
      cy.$(":selected").unselect();
      edgeMode = true;
      edgeSource = null;
      setSelectionMode(SELECTION_MODES.ADD);
      setStatus("Edge mode: click source node, then target node.");
    });

    cy.on("tap", (evt) => {
      if (evt.target === cy){
        if (edgeMode && edgeSource){
          edgeSource.unselect();
          edgeSource = null;
          setStatus("Edge mode: click source node, then target node.");
        } else if (edgeMode){
          edgeMode = false;
          setSelectionMode(SELECTION_MODES.DEFAULT);
          setStatus("Ready.");
        } else {
          setStatus("Ready.");
        }
      }
    });

    cy.on("tap", "node", (evt) => {
      const node = evt.target;
      if (!edgeMode) return;

      if (!edgeSource){
        edgeSource = node;
        node.select();
        setSelectionMode(SELECTION_MODES.ADD);
        setStatus(`Edge mode: source="${node.data("label")}". Now click target node.`);
      } else {
        const target = node;
        if (edgeSource.id() === target.id()){
          setStatus("Edge mode cancelled: cannot connect a node to itself.");
          edgeSource.unselect();
          edgeSource = null;
          edgeMode = false;
          setSelectionMode(SELECTION_MODES.DEFAULT);
          return;
        }

        const exists = cy.edges().some(e => e.source().id() === edgeSource.id() && e.target().id() === target.id());
        let addedEdge = false;
        if (exists){
          setStatus("Edge already exists. Edge mode ended.");
        } else {
          pushUndoState();
          const newEdge = cy.add({
            group: "edges",
            data: {
              id: "e" + Date.now(),
              source: edgeSource.id(),
              target: target.id(),
              label: "",
              lineText: composeLineText(edgeSource.data("label"), target.data("label"))
            }
          });
          markAsAdded(newEdge);
          setStatus(`Added edge: "${edgeSource.data("label")}" -> "${target.data("label")}".`);
          addedEdge = true;
        }

        edgeSource.unselect();
        edgeSource = null;
        edgeMode = false;
        setSelectionMode(SELECTION_MODES.DEFAULT);
        if (addedEdge){
          runLayout();
        }
      }
    });

    document.getElementById("btnAddNode").addEventListener("click", () => {
      if (addNodeHighlightTimer){
        clearTimeout(addNodeHighlightTimer);
        addNodeHighlightTimer = null;
      }
      if (edgeMode){
        if (edgeSource){
          edgeSource.unselect();
        }
        edgeMode = false;
        edgeSource = null;
      }
      setSelectionMode(SELECTION_MODES.ADD);
      const name = prompt("Node name (label):");
      if (!name){
        setSelectionMode(SELECTION_MODES.DEFAULT);
        return;
      }
      const label = sanitizeName(name.trim());
      if (!label){
        setSelectionMode(SELECTION_MODES.DEFAULT);
        return;
      }

      const dup = cy.nodes().some(n => (n.data("label") || "").toLowerCase() === label.toLowerCase());
      if (dup){
        alert("A node with the same label already exists (case-insensitive).");
        setSelectionMode(SELECTION_MODES.DEFAULT);
        return;
      }

      const hazardTag = extractHazardTag(label);
      const lower = label.toLowerCase();
      const autoCond = hazardTag ? true : false;
      const conditionSet = new Set([...USER_CONDITIONS, ...(autoCond ? [lower] : [])]);
      const hazardSet = new Set([...USER_HAZARDS].filter(x => !(autoCond && x === lower)));

      let fill = COLORS.neutral_color;
      if (hazardTag){
        fill = (HAZARD_COLORS[hazardTag] || COLORS.condition_color);
      } else if (hazardSet.has(lower)){
        fill = COLORS.hazard_color;
      } else if (conditionSet.has(lower)){
        fill = COLORS.condition_color;
      }

      pushUndoState();

      const addedNode = cy.add({
        group: "nodes",
        data: {
          id: "n" + Date.now(),
          label,
          labelWrapped: wrapLabel(label, 28),
          hazardTag: hazardTag || "",
          fill
        }
      });

      if (addedNode && addedNode.length){
        cy.$(":selected").unselect();
        addedNode[0].select();
        markAsAdded(addedNode);
      }

      setStatus(`Added node: "${label}"`);
      runLayout();
      addNodeHighlightTimer = setTimeout(() => {
        setSelectionMode(SELECTION_MODES.DEFAULT);
        addNodeHighlightTimer = null;
      }, 800);
    });

    /******************************************************************
    * Right-click two nodes to connect (context edge)
    ******************************************************************/
    let rcEdgeSource = null;

    cy.on("cxttap", "node", (evt) => {
      const node = evt.target;

      // 阻止浏览器右键菜单（保险）
      if (evt.originalEvent && typeof evt.originalEvent.preventDefault === "function"){
        evt.originalEvent.preventDefault();
      }

      // 如果你正在使用左键“Add edge mode”，避免混淆：右键连边先不介入
      if (typeof edgeMode !== "undefined" && edgeMode){
        setStatus("Edge mode is active (left-click). Finish it or click empty space to exit.");
        return;
      }

      // 右键即选中节点（可选：保留已有多选的话就不要 unselect）
      cy.$(":selected").unselect();
      node.select();

      // 第一次右键：记录源节点
      if (!rcEdgeSource){
        rcEdgeSource = node;
        setSelectionMode(SELECTION_MODES.ADD); // 用你已有的红色高亮风格提示“正在连边”
        setStatus(`Right-click connect: source="${node.data("label")}". Now right-click the target node.`);
        return;
      }

      // 第二次右键：目标节点
      const target = node;

      // 同一个节点：取消
      if (rcEdgeSource.id() === target.id()){
        setStatus("Right-click connect cancelled: cannot connect a node to itself.");
        rcEdgeSource = null;
        setSelectionMode(SELECTION_MODES.DEFAULT);
        cy.$(":selected").unselect();
        return;
      }

      // 已存在：提示并结束
      const exists = cy.edges().some(e => e.source().id() === rcEdgeSource.id() && e.target().id() === target.id());
      if (exists){
        setStatus("Edge already exists. Right-click connect ended.");
        rcEdgeSource = null;
        setSelectionMode(SELECTION_MODES.DEFAULT);
        cy.$(":selected").unselect();
        return;
      }

      // add edge
      pushUndoState();
      const newEdge = cy.add({
        group: "edges",
        data: {
          id: "e" + Date.now(),
          source: rcEdgeSource.id(),
          target: target.id(),
          label: "",
          lineText: composeLineText(rcEdgeSource.data("label"), target.data("label"))
        }
      });

      markAsAdded(newEdge);
      setStatus(`Added edge (right-click): "${rcEdgeSource.data("label")}" -> "${target.data("label")}".`);

      rcEdgeSource = null;
      setSelectionMode(SELECTION_MODES.DEFAULT);
      cy.$(":selected").unselect();
    });

    cy.on("cxttap", (evt) => {
      if (evt.target !== cy){
        return;
      }
      if (evt.originalEvent && typeof evt.originalEvent.preventDefault === "function"){
        evt.originalEvent.preventDefault();
      }

      if (edgeSource){
        edgeSource.unselect();
      }
      edgeMode = false;
      edgeSource = null;
      setSelectionMode(SELECTION_MODES.DEFAULT);

      const name = prompt("Node name (label):");
      if (!name) return;

      const label = sanitizeName(name.trim());
      if (!label) return;

      const dup = cy.nodes().some(n => (n.data("label") || "").toLowerCase() === label.toLowerCase());
      if (dup){
        alert("A node with the same label already exists (case-insensitive).");
        return;
      }

      const hazardTag = extractHazardTag(label);
      const lower = label.toLowerCase();
      const autoCond = hazardTag ? true : false;
      const conditionSet = new Set([...USER_CONDITIONS, ...(autoCond ? [lower] : [])]);
      const hazardSet = new Set([...USER_HAZARDS].filter(x => !(autoCond && x === lower)));

      let fill = COLORS.neutral_color;
      if (hazardTag){
        fill = (HAZARD_COLORS[hazardTag] || COLORS.condition_color);
      } else if (hazardSet.has(lower)){
        fill = COLORS.hazard_color;
      } else if (conditionSet.has(lower)){
        fill = COLORS.condition_color;
      }

      pushUndoState();

      const nodeOptions = {
        group: "nodes",
        data: {
          id: "n" + Date.now(),
          label,
          labelWrapped: wrapLabel(label, 28),
          hazardTag: hazardTag || "",
          fill
        }
      };

      if (evt.position && typeof evt.position.x === "number" && typeof evt.position.y === "number"){
        nodeOptions.position = { x: evt.position.x, y: evt.position.y };
      }

      const addedNode = cy.add(nodeOptions);
      if (addedNode && addedNode.length){
        cy.$(":selected").unselect();
        addedNode[0].select();
        markAsAdded(addedNode);
      }

      setStatus(`Added node via right-click: "${label}"`);
    });

    document.getElementById("btnDelete").addEventListener("click", () => {
      const sel = cy.$(":selected");
      if (!sel || sel.length === 0){
        alert("Select a node or edge first.");
        return;
      }
      setSelectionMode(SELECTION_MODES.DELETE);
      pushUndoState();
      const nodes = sel.filter(ele => ele.isNode());
      if (nodes.length){
        markAsDeleted(nodes);
        markAsDeleted(nodes.connectedEdges());
      }
      const edges = sel.filter(ele => ele.isEdge());
      if (edges.length){
        markAsDeleted(edges);
      }
      cy.$(":selected").unselect();
      setSelectionMode(SELECTION_MODES.DEFAULT);
      setStatus("Marked as deleted (green dashed).");
    });

    document.getElementById("btnRename").addEventListener("click", () => {
      const sel = cy.$("node:selected");
      if (!sel || sel.length !== 1){
        alert("Select exactly one node to rename.");
        return;
      }
      const node = sel[0];
      const oldLabel = node.data("label");
      const name = prompt("New node name (label):", oldLabel);
      if (!name) return;

      const label = sanitizeName(name.trim());
      if (!label) return;

      const dup = cy.nodes().some(n => n.id() !== node.id() && (n.data("label") || "").toLowerCase() === label.toLowerCase());
      if (dup){
        alert("Another node already has that label (case-insensitive).");
        return;
      }

      if (label === oldLabel){
        setStatus("Rename cancelled: label unchanged.");
        return;
      }

      const hazardTag = extractHazardTag(label);
      const lower = label.toLowerCase();
      const autoCond = hazardTag ? true : false;
      const conditionSet = new Set([...USER_CONDITIONS, ...(autoCond ? [lower] : [])]);
      const hazardSet = new Set([...USER_HAZARDS].filter(x => !(autoCond && x === lower)));

      let fill = COLORS.neutral_color;
      if (hazardTag){
        fill = (HAZARD_COLORS[hazardTag] || COLORS.condition_color);
      } else if (hazardSet.has(lower)){
        fill = COLORS.hazard_color;
      } else if (conditionSet.has(lower)){
        fill = COLORS.condition_color;
      }

      pushUndoState();

      node.data("label", label);
      node.data("labelWrapped", wrapLabel(label, 28));
      node.data("hazardTag", hazardTag || "");
      node.data("fill", fill);
      refreshEdgesForNode(node);

      setStatus(`Renamed node: "${oldLabel}" -> "${label}"`);
      runLayout();
    });

    document.getElementById("btnRelayout").addEventListener("click", () => {
      runLayout();
      setStatus("Re-layout applied.");
    });

    document.getElementById("btnRender").addEventListener("click", () => {
      const raw = document.getElementById("txtLines").value;
      renderGraphFromArrowLines(raw);
    });
    /******************************************************************
    * Export helpers
    ******************************************************************/
    function collectArrowLinesFromGraph(){
      const lines = [];
      const seen = new Set();

      cy.edges().forEach(e => {
        if (e.hasClass("delete-mark") || e.source().hasClass("delete-mark") || e.target().hasClass("delete-mark")){
          return;
        }
        const s = e.source().data("label");
        const t = e.target().data("label");
        if (!s || !t) return;

        const stored = e.data("lineText");
        const line = stored || composeLineText(s, t);
        const key = line.toLowerCase();
        if (!seen.has(key)){
          seen.add(key);
          lines.push(line);
        }
      });

      // Stable output: alphabetical order (can be replaced by topological order)
      lines.sort((a,b) => a.toLowerCase().localeCompare(b.toLowerCase()));
      return lines;
    }

    function collectAddedArrowLines(lines){
      return lines.filter(line => !INITIAL_LINE_SET.has(line.toLowerCase()));
    }

    function collectNodeLabelsByClass(selector, { skipHistory = true } = {}){
      const seen = new Set();
      const labels = [];
      cy.nodes(selector).forEach(node => {
        if (skipHistory && node.data(HISTORY_DATA_KEY)) return;
        const label = node.data("label");
        if (!label) return;
        const key = label.toLowerCase();
        if (!seen.has(key)){
          seen.add(key);
          labels.push(label);
        }
      });
      labels.sort((a,b) => a.toLowerCase().localeCompare(b.toLowerCase()));
      return labels;
    }

    function collectEdgeLinesByClass(selector, { skipHistory = true } = {}){
      const seen = new Set();
      const lines = [];
      cy.edges(selector).forEach(edge => {
        if (skipHistory && edge.data(HISTORY_DATA_KEY)) return;
        const stored = edge.data("lineText") || composeLineText(edge.source().data("label"), edge.target().data("label"));
        if (!stored) return;
        const key = stored.toLowerCase();
        if (seen.has(key)){
          return;
        }
        seen.add(key);
        lines.push(stored);
      });
      lines.sort((a,b) => a.toLowerCase().localeCompare(b.toLowerCase()));
      return lines;
    }

    function buildTrackPayload(){
      return {
        original: getBaselineLines(),
        added: collectEdgeLinesByClass(".added-highlight"),
        deleted: collectEdgeLinesByClass(".delete-mark"),
        addedNodes: collectNodeLabelsByClass(".added-highlight"),
        deletedNodes: collectNodeLabelsByClass(".delete-mark")
      };
    }

    function downloadText(filename, content){
      const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.style.display = "none";
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    }

    function encodeJsonForScript(value){
      return JSON.stringify(value).replace(/</g, "\\u003c");
    }

    function persistEmbeddedTrackDiff(diff){
      embeddedTrackDiff = diff || null;
      if (trackDiffEl){
        trackDiffEl.textContent = encodeJsonForScript(embeddedTrackDiff || {});
      }
    }

    function downloadHtmlFromCurrentDom(filename, currentText, trackPayload){
      const textarea = document.getElementById("txtLines");
      const previousTextareaValue = textarea ? textarea.value : null;
      if (textarea){
        textarea.value = currentText;
      }

      const cyDiv = document.getElementById("cy");
      let cyDomSnapshot = null;
      if (cyDiv){
        cyDomSnapshot = {
          html: cyDiv.innerHTML,
          className: cyDiv.className,
          styleAttr: cyDiv.getAttribute("style")
        };
        cyDiv.innerHTML = "";
        cyDiv.className = "";
        cyDiv.removeAttribute("style");
      }

      let prevSnapshotText = null;
      if (cySnapshotEl){
        prevSnapshotText = cySnapshotEl.textContent || "";
        try{
          cySnapshotEl.textContent = encodeJsonForScript(cy.json());
        }catch(err){
          console.warn("Failed to serialize Cytoscape snapshot", err);
        }
      }

      let prevInitialLines = null;
      if (initialLinesEl){
        prevInitialLines = initialLinesEl.textContent || "";
        initialLinesEl.textContent = encodeJsonForScript(currentText);
      }

      let prevTrackText = null;
      if (trackDiffEl){
        prevTrackText = trackDiffEl.textContent || "";
        trackDiffEl.textContent = encodeJsonForScript(trackPayload || {});
      }

      const html = "<!doctype html>\n" + document.documentElement.outerHTML;

      if (cySnapshotEl && prevSnapshotText !== null){
        cySnapshotEl.textContent = prevSnapshotText;
      }
      if (initialLinesEl && prevInitialLines !== null){
        initialLinesEl.textContent = prevInitialLines;
      }
      if (trackDiffEl && prevTrackText !== null){
        trackDiffEl.textContent = prevTrackText;
      }
      if (textarea && previousTextareaValue !== null){
        textarea.value = previousTextareaValue;
      }
      if (cyDiv && cyDomSnapshot){
        cyDiv.innerHTML = cyDomSnapshot.html;
        cyDiv.className = cyDomSnapshot.className || "";
        if (cyDomSnapshot.styleAttr !== null){
          cyDiv.setAttribute("style", cyDomSnapshot.styleAttr);
        } else {
          cyDiv.removeAttribute("style");
        }
      }

      downloadText(filename, html);
    }

    function clearChangeMarkers(){
      cy.nodes().forEach(node => {
        node.removeClass("added-highlight delete-mark");
        node.removeData(HISTORY_DATA_KEY);
      });
      cy.edges().forEach(edge => {
        edge.removeClass("added-highlight delete-mark");
        edge.removeData(HISTORY_DATA_KEY);
      });
    }

    function findNodesByLabel(label){
      const lower = (label || "").toLowerCase();
      if (!lower) return cy.collection();
      return cy.nodes().filter(node => (node.data("label") || "").toLowerCase() === lower);
    }

    function findEdgesByLine(line){
      const lower = (line || "").toLowerCase();
      if (!lower) return cy.collection();
      return cy.edges().filter(edge => {
        const stored = edge.data("lineText") || composeLineText(edge.source().data("label"), edge.target().data("label"));
        return stored && stored.toLowerCase() === lower;
      });
    }

    function applyTrackDiffHighlights(diff){
      if (!diff) return false;
      clearChangeMarkers();
      const addedNodes = Array.isArray(diff.addedNodes) ? diff.addedNodes : [];
      const deletedNodes = Array.isArray(diff.deletedNodes) ? diff.deletedNodes : [];
      const addedLines = Array.isArray(diff.addedLines) ? diff.addedLines : (Array.isArray(diff.added) ? diff.added : []);
      const deletedLines = Array.isArray(diff.deletedLines) ? diff.deletedLines : (Array.isArray(diff.deleted) ? diff.deleted : []);

      addedNodes.forEach(label => {
        const nodes = findNodesByLabel(label);
        if (nodes.length){
          markAsAdded(nodes);
          tagAsHistory(nodes, "added");
        }
      });
      deletedNodes.forEach(label => {
        const nodes = findNodesByLabel(label);
        if (nodes.length){
          markAsDeleted(nodes);
          tagAsHistory(nodes, "deleted");
        }
      });
      addedLines.forEach(line => {
        const edges = findEdgesByLine(line);
        if (edges.length){
          markAsAdded(edges);
          tagAsHistory(edges, "added");
        }
      });
      deletedLines.forEach(line => {
        const edges = findEdgesByLine(line);
        if (edges.length){
          markAsDeleted(edges);
          tagAsHistory(edges, "deleted");
        }
      });
      return true;
    }

    async function fetchTrackDiffFromFile(){
      if (location.protocol === "file:") {
        return null;
      }

      if (!TRACK_FILE_NAME) return null;
      try{
        const res = await fetch(`${TRACK_FILE_NAME}?t=${Date.now()}`, { cache: "no-store" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const text = await res.text();
        if (!text.trim()) return null;
        return JSON.parse(text);
      }catch(err){
        console.warn("Track TXT fetch failed", err);
        return null;
      }
    }

    async function loadAndApplyTrackDiff(){
      const diffFromFile = await fetchTrackDiffFromFile();
      const diff = diffFromFile || embeddedTrackDiff || null;
      if (diff){
        const { finalLines, baselineLines } = buildLinesFromTrackDiff(diff);
        if (finalLines.length){
          renderGraphFromArrowLines(finalLines, {
            updateBaseline: true,
            baselineLines: baselineLines.length ? baselineLines : finalLines,
            statusMessage: diffFromFile ? "Rendered graph from fetched track diff." : "Rendered graph from embedded track diff."
          });
        }
        applyTrackDiffHighlights(diff);
      }
    }

    function readSavedSnapshot(){
      return parseJsonFromScript(cySnapshotEl);
    }

    function applySavedSnapshot(){
      const snapshot = readSavedSnapshot();
      if (!snapshot) return false;
      try{
        cy.json(snapshot);
        cy.resize();
        return true;
      }catch(err){
        console.warn("Failed to apply saved snapshot", err);
        return false;
      }
    }

    function hydrateEditorBaseline(){
      const textarea = document.getElementById("txtLines");
      const prefilled = textarea && textarea.value && textarea.value.trim().length > 0;
      const effective = prefilled ? textarea.value : INITIAL_TEXT;
      if (textarea){
        textarea.value = effective;
      }
      const baselineLines = toArrowLines(effective);
      setBaselineFromLines(baselineLines);
      return effective;
    }

    /******************************************************************
    * One-click export: Verified TXT + Track TXT + HTML snapshot
    ******************************************************************/
    document.getElementById("btnSaveBoth").addEventListener("click", () => {
      const arrowLines = collectArrowLinesFromGraph();
      const additionsOnly = collectAddedArrowLines(arrowLines);
      const updatedText = arrowLines.join("\n");
      const trackPayload = buildTrackPayload();

      downloadText(VERIFIED_FILE_NAME, updatedText);
      downloadText(TRACK_FILE_NAME, JSON.stringify(trackPayload, null, 2));

      setTimeout(() => {
        downloadHtmlFromCurrentDom(HTML_FILE_NAME, updatedText, trackPayload);
        setStatus(`Saved: ${VERIFIED_FILE_NAME}, ${TRACK_FILE_NAME}, ${HTML_FILE_NAME} (additions=${additionsOnly.length})`);
      }, 200);
    });


    /******************************************************************
     * Legend rendering
     ******************************************************************/
    function renderLegendHazards(){
      const box = document.getElementById("legendHazards");
      const keys = Object.keys(HAZARD_COLORS);
      keys.sort((a,b) => a.localeCompare(b));
      box.innerHTML = keys.map(k => `
        <div class="leg-item">
          <div class="swatch" style="background:${HAZARD_COLORS[k]}"></div>
          <div class="leg-text">Condition &lt;${k}&gt;</div>
        </div>
      `).join("");
    }
    renderLegendHazards();

    /******************************************************************
     * Boot
     ******************************************************************/
    function boot(){
      hydrateEditorBaseline();
      const loadedSnapshot = applySavedSnapshot();
      const finalizeBoot = () => {
        setBaselineNodesFromGraph();
        loadAndApplyTrackDiff();
      };
      if (!loadedSnapshot){
        document.getElementById("btnRender").click();
        setTimeout(finalizeBoot, 200);
      } else {
        setStatus("Loaded saved graph.");
        finalizeBoot();
      }
    }

    const trackFileInput = document.getElementById("trackFileInput");
    const importTrackBtn = document.getElementById("btnImportTrack");
    if (importTrackBtn){
      importTrackBtn.addEventListener("click", () => {
        if (!trackFileInput){
          alert("Track file input unavailable in this build.");
          return;
        }
        trackFileInput.value = "";
        trackFileInput.click();
      });
    }

    if (trackFileInput){
      trackFileInput.addEventListener("change", () => {
        const file = trackFileInput.files && trackFileInput.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = () => {
          try{
            const text = (reader.result || "").toString().trim();
            if (!text){
              alert("Selected file is empty.");
              return;
            }
            let parsed = null;
            try{
              parsed = JSON.parse(text);
            }catch(err){
              parsed = null;
            }

            let handled = false;
            if (parsed && typeof parsed === "object" && !Array.isArray(parsed) &&
                (parsed.original || parsed.added || parsed.addedLines || parsed.deleted || parsed.deletedLines || parsed.addedNodes || parsed.deletedNodes)){
              const { finalLines, baselineLines } = buildLinesFromTrackDiff(parsed);
              if (!finalLines.length){
                alert("Track diff file does not contain any valid arrow lines.");
                handled = true;
              } else {
                const rendered = renderGraphFromArrowLines(finalLines, {
                  updateBaseline: true,
                  baselineLines: baselineLines.length ? baselineLines : finalLines,
                  statusMessage: `Rendered imported track from "${file.name}".`
                });
                if (rendered){
                  const applied = applyTrackDiffHighlights(parsed);
                  if (applied){
                    persistEmbeddedTrackDiff(parsed);
                    setStatus(`Imported track diff from "${file.name}".`);
                  } else {
                    alert("Track diff applied, but no matching nodes/edges were found to highlight.");
                  }
                }
                handled = true;
              }
            } else if (Array.isArray(parsed)){
              const arrLines = normalizeArrowLineInput(parsed);
              if (!arrLines.length){
                alert("JSON array did not contain recognizable 'A -> B' lines.");
              } else {
                renderGraphFromArrowLines(arrLines, {
                  updateBaseline: true,
                  statusMessage: `Rendered imported lines from "${file.name}".`
                });
              }
              handled = true;
            }

            if (!handled){
              const textLines = toArrowLines(text);
              if (!textLines.length){
                alert("File is neither valid JSON diff nor arrow-line text.");
                return;
              }
              renderGraphFromArrowLines(textLines, {
                updateBaseline: true,
                statusMessage: `Rendered imported lines from "${file.name}".`
              });
            }
          } finally {
            trackFileInput.value = "";
          }
        };
        reader.onerror = () => {
          alert("Failed to read selected file.");
          trackFileInput.value = "";
        };
        reader.readAsText(file);
      });
    }

    boot();
  </script>
</body>
</html>
"""


_JSON_GRAPH_HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{{PAGE_TITLE}}</title>
  <script src="https://unpkg.com/cytoscape/dist/cytoscape.min.js"></script>
  <script src="https://unpkg.com/dagre@0.8.5/dist/dagre.min.js"></script>
  <script src="https://unpkg.com/cytoscape-dagre/cytoscape-dagre.js"></script>
  <style>
    body {
      margin: 0;
      font-family: Arial, sans-serif;
      background: #f7f7f7;
      color: #222;
    }
    .page {
      --left-panel-width: 280px;
      --right-panel-width: 380px;
      display: grid;
      grid-template-columns: var(--left-panel-width) 8px minmax(0, 1fr) 8px var(--right-panel-width);
      gap: 12px;
      height: 100vh;
      padding: 16px;
      box-sizing: border-box;
    }
    .page.right-panel-collapsed {
      --right-panel-width: 0px;
      grid-template-columns: var(--left-panel-width) 8px minmax(0, 1fr);
    }
    .page.left-panel-collapsed {
      --left-panel-width: 0px;
      grid-template-columns: minmax(0, 1fr) 8px var(--right-panel-width);
    }
    .page.left-panel-collapsed.right-panel-collapsed {
      grid-template-columns: minmax(0, 1fr);
    }
    .canvas {
      position: relative;
      overflow: hidden;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
    }
    .panel, .canvas {
      background: #fff;
      border: 1px solid #ddd;
      border-radius: 12px;
      box-shadow: 0 8px 24px rgba(0,0,0,0.08);
    }
    .panel {
      min-width: 0;
      grid-column: 1;
    }
    .detail-panel {
      background: #fff;
      border: 1px solid #ddd;
      border-radius: 12px;
      box-shadow: 0 8px 24px rgba(0,0,0,0.08);
      padding: 16px;
      overflow: hidden;
      min-width: 0;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      grid-column: 5;
    }
    .detail-panel-header {
      display: grid;
      gap: 14px;
      padding-bottom: 14px;
      border-bottom: 1px solid #ececec;
      background: #fff;
      position: relative;
      z-index: 2;
    }
    .left-resizer {
      grid-column: 2;
    }
    .canvas {
      grid-column: 3;
    }
    .right-resizer {
      grid-column: 4;
    }
    .page.left-panel-collapsed .canvas {
      grid-column: 1;
    }
    .page.left-panel-collapsed .right-resizer {
      grid-column: 2;
    }
    .page.left-panel-collapsed .detail-panel {
      grid-column: 3;
    }
    .page.right-panel-collapsed .canvas {
      grid-column: 3;
    }
    .page.right-panel-collapsed .panel {
      grid-column: 1;
    }
    .page.left-panel-collapsed.right-panel-collapsed .canvas {
      grid-column: 1;
    }
    .page.right-panel-collapsed .detail-panel,
    .page.left-panel-collapsed .panel {
      display: none;
    }
    .canvas-toolbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 12px 14px;
      border-bottom: 1px solid #ececec;
      background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
    }
    .toolbar-group {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }
    .toolbar-button {
      border: 1px solid #d1d5db;
      border-radius: 999px;
      padding: 7px 12px;
      font: inherit;
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
      background: #fff;
      color: #111827;
    }
    .toolbar-button:hover {
      background: #f3f4f6;
    }
    .toolbar-button.active {
      border-color: #bfdbfe;
      background: #eff6ff;
      color: #1d4ed8;
    }
    .toolbar-hint {
      font-size: 12px;
      color: #6b7280;
      white-space: nowrap;
    }
    .canvas-body {
      position: relative;
      min-height: 0;
    }
    .page-resizer {
      position: relative;
      border-radius: 999px;
      background: transparent;
      cursor: col-resize;
      user-select: none;
      touch-action: none;
    }
    .page-resizer::before {
      content: "";
      position: absolute;
      top: 12px;
      bottom: 12px;
      left: 50%;
      width: 4px;
      transform: translateX(-50%);
      border-radius: 999px;
      background: #e5e7eb;
      transition: background 0.15s ease;
    }
    .page-resizer:hover::before,
    .page-resizer.dragging::before {
      background: #93c5fd;
    }
    .page.right-panel-collapsed .right-resizer,
    .page.left-panel-collapsed .left-resizer {
      visibility: hidden;
    }
    .detail-tabs {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      margin-bottom: 0;
    }
    .detail-tab {
      width: 100%;
      min-width: 0;
      border: 1px solid #d1d5db;
      border-radius: 999px;
      padding: 7px 12px;
      font: inherit;
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
      background: #fff;
      color: #111827;
    }
    .detail-tab.active {
      border-color: #bfdbfe;
      background: #eff6ff;
      color: #1d4ed8;
    }
    .detail-panel-scroll {
      min-height: 0;
      overflow: auto;
      padding-top: 16px;
      position: relative;
      z-index: 1;
    }
    .detail-panel-body {
      min-height: 0;
    }
    .detail-summary {
      margin: 0;
      padding: 10px 12px;
      border: 1px solid #dbeafe;
      border-radius: 12px;
      background: #f8fbff;
    }
    .detail-summary-label {
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: #64748b;
      margin-bottom: 4px;
    }
    .detail-summary-value {
      font-size: 14px;
      line-height: 1.5;
      color: #0f172a;
      word-break: break-word;
    }
    .panel-view {
      display: none;
    }
    .panel-view.active {
      display: block;
    }
    .revision-panel {
      display: grid;
      gap: 12px;
    }
    .revision-title {
      margin: 0;
      font-size: 18px;
      font-weight: 700;
      color: #111827;
    }
    .revision-subtitle {
      margin: 0;
      font-size: 13px;
      line-height: 1.5;
      color: #6b7280;
    }
    .revision-list {
      display: grid;
      gap: 10px;
    }
    .revision-empty {
      color: #6b7280;
      font-size: 13px;
      line-height: 1.5;
    }
    .revision-card {
      border: 1px solid #e5e7eb;
      border-radius: 14px;
      background: #f9fafb;
      padding: 12px;
      display: grid;
      gap: 8px;
    }
    .revision-card.relevant {
      border-color: #60a5fa;
      background: #eff6ff;
      box-shadow: inset 0 0 0 1px rgba(96, 165, 250, 0.25);
    }
    .revision-head {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 8px;
    }
    .revision-kind {
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.3px;
      text-transform: uppercase;
      color: #1f2937;
    }
    .revision-badges {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }
    .revision-badge {
      display: inline-flex;
      align-items: center;
      padding: 2px 8px;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 600;
      border: 1px solid transparent;
      white-space: nowrap;
    }
    .revision-badge.severity-high {
      color: #991b1b;
      background: #fee2e2;
      border-color: #fecaca;
    }
    .revision-badge.severity-medium {
      color: #92400e;
      background: #fef3c7;
      border-color: #fde68a;
    }
    .revision-badge.severity-low {
      color: #1f2937;
      background: #e5e7eb;
      border-color: #d1d5db;
    }
    .revision-badge.confidence-high,
    .revision-badge.confidence-medium,
    .revision-badge.confidence-low {
      color: #1d4ed8;
      background: #dbeafe;
      border-color: #bfdbfe;
    }
    .revision-text {
      font-size: 13px;
      line-height: 1.5;
      color: #111827;
    }
    .revision-meta {
      display: grid;
      gap: 6px;
    }
    .revision-meta-row {
      font-size: 12px;
      line-height: 1.45;
      color: #4b5563;
    }
    .revision-meta-row strong {
      color: #111827;
      font-weight: 700;
    }
    .revision-actions {
      display: flex;
      gap: 8px;
      justify-content: flex-end;
      flex-wrap: wrap;
    }
    .revision-actions button {
      border: 1px solid #d1d5db;
      border-radius: 10px;
      padding: 7px 12px;
      font: inherit;
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
      background: #fff;
      color: #111827;
    }
    .revision-actions button:hover {
      background: #f3f4f6;
    }
    .revision-actions .accept-btn {
      border-color: #86efac;
      background: #f0fdf4;
      color: #166534;
    }
    .revision-actions .accept-btn:hover {
      background: #dcfce7;
    }
    .revision-actions .reject-btn {
      border-color: #fecaca;
      background: #fef2f2;
      color: #991b1b;
    }
    .revision-actions .reject-btn:hover {
      background: #fee2e2;
    }
    .revision-actions button:disabled {
      opacity: 0.55;
      cursor: not-allowed;
    }
    .revision-state {
      font-size: 12px;
      font-weight: 600;
      line-height: 1.4;
    }
    .revision-state.accepted {
      color: #166534;
    }
    .revision-state.rejected {
      color: #991b1b;
    }
    .panel {
      padding: 16px;
      overflow: auto;
    }
    .panel h1 {
      font-size: 18px;
      margin: 0 0 12px 0;
    }
    .panel p {
      font-size: 13px;
      line-height: 1.5;
      margin: 0 0 10px 0;
    }
    .panel-section {
      margin-top: 18px;
      padding-top: 18px;
      border-top: 1px solid #ececec;
    }
    .panel-section h3 {
      margin: 0 0 10px 0;
      font-size: 15px;
    }
    .panel button {
      border: 1px solid #d7d7d7;
      border-radius: 8px;
      padding: 8px 10px;
      font: inherit;
      background: #fff;
      color: #111827;
    }
    .form-grid textarea {
      min-height: 74px;
      resize: vertical;
    }
    .panel button {
      margin-top: 10px;
      cursor: pointer;
      background: #eef4ff;
      border-color: #cddcff;
      font-weight: 600;
    }
    .panel button:hover {
      background: #e2ecff;
    }
    .panel-status {
      margin-top: 10px;
      font-size: 12px;
      line-height: 1.5;
      color: #4b5563;
      min-height: 18px;
    }
    .panel-hint {
      font-size: 12px;
      line-height: 1.5;
      color: #4b5563;
      margin-top: 8px;
    }
    .modal-backdrop {
      position: fixed;
      inset: 0;
      background: rgba(17, 24, 39, 0.42);
      display: none;
      align-items: center;
      justify-content: center;
      z-index: 9999;
      padding: 16px;
      box-sizing: border-box;
    }
    .modal-backdrop.open {
      display: flex;
    }
    .modal-card {
      width: min(520px, 100%);
      background: #fff;
      border-radius: 14px;
      box-shadow: 0 20px 50px rgba(0,0,0,0.18);
      padding: 18px;
      box-sizing: border-box;
    }
    .modal-card h3 {
      margin: 0 0 8px 0;
      font-size: 18px;
    }
    .modal-card p {
      margin: 0 0 14px 0;
      font-size: 13px;
      line-height: 1.5;
      color: #4b5563;
    }
    .modal-grid {
      display: grid;
      gap: 10px;
    }
    .modal-grid label {
      display: grid;
      gap: 6px;
      font-size: 12px;
      color: #4b5563;
    }
    .modal-grid select,
    .modal-grid input,
    .modal-grid textarea {
      width: 100%;
      box-sizing: border-box;
      border: 1px solid #d7d7d7;
      border-radius: 8px;
      padding: 8px 10px;
      font: inherit;
      background: #fff;
      color: #111827;
    }
    .modal-grid textarea {
      min-height: 80px;
      resize: vertical;
    }
    .modal-error {
      display: none;
      margin-top: 12px;
      padding: 10px 12px;
      border-radius: 8px;
      background: #fef2f2;
      border: 1px solid #fecaca;
      color: #b91c1c;
      font-size: 12px;
      line-height: 1.5;
      white-space: pre-wrap;
    }
    .modal-error.open {
      display: block;
    }
    .field-invalid {
      border-color: #dc2626 !important;
      box-shadow: 0 0 0 2px rgba(220, 38, 38, 0.12);
    }
    .modal-actions {
      display: flex;
      justify-content: flex-end;
      gap: 10px;
      margin-top: 14px;
    }
    .modal-actions button {
      border: 1px solid #d7d7d7;
      border-radius: 8px;
      padding: 8px 12px;
      font: inherit;
      cursor: pointer;
      background: #fff;
    }
    .modal-actions button.primary {
      background: #eef4ff;
      border-color: #cddcff;
      font-weight: 600;
    }
    .legend-item {
      display: flex;
      align-items: center;
      gap: 10px;
      margin: 8px 0;
      font-size: 13px;
    }
    .swatch {
      width: 14px;
      height: 14px;
      border-radius: 4px;
      border: 1px solid rgba(0,0,0,0.15);
      flex: 0 0 auto;
    }
    .detail-title {
      font-size: 18px;
      margin: 0 0 12px 0;
    }
    .detail-subtitle {
      font-size: 13px;
      line-height: 1.5;
      color: #4b5563;
      margin: 0 0 14px 0;
    }
    .detail-empty {
      font-size: 13px;
      line-height: 1.6;
      color: #6b7280;
    }
    .detail-section {
      margin-top: 14px;
      padding-top: 14px;
      border-top: 1px solid #ececec;
    }
    .detail-section:first-child {
      margin-top: 0;
      padding-top: 0;
      border-top: 0;
    }
    .detail-label {
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: #6b7280;
      margin-bottom: 4px;
    }
    .detail-value {
      font-size: 14px;
      line-height: 1.5;
      color: #111827;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .detail-form {
      display: grid;
      gap: 14px;
    }
    .detail-form label {
      display: grid;
      gap: 6px;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: #6b7280;
    }
    .detail-form input,
    .detail-form select,
    .detail-form textarea {
      width: 100%;
      box-sizing: border-box;
      border: 1px solid #d1d5db;
      border-radius: 10px;
      padding: 10px 12px;
      font: inherit;
      color: #111827;
      background: #fff;
    }
    .detail-form textarea {
      min-height: 96px;
      resize: vertical;
    }
    .detail-form input[readonly] {
      background: #f3f4f6;
      color: #6b7280;
    }
    .detail-actions {
      display: flex;
      justify-content: flex-end;
      gap: 10px;
    }
    .detail-actions button {
      border: 1px solid #cddcff;
      border-radius: 10px;
      padding: 9px 14px;
      font: inherit;
      font-weight: 600;
      color: #1d4ed8;
      background: #eef4ff;
      cursor: pointer;
    }
    .detail-actions button:hover {
      background: #e2ecff;
    }
    .detail-status {
      font-size: 13px;
      line-height: 1.5;
      color: #4b5563;
    }
    .detail-status.error {
      color: #b91c1c;
    }
    .detail-status.success {
      color: #166534;
    }
    #cy {
      width: 100%;
      height: 100%;
    }
    #node-label-overlay {
      position: absolute;
      inset: 0;
      pointer-events: none;
      overflow: hidden;
    }
    #node-measure-box {
      position: absolute;
      left: -10000px;
      top: -10000px;
      width: 260px;
      visibility: hidden;
      pointer-events: none;
    }
    .node-measure-card {
      box-sizing: border-box;
      width: 260px;
      border-radius: 8px;
      border: 1px solid rgba(31, 41, 55, 0.18);
      background: #ffffff;
      box-shadow: none;
      overflow: hidden;
    }
    .node-measure-header {
      box-sizing: border-box;
      font-weight: 700;
      font-size: 18px;
      line-height: 1.25;
      color: #ffffff;
      text-align: center;
      white-space: pre-line;
      padding: 8px 10px 7px;
      margin: 0 0 6px 0;
    }
    .node-measure-body {
      box-sizing: border-box;
      font-size: 18px;
      line-height: 1.25;
      color: #111827;
      white-space: normal;
      text-align: left;
      padding: 8px 10px 14px;
    }
    .node-measure-line + .node-measure-line {
      margin-top: 3px;
    }
    .node-overlay {
      --node-card-radius: 8px;
      position: absolute;
      box-sizing: border-box;
      display: flex;
      flex-direction: column;
      color: #111827;
      line-height: 1.25;
      font-size: 14px;
      overflow: hidden;
      border-radius: var(--node-card-radius);
      border: 1px solid rgba(31, 41, 55, 0.18);
      background: #ffffff;
      box-shadow: none;
    }
    .node-overlay.deleted-overlay {
      opacity: 0.62;
      filter: grayscale(0.75) saturate(0.7);
      text-decoration: line-through;
    }
    .node-overlay-label {
      font-weight: 700;
      white-space: pre-line;
      color: #ffffff;
      text-align: center;
    }
    .node-overlay-name {
      box-sizing: border-box;
      flex: 1;
      background: #ffffff;
      color: #111827;
      line-height: 1.25;
      white-space: normal;
      overflow: visible;
      overflow-wrap: anywhere;
      text-align: left;
    }
    .node-overlay-name-line + .node-overlay-name-line {
      margin-top: 3px;
    }
    @media (max-width: 1100px) {
      .page {
        --left-panel-width: 240px;
        --right-panel-width: 320px;
      }
      .toolbar-hint {
        display: none;
      }
    }
  </style>
</head>
<body>
  <div class="page">
    <div class="panel">
      <h1>{{PAGE_TITLE}}</h1>
      <p>Nodes come from <code>identify_accident_scenario_output.json</code>.</p>
      <p>Edges come from <code>causal_edge_linking_output.json</code>.</p>
      <p>Node text shows <code>label</code> and <code>name</code>. Edge text shows the relation.</p>
      <div class="legend-item"><span class="swatch" style="background:#ddf5df"></span>Entity</div>
      <div class="legend-item"><span class="swatch" style="background:#d8ebff"></span>Condition</div>
      <div class="legend-item"><span class="swatch" style="background:#f3e7ff"></span>Event</div>
      <div class="legend-item"><span class="swatch" style="background:#ffd6d6"></span>Hazard consequence</div>
      <p id="summary"></p>
      <div class="panel-section">
        <h3>Add Node</h3>
        <button id="add-node-button" type="button">Add Node</button>
        <div class="panel-hint">Click the button to open a dialog and fill in node fields.</div>
        <div id="node-form-status" class="panel-status"></div>
      </div>
      <div class="panel-section">
        <h3>Add Edge</h3>
        <button id="add-edge-button" type="button">Add Edge</button>
        <div class="panel-hint">Click the button, then left-click two nodes in order. Left-drag empty canvas to box-select. Right-drag the canvas to pan.</div>
        <div id="edge-form-status" class="panel-status"></div>
      </div>
      <div class="panel-section">
        <h3>Deletion</h3>
        <button id="delete-selected-button" type="button">Delete Selected</button>
        <button id="toggle-deleted-button" type="button">Hide Deleted</button>
        <div class="panel-hint">Delete keeps visual traces instead of removing elements permanently.</div>
        <div id="delete-form-status" class="panel-status"></div>
      </div>
      <div class="panel-section">
        <h3>Export</h3>
        <button id="save-updates-button" type="button">Save Updates</button>
        <div class="panel-hint">Download the current graph as JSON and HTML, including change traces.</div>
        <div id="save-form-status" class="panel-status"></div>
      </div>
    </div>
    <div class="page-resizer left-resizer" data-resize-target="left" aria-hidden="true"></div>
    <div class="canvas">
      <div class="canvas-toolbar">
        <div class="toolbar-group">
          <button id="toggle-left-panel-button" class="toolbar-button" type="button">Tools</button>
          <button id="show-details-button" class="toolbar-button" type="button">Details</button>
          <button id="show-revisions-button" class="toolbar-button" type="button">Revisions</button>
          <button id="hide-right-panel-button" class="toolbar-button" type="button">Hide Panel</button>
        </div>
        <div class="toolbar-hint">Drag the rails to resize side panels.</div>
      </div>
      <div class="canvas-body">
        <div id="cy"></div>
        <div id="node-label-overlay"></div>
      </div>
    </div>
    <div class="page-resizer right-resizer" data-resize-target="right" aria-hidden="true"></div>
    <div class="detail-panel">
      <div class="detail-panel-header">
        <div>
          <h2 class="detail-title">Details</h2>
          <p class="detail-subtitle">Click a node or edge to inspect all available fields.</p>
        </div>
        <div class="detail-tabs">
          <button id="detail-tab-button" class="detail-tab active" type="button">Details</button>
          <button id="revision-tab-button" class="detail-tab" type="button">Revisions</button>
        </div>
        <div id="detail-summary" class="detail-summary">
          <div class="detail-summary-label">Selection</div>
          <div id="detail-summary-value" class="detail-summary-value">Review suggestions are open by default.</div>
        </div>
      </div>
      <div class="detail-panel-scroll">
        <div class="detail-panel-body">
          <div id="detail-view" class="panel-view active">
            <div id="detail-content" class="detail-empty">Nothing selected.</div>
          </div>
          <div id="revision-view" class="panel-view">
            <div class="revision-panel">
              <h2 class="revision-title">Suggested Revisions</h2>
              <p class="revision-subtitle">Review-only preview of graph revision suggestions for this case.</p>
              <div id="revision-content" class="revision-empty">No review suggestions loaded.</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
  <div id="modal-backdrop" class="modal-backdrop"></div>
  <div id="node-measure-box"></div>
  <script>
    cytoscape.use(cytoscapeDagre);
    const elements = {{GRAPH_ELEMENTS_JSON}};
    const schemaForm = {{SCHEMA_FORM_JSON}};
    const reviewSuggestions = {{REVIEW_SUGGESTIONS_JSON}};
    const initialRevisionDecisions = {{REVISION_DECISIONS_JSON}};
    const originalDocumentHtml = document.documentElement.outerHTML;
    document.getElementById("summary").textContent =
      `${elements.nodes.length} nodes, ${elements.edges.length} edges`;

    const cy = cytoscape({
      container: document.getElementById("cy"),
      elements: [...elements.nodes, ...elements.edges],
      wheelSensitivity: 2,
      userZoomingEnabled: true,
      selectionType: "additive",
      boxSelectionEnabled: true,
      userPanningEnabled: false,
      style: [
        {
          selector: "node",
          style: {
            "shape": "round-rectangle",
            "background-color": "transparent",
            "background-opacity": 0,
            "border-color": "transparent",
            "border-width": 0,
            "border-opacity": 0,
            "corner-radius": 0,
            "label": "",
            "width": "data(nodeWidth)",
            "height": "data(nodeHeight)",
          }
        },
        {
          selector: "edge",
          style: {
            "curve-style": "bezier",
            "line-color": "#6d6d6d",
            "target-arrow-shape": "triangle",
            "target-arrow-color": "#6d6d6d",
            "arrow-scale": 0.9,
            "width": 2,
            "label": "data(label)",
            "font-size": 18,
            "color": "#111",
            "text-rotation": "autorotate",
            "text-margin-y": -10,
            "text-background-color": "#ffffff",
            "text-background-opacity": 1,
            "text-background-padding": 3
          }
        },
        {
          selector: "edge.edge-label-hidden",
          style: {
            "label": ""
          }
        },
        {
          selector: "node.added-highlight",
          style: {
            "border-color": "transparent",
            "border-width": 0
          }
        },
        {
          selector: "edge.added-highlight",
          style: {
            "line-color": "#dc2626",
            "target-arrow-color": "#dc2626",
            "width": 3
          }
        },
        {
          selector: "node.delete-mark",
          style: {
            "border-color": "transparent",
            "border-width": 0,
            "border-style": "dashed",
            "background-opacity": 0.35
          }
        },
        {
          selector: "edge.delete-mark",
          style: {
            "line-color": "#b45309",
            "target-arrow-color": "#b45309",
            "line-style": "dashed",
            "opacity": 0.45,
            "width": 3
          }
        },
        {
          selector: ":selected",
          style: {
            "border-color": "transparent",
            "line-color": "#2563eb",
            "target-arrow-color": "#2563eb"
          }
        },
        {
          selector: ".added-highlight:selected",
          style: {
            "border-color": "transparent",
            "line-color": "#dc2626",
            "target-arrow-color": "#dc2626"
          }
        }
      ],
      layout: {
        name: "dagre",
        rankDir: "LR",
        nodeSep: 40,
        rankSep: 100,
        edgeSep: 16,
        padding: 30
      }
    });

    const page = document.querySelector(".page");
    const overlay = document.getElementById("node-label-overlay");
    const nodeMeasureBox = document.getElementById("node-measure-box");
    const detailContent = document.getElementById("detail-content");
    const revisionContent = document.getElementById("revision-content");
    const detailView = document.getElementById("detail-view");
    const revisionView = document.getElementById("revision-view");
    const detailPanelScroll = document.querySelector(".detail-panel-scroll");
    const detailSummaryValue = document.getElementById("detail-summary-value");
    const detailTabButton = document.getElementById("detail-tab-button");
    const revisionTabButton = document.getElementById("revision-tab-button");
    const toggleLeftPanelButton = document.getElementById("toggle-left-panel-button");
    const showDetailsButton = document.getElementById("show-details-button");
    const showRevisionsButton = document.getElementById("show-revisions-button");
    const hideRightPanelButton = document.getElementById("hide-right-panel-button");
    const leftResizer = document.querySelector(".left-resizer");
    const rightResizer = document.querySelector(".right-resizer");
    const addNodeButton = document.getElementById("add-node-button");
    const nodeFormStatus = document.getElementById("node-form-status");
    const addEdgeButton = document.getElementById("add-edge-button");
    const edgeFormStatus = document.getElementById("edge-form-status");
    const deleteSelectedButton = document.getElementById("delete-selected-button");
    const toggleDeletedButton = document.getElementById("toggle-deleted-button");
    const deleteFormStatus = document.getElementById("delete-form-status");
    const saveUpdatesButton = document.getElementById("save-updates-button");
    const saveFormStatus = document.getElementById("save-form-status");
    const modalBackdrop = document.getElementById("modal-backdrop");
    let edgeCreationSource = null;
    let edgeCreationMode = false;
    let deletedVisible = {{DELETED_VISIBLE_JSON}};
    const undoStack = [];
    const redoStack = [];
    const MAX_HISTORY = 50;
    let dragUndoSnapshot = null;
    let dragUndoCommitted = false;
    const revisionDecisions = { ...initialRevisionDecisions };
    const revisionGeneratedEdges = {};
    let revisionFocus = null;
    let activeRightPanelTab = "details";
    let leftPanelVisible = true;
    let rightPanelVisible = false;
    let initialViewportApplied = false;

    function canonicalizeNodeType(nodeType) {
      const normalized = String(nodeType || "").trim().toLowerCase();
      if (normalized === "intermediateevent") return "entity";
      return normalized;
    }

    function normalizeRevisionDecisionEntry(value) {
      if (value && typeof value === "object" && !Array.isArray(value)) {
        return {
          status: String(value.status || "").trim().toLowerCase(),
          reviewReason: String(value.review_reason || "").trim(),
        };
      }
      return {
        status: String(value || "").trim().toLowerCase(),
        reviewReason: "",
      };
    }

    function getRevisionDecisionStatus(key) {
      return normalizeRevisionDecisionEntry(revisionDecisions[key]).status;
    }

    function getRevisionDecisionReason(key) {
      return normalizeRevisionDecisionEntry(revisionDecisions[key]).reviewReason;
    }

    function setRevisionDecision(key, status, reviewReason = "") {
      revisionDecisions[key] = {
        status: String(status || "").trim().toLowerCase(),
        review_reason: String(reviewReason || "").trim(),
      };
    }

    function setDetailSummary(text) {
      if (!detailSummaryValue) return;
      detailSummaryValue.textContent = text || "Nothing selected.";
    }

    function ensureNameVisibleInitialViewport() {
      if (initialViewportApplied) return;
      initialViewportApplied = true;
      cy.fit(cy.elements(), 40);
      const minNameZoom = 0.65;
      if (cy.zoom() < minNameZoom) {
        cy.zoom(minNameZoom);
        cy.center(cy.elements());
      }
      syncNodeOverlay();
    }

    function refreshCanvasViewport() {
      window.requestAnimationFrame(() => {
        cy.resize();
        syncNodeOverlay();
      });
    }

    function setRightPanelTab(tab) {
      activeRightPanelTab = tab === "revisions" ? "revisions" : "details";
      if (detailView) detailView.classList.toggle("active", activeRightPanelTab === "details");
      if (revisionView) revisionView.classList.toggle("active", activeRightPanelTab === "revisions");
      if (detailTabButton) detailTabButton.classList.toggle("active", activeRightPanelTab === "details");
      if (revisionTabButton) revisionTabButton.classList.toggle("active", activeRightPanelTab === "revisions");
      if (showDetailsButton) showDetailsButton.classList.toggle("active", rightPanelVisible && activeRightPanelTab === "details");
      if (showRevisionsButton) showRevisionsButton.classList.toggle("active", rightPanelVisible && activeRightPanelTab === "revisions");
    }

    function setLeftPanelVisibility(visible) {
      leftPanelVisible = !!visible;
      if (page) page.classList.toggle("left-panel-collapsed", !leftPanelVisible);
      if (toggleLeftPanelButton) {
        toggleLeftPanelButton.classList.toggle("active", leftPanelVisible);
        toggleLeftPanelButton.textContent = leftPanelVisible ? "Hide Tools" : "Show Tools";
      }
      refreshCanvasViewport();
    }

    function setRightPanelVisibility(visible, tab = activeRightPanelTab) {
      rightPanelVisible = !!visible;
      if (page) page.classList.toggle("right-panel-collapsed", !rightPanelVisible);
      if (hideRightPanelButton) hideRightPanelButton.disabled = !rightPanelVisible;
      if (rightPanelVisible) {
        setRightPanelTab(tab);
      } else {
        if (showDetailsButton) showDetailsButton.classList.remove("active");
        if (showRevisionsButton) showRevisionsButton.classList.remove("active");
      }
      if (hideRightPanelButton) {
        hideRightPanelButton.textContent = rightPanelVisible ? "Hide Panel" : "Panel Hidden";
      }
      refreshCanvasViewport();
    }

    function enableHorizontalResize(handle, side) {
      if (!handle || !page) return;
      handle.addEventListener("pointerdown", (event) => {
        event.preventDefault();
        const pageRect = page.getBoundingClientRect();
        const styles = getComputedStyle(page);
        const currentLeft = Number.parseFloat(styles.getPropertyValue("--left-panel-width")) || 280;
        const currentRight = Number.parseFloat(styles.getPropertyValue("--right-panel-width")) || 380;
        const startX = event.clientX;
        handle.classList.add("dragging");

        const onMove = (moveEvent) => {
          const delta = moveEvent.clientX - startX;
          if (side === "left" && leftPanelVisible) {
            const maxLeft = Math.max(220, pageRect.width - (rightPanelVisible ? currentRight : 0) - 320);
            const next = Math.max(220, Math.min(maxLeft, currentLeft + delta));
            page.style.setProperty("--left-panel-width", `${next}px`);
          }
          if (side === "right" && rightPanelVisible) {
            const maxRight = Math.max(260, pageRect.width - (leftPanelVisible ? currentLeft : 0) - 320);
            const next = Math.max(260, Math.min(maxRight, currentRight - delta));
            page.style.setProperty("--right-panel-width", `${next}px`);
          }
          refreshCanvasViewport();
        };

        const onUp = () => {
          handle.classList.remove("dragging");
          window.removeEventListener("pointermove", onMove);
          window.removeEventListener("pointerup", onUp);
          window.removeEventListener("pointercancel", onUp);
        };

        window.addEventListener("pointermove", onMove);
        window.addEventListener("pointerup", onUp);
        window.addEventListener("pointercancel", onUp);
      });
    }

    function severityBadgeClass(value) {
      const normalized = String(value || "").toLowerCase();
      if (normalized === "high") return "severity-high";
      if (normalized === "medium") return "severity-medium";
      return "severity-low";
    }

    function confidenceBadgeClass(value) {
      const normalized = String(value || "").toLowerCase();
      if (normalized === "high") return "confidence-high";
      if (normalized === "medium") return "confidence-medium";
      return "confidence-low";
    }

    function parseSuggestedStateField(suggestedState, field) {
      if (suggestedState && typeof suggestedState === "object" && !Array.isArray(suggestedState)) {
        const direct = suggestedState[field];
        if (direct !== undefined && direct !== null && String(direct).trim()) {
          return String(direct).trim();
        }
        if (field === "node_type") {
          const alias = suggestedState.type;
          if (alias !== undefined && alias !== null && String(alias).trim()) {
            return String(alias).trim();
          }
        }
        return "";
      }
      const text = String(suggestedState || "").trim();
      if (!text) return "";
      const escapedField = field.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      const match = text.match(new RegExp(`(?:^|[;\\n])\\s*${escapedField}\\s*[:=]\\s*(.+?)(?=\\s*(?:[;\\n]|$))`, "i"));
      return match ? match[1].trim() : "";
    }

    function resolveSuggestedStateValue(suggestedState, preferredFields, currentValue) {
      if (suggestedState && typeof suggestedState === "object" && !Array.isArray(suggestedState)) {
        for (const field of preferredFields) {
          const parsed = parseSuggestedStateField(suggestedState, field);
          if (!parsed) continue;
          if (/^(retained|keep|unchanged|no change|same)$/i.test(parsed)) {
            return currentValue || "";
          }
          return parsed;
        }
        return currentValue || "";
      }
      const text = String(suggestedState || "").trim();
      if (!text) return currentValue || "";
      for (const field of preferredFields) {
        const parsed = parseSuggestedStateField(text, field);
        if (parsed) {
          if (/^(retained|keep|unchanged|no change|same)$/i.test(parsed)) {
            return currentValue || "";
          }
          return parsed;
        }
      }
      if (/\bretained\b|\bunchanged\b|\bno\s+change\b|\bkeep\b/i.test(text)) {
        return currentValue || "";
      }
      return text;
    }

    function formatRevisionState(value) {
      if (value && typeof value === "object" && !Array.isArray(value)) {
        const entries = Object.entries(value)
          .filter(([_, fieldValue]) => String(fieldValue || "").trim());
        if (!entries.length) return "";
        return entries
          .map(([key, fieldValue]) => `${key}: ${String(fieldValue).trim()}`)
          .join("; ");
      }
      return String(value || "").trim();
    }

    function summarizeNodeUpdate(item) {
      const suggestedState = item.suggested_state || "";
      const changeType = String(item.change_type || "").toLowerCase();
      if (changeType === "relabel") {
        const labelValue = resolveSuggestedStateValue(suggestedState, ["label"], "");
        return labelValue ? `Label -> ${labelValue}` : (item.reason || "Update node");
      }
      if (changeType === "rename") {
        const nameValue = resolveSuggestedStateValue(suggestedState, ["name"], "");
        return nameValue ? `Name -> ${nameValue}` : (item.reason || "Update node");
      }
      if (changeType === "retype") {
        const typeValue = resolveSuggestedStateValue(suggestedState, ["node_type", "type"], "");
        return typeValue ? `Type -> ${typeValue}` : (item.reason || "Update node");
      }
      return formatRevisionState(suggestedState) || item.reason || "Update node";
    }

    function collectReviewCards() {
      const cards = [];
      const coveredEdgeAdditions = new Map();
      Object.entries(revisionGeneratedEdges).forEach(([ownerKey, edges]) => {
        (edges || []).forEach((edgeKey) => coveredEdgeAdditions.set(edgeKey, ownerKey));
      });
      const nextIndexByPrefix = {
        H: 0,
        En: 0,
        C: 0,
        Ev: 0,
      };
      cy.nodes().forEach((node) => {
        const nodeId = String(node.data("nodeId") || node.data("id") || "");
        const match = nodeId.match(/^(H|En|C|Ev)(\d+)$/);
        if (!match) return;
        const prefix = match[1];
        const value = Number.parseInt(match[2], 10);
        if (Number.isFinite(value)) {
          nextIndexByPrefix[prefix] = Math.max(nextIndexByPrefix[prefix], value);
        }
      });
      function reservePreviewNodeId(nodeType) {
        const normalized = canonicalizeNodeType(nodeType);
        const prefixMap = {
          hazardconsequence: "H",
          entity: "En",
          condition: "C",
          event: "Ev",
        };
        const prefix = prefixMap[normalized] || "N";
        if (!(prefix in nextIndexByPrefix)) {
          nextIndexByPrefix[prefix] = 0;
        }
        nextIndexByPrefix[prefix] += 1;
        return `${prefix}${nextIndexByPrefix[prefix]}`;
      }
      (reviewSuggestions.issues_summary || []).forEach((item, index) => {
        cards.push({
          kind: "Issue Summary",
          actionable: false,
          key: `issue_summary_${index}`,
          relatedNodeIds: [],
          relatedEdgeKeys: [],
          summary: item.description || "",
          details: [
            ["Issue type", item.issue_type || ""],
          ],
          severity: item.severity || "low",
          confidence: "",
          payload: item,
        });
      });
      (reviewSuggestions.node_updates || []).forEach((item, index) => {
        cards.push({
          kind: "Node Update",
          actionable: true,
          key: `node_update_${index}`,
          relatedNodeIds: [item.target_id].filter(Boolean),
          relatedEdgeKeys: [],
          summary: summarizeNodeUpdate(item),
          details: [
            ["Target", item.target_id || ""],
            ["Change", item.change_type || ""],
            ["Suggested state", formatRevisionState(item.suggested_state || "")],
            ["Reason", item.reason || ""],
            ["Evidence", item.evidence || ""],
          ],
          severity: item.severity || "low",
          confidence: item.confidence || "",
          payload: item,
        });
      });
      (reviewSuggestions.node_additions || []).forEach((item, index) => {
        const nodeAdditionKey = `node_addition_${index}`;
        const relatedNodeIds = [];
        const suggestedNodeType = String(item.suggested_node_type || "").trim();
        const previewNodeId = reservePreviewNodeId(suggestedNodeType);
        const coveredByThisNode = [];
        (item.suggested_upstream_links || []).forEach((link) => {
          if (link && link.source) {
            relatedNodeIds.push(link.source);
            const relation = link.relation || "enables";
            const edgeKey = `${link.source}|${previewNodeId}|${relation}`;
            coveredEdgeAdditions.set(edgeKey, nodeAdditionKey);
            coveredByThisNode.push(edgeKey);
          }
        });
        (item.suggested_downstream_links || []).forEach((link) => {
          if (link && link.target) {
            relatedNodeIds.push(link.target);
            const relation = link.relation || "enables";
            const edgeKey = `${previewNodeId}|${link.target}|${relation}`;
            coveredEdgeAdditions.set(edgeKey, nodeAdditionKey);
            coveredByThisNode.push(edgeKey);
          }
        });
        cards.push({
          kind: "Node Addition",
          actionable: true,
          key: nodeAdditionKey,
          relatedNodeIds,
          relatedEdgeKeys: coveredByThisNode,
          summary: `${item.suggested_label || "Node"}: ${item.suggested_name || ""}`,
          details: [
            ["Preview node ID", previewNodeId],
            ["Suggested label", item.suggested_label || ""],
            ["Suggested name", item.suggested_name || ""],
            ["Suggested type", item.suggested_node_type || ""],
            ["Upstream links", (item.suggested_upstream_links || []).map((link) => `${link.source} -> new (${link.relation})`).join("; ")],
            ["Downstream links", (item.suggested_downstream_links || []).map((link) => `new -> ${link.target} (${link.relation})`).join("; ")],
            ["Reason", item.reason || ""],
            ["Evidence", item.evidence || ""],
          ],
          severity: item.severity || "low",
          confidence: item.confidence || "",
          payload: item,
        });
      });
      (reviewSuggestions.node_deletions || []).forEach((item, index) => {
        cards.push({
          kind: "Node Deletion",
          actionable: true,
          key: `node_deletion_${index}`,
          relatedNodeIds: [item.target_id].filter(Boolean),
          relatedEdgeKeys: [],
          summary: `Delete node ${item.target_id || ""}`,
          details: [
            ["Target", item.target_id || ""],
            ["Reason", item.reason || ""],
            ["Evidence", item.evidence || ""],
          ],
          severity: item.severity || "low",
          confidence: item.confidence || "",
          payload: item,
        });
      });
      (reviewSuggestions.edge_additions || []).forEach((item, index) => {
        const edgeKey = `${item.source}|${item.target}|${item.relation}`;
        const coveredByKey = coveredEdgeAdditions.get(edgeKey) || "";
        const coveredByAcceptedNodeAddition = (
          coveredByKey &&
          coveredByKey.startsWith("node_addition_") &&
          getRevisionDecisionStatus(coveredByKey) === "accepted"
        );
        cards.push({
          kind: "Edge Addition",
          actionable: !coveredByAcceptedNodeAddition,
          key: `edge_addition_${index}`,
          relatedNodeIds: [item.source, item.target].filter(Boolean),
          relatedEdgeKeys: [`${item.source}|${item.target}|${item.relation}`],
          summary: `${item.source || ""} -> ${item.target || ""} (${item.relation || ""})`,
          details: [
            ["Source", item.source || ""],
            ["Target", item.target || ""],
            ["Relation", item.relation || ""],
            ["Reason", item.reason || ""],
            ["Evidence", item.evidence || ""],
          ],
          severity: item.severity || "low",
          confidence: item.confidence || "",
          impliedDecision: coveredByAcceptedNodeAddition ? "accepted" : "",
          impliedDecisionLabel: coveredByAcceptedNodeAddition
            ? "Accepted and applied via node addition."
            : "",
          payload: item,
        });
      });
      (reviewSuggestions.edge_deletions || []).forEach((item, index) => {
        cards.push({
          kind: "Edge Deletion",
          actionable: true,
          key: `edge_deletion_${index}`,
          relatedNodeIds: [item.source, item.target].filter(Boolean),
          relatedEdgeKeys: [`${item.source}|${item.target}|${item.relation}`],
          summary: `Delete edge ${item.source || ""} -> ${item.target || ""} (${item.relation || ""})`,
          details: [
            ["Source", item.source || ""],
            ["Target", item.target || ""],
            ["Relation", item.relation || ""],
            ["Reason", item.reason || ""],
            ["Evidence", item.evidence || ""],
          ],
          severity: item.severity || "low",
          confidence: item.confidence || "",
          payload: item,
        });
      });
      (reviewSuggestions.edge_updates || []).forEach((item, index) => {
        cards.push({
          kind: "Edge Update",
          actionable: true,
          key: `edge_update_${index}`,
          relatedNodeIds: [item.source, item.target].filter(Boolean),
          relatedEdgeKeys: [`${item.source}|${item.target}|${item.current_relation}`],
          summary: `${item.source || ""} -> ${item.target || ""}: ${item.current_relation || ""} -> ${item.suggested_relation || ""}`,
          details: [
            ["Source", item.source || ""],
            ["Target", item.target || ""],
            ["Current relation", item.current_relation || ""],
            ["Suggested relation", item.suggested_relation || ""],
            ["Reason", item.reason || ""],
            ["Evidence", item.evidence || ""],
          ],
          severity: item.severity || "low",
          confidence: item.confidence || "",
          payload: item,
        });
      });
      return cards;
    }

    function severityRank(value) {
      const normalized = String(value || "").toLowerCase();
      if (normalized === "high") return 0;
      if (normalized === "medium") return 1;
      return 2;
    }

    function kindRank(value) {
      const normalized = String(value || "").toLowerCase();
      if (normalized === "issue summary") return 0;
      if (normalized === "node update") return 1;
      if (normalized === "node addition") return 2;
      if (normalized === "node deletion") return 3;
      if (normalized === "edge addition") return 4;
      if (normalized === "edge deletion") return 5;
      if (normalized === "edge update") return 6;
      return 99;
    }

    function renderRevisionSuggestions(focus = null, options = {}) {
      if (!revisionContent) return;
      const preserveScroll = !!options.preserveScroll;
      const anchorKey = String(options.anchorKey || "");
      const previousScrollTop = preserveScroll && detailPanelScroll
        ? detailPanelScroll.scrollTop
        : null;
      revisionFocus = focus;
      const cards = collectReviewCards().sort((a, b) => {
        const issueSummaryDiff = kindRank(a.kind) === 0 ? -1 : kindRank(b.kind) === 0 ? 1 : 0;
        if (issueSummaryDiff !== 0) return issueSummaryDiff;
        const severityDiff = severityRank(a.severity) - severityRank(b.severity);
        if (severityDiff !== 0) return severityDiff;
        return kindRank(a.kind) - kindRank(b.kind);
      });
      if (!cards.length) {
        revisionContent.className = "revision-empty";
        revisionContent.innerHTML = "No review suggestions loaded.";
        return;
      }

      const focusNodeId = focus && focus.type === "node" ? focus.id : null;
      const focusEdgeKey = focus && focus.type === "edge"
        ? `${focus.source}|${focus.target}|${focus.relation || ""}`
        : null;

      const html = cards.map((card) => {
        const relatedNodes = Array.isArray(card.relatedNodeIds) ? card.relatedNodeIds.filter(Boolean) : [];
        const relatedEdges = Array.isArray(card.relatedEdgeKeys) ? card.relatedEdgeKeys.filter(Boolean) : [];
        const relevant = (
          (focusNodeId && relatedNodes.includes(focusNodeId)) ||
          (focusEdgeKey && relatedEdges.includes(focusEdgeKey))
        );
        const detailsHtml = (card.details || [])
          .filter(([_, value]) => String(value || "").trim())
          .map(([label, value]) => `<div class="revision-meta-row"><strong>${escapeHtml(label)}:</strong> ${escapeHtml(value)}</div>`)
          .join("");
        const badges = [
          `<span class="revision-badge ${severityBadgeClass(card.severity)}">Severity: ${escapeHtml(card.severity || "low")}</span>`,
          card.confidence ? `<span class="revision-badge ${confidenceBadgeClass(card.confidence)}">Confidence: ${escapeHtml(card.confidence)}</span>` : "",
        ].join("");
        const decision = getRevisionDecisionStatus(card.key) || card.impliedDecision || "";
        const decisionReason = getRevisionDecisionReason(card.key);
        const stateHtml = decision
          ? `<div class="revision-state ${decision}">${
              card.impliedDecisionLabel
                ? escapeHtml(card.impliedDecisionLabel)
                : decision === "accepted"
                  ? "Accepted and applied."
                  : "Rejected."
            }${
              decision === "rejected" && decisionReason
                ? `<div class="revision-reason">${escapeHtml(decisionReason)}</div>`
                : ""
            }</div>`
          : "";
        const actionsHtml = card.actionable ? `
          <div class="revision-actions">
            <button type="button" class="accept-btn" data-revision-key="${escapeHtml(card.key)}" data-revision-action="accept"${decision ? " disabled" : ""}>Accept</button>
            <button type="button" class="reject-btn" data-revision-key="${escapeHtml(card.key)}" data-revision-action="reject"${decision ? " disabled" : ""}>Reject</button>
          </div>
        ` : `
          <div class="revision-actions">
            <button type="button" disabled>Info only</button>
          </div>
        `;
        return `
          <div class="revision-card${relevant ? " relevant" : ""}">
            <div class="revision-head">
              <div class="revision-kind">${escapeHtml(card.kind)}</div>
              <div class="revision-badges">${badges}</div>
            </div>
            <div class="revision-text">${escapeHtml(card.summary || "")}</div>
            <div class="revision-meta">${detailsHtml}</div>
            ${stateHtml}
            ${actionsHtml}
          </div>
        `;
      }).join("");

      revisionContent.className = "revision-list";
      revisionContent.innerHTML = html;
      revisionContent.querySelectorAll("[data-revision-action]").forEach((button) => {
        button.addEventListener("click", () => {
          const key = button.getAttribute("data-revision-key") || "";
          const action = button.getAttribute("data-revision-action") || "";
          handleRevisionDecision(key, action);
        });
      });
      if (preserveScroll && detailPanelScroll && previousScrollTop !== null) {
        window.requestAnimationFrame(() => {
          detailPanelScroll.scrollTop = previousScrollTop;
          if (!anchorKey) return;
          const anchorButton = Array.from(revisionContent.querySelectorAll("[data-revision-key]"))
            .find((button) => (button.getAttribute("data-revision-key") || "") === anchorKey);
          const anchorCard = anchorButton ? anchorButton.closest(".revision-card") : null;
          if (!anchorCard) return;
          const containerRect = detailPanelScroll.getBoundingClientRect();
          const cardRect = anchorCard.getBoundingClientRect();
          const outsideView = (
            cardRect.top < containerRect.top ||
            cardRect.bottom > containerRect.bottom
          );
          if (outsideView) {
            anchorCard.scrollIntoView({ block: "nearest" });
          }
        });
      }
    }

    function findNodeByNodeId(nodeId) {
      return cy.nodes().filter((node) => {
        const data = node.data();
        return (data.nodeId || data.id || "") === nodeId;
      })[0] || null;
    }

    function findNodeBySignature(label, name, nodeType) {
      const normalizedLabel = String(label || "").trim().toLowerCase();
      const normalizedName = String(name || "").trim().toLowerCase();
      const normalizedType = canonicalizeNodeType(nodeType);
      return cy.nodes().filter((node) => {
        const data = node.data();
        return (
          String(data.label || "").trim().toLowerCase() === normalizedLabel &&
          String(data.name || "").trim().toLowerCase() === normalizedName &&
          canonicalizeNodeType(data.nodeType || "") === normalizedType
        );
      })[0] || null;
    }

    function findEdgeByTriple(source, target, relation) {
      return cy.edges().filter((edge) => {
        const data = edge.data();
        return (
          (data.source || "") === source &&
          (data.target || "") === target &&
          ((data.relation || data.label || "") === relation)
        );
      })[0] || null;
    }

    function applyStoredRevisionHighlights() {
      const acceptedKeys = Object.entries(revisionDecisions)
        .filter(([key]) => getRevisionDecisionStatus(key) === "accepted")
        .map(([key]) => key);
      if (!acceptedKeys.length) return;

      const cardsByKey = new Map(collectReviewCards().map((card) => [card.key, card]));
      acceptedKeys.forEach((key) => {
        const card = cardsByKey.get(key);
        if (!card) return;
        const item = card.payload || {};
        const kind = String(card.kind || "").toLowerCase();
        if (kind === "node update") {
          const node = findNodeByNodeId(item.target_id || "");
          if (node) markAsAdded(node);
          return;
        }
        if (kind === "node addition") {
          const node = findNodeBySignature(
            item.suggested_label || "",
            item.suggested_name || "",
            item.suggested_node_type || ""
          );
          if (node) markAsAdded(node);
          (item.suggested_upstream_links || []).forEach((link) => {
            const edge = findEdgeByTriple(link.source || "", node?.data("nodeId") || node?.data("id") || "", link.relation || "enables");
            if (edge) markAsAdded(edge);
          });
          (item.suggested_downstream_links || []).forEach((link) => {
            const edge = findEdgeByTriple(node?.data("nodeId") || node?.data("id") || "", link.target || "", link.relation || "enables");
            if (edge) markAsAdded(edge);
          });
          return;
        }
        if (kind === "node deletion") {
          const node = findNodeByNodeId(item.target_id || "");
          if (node) markAsDeleted(node);
          return;
        }
        if (kind === "edge addition") {
          const edge = findEdgeByTriple(item.source || "", item.target || "", item.relation || "");
          if (edge) markAsAdded(edge);
          return;
        }
        if (kind === "edge deletion") {
          const edge = findEdgeByTriple(item.source || "", item.target || "", item.relation || "");
          if (edge) markAsDeleted(edge);
        }
      });
    }

    function applyNodeUpdate(card) {
      const item = card.payload || {};
      const node = findNodeByNodeId(item.target_id || "");
      if (!node) throw new Error(`Node ${item.target_id || ""} not found.`);
      const data = { ...node.data() };
      const changeType = String(item.change_type || "").toLowerCase();
      const suggestedState = item.suggested_state || "";
      const captureField = (label) => parseSuggestedStateField(suggestedState, label);
      const resolveFieldValue = (preferredFields, currentValue) =>
        resolveSuggestedStateValue(suggestedState, preferredFields, currentValue);
      if (changeType === "rename") {
        data.name = resolveFieldValue(["name"], data.name);
      } else if (changeType === "relabel") {
        data.label = resolveFieldValue(["label"], data.label);
      } else if (changeType === "retype") {
        data.nodeType = resolveFieldValue(["node_type", "type"], data.nodeType);
      } else if (changeType === "update_evidence") {
        data.evidence = captureField("evidence") || suggestedState || data.evidence;
      } else if (changeType === "update_explanation") {
        data.explanation = captureField("explanation") || suggestedState || data.explanation;
      } else if (changeType === "clarify_role") {
        data.explanation = suggestedState || data.explanation;
      }
      data.labelWrapped = wrapText(data.label || "", 18);
      data.nameWrapped = wrapText(data.name || "", 24);
      const size = computeNodeSize(data.labelWrapped, data.nameWrapped);
      data.nodeWidth = size.nodeWidth;
      data.nodeHeight = size.nodeHeight;
      data.fill = nodeFillFromType(data.nodeType);
      data.title = buildNodeTitle(data);
      node.data(data);
      markAsAdded(node);
      runLayout();
      syncNodeOverlay();
      updateSummary();
      showNodeDetails(node, "Accepted revision applied.", "success");
    }

    function applyNodeAddition(card) {
      const item = card.payload || {};
      const label = String(item.suggested_label || "").trim();
      const nodeType = String(item.suggested_node_type || "").trim();
      const name = String(item.suggested_name || "").trim();
      if (!label || !nodeType || !name) {
        throw new Error("Node addition is missing label, type, or name.");
      }
      const nodeId = nextNodeIdForType(nodeType);
      const labelWrapped = wrapText(label, 18);
      const nameWrapped = wrapText(name, 24);
      const size = computeNodeSize(labelWrapped, nameWrapped);
      const nodeData = {
        id: nodeId,
        nodeId,
        label,
        name,
        nodeType,
        labelWrapped,
        nameWrapped,
        evidence: item.evidence || "",
        explanation: item.reason || item.explanation || "",
        fill: nodeFillFromType(nodeType),
        nodeWidth: size.nodeWidth,
        nodeHeight: size.nodeHeight,
      };
      nodeData.title = buildNodeTitle(nodeData);
      const newNode = cy.add({ group: "nodes", data: nodeData });
      const center = cy.extent();
      newNode.position({
        x: (center.x1 + center.x2) / 2,
        y: (center.y1 + center.y2) / 2,
      });
      markAsAdded(newNode);

      const maybeAddEdge = (sourceId, targetId, relation) => {
        if (!sourceId || !targetId || !relation) return;
        if (!findNodeByNodeId(sourceId) || !findNodeByNodeId(targetId)) return;
        if (findEdgeByTriple(sourceId, targetId, relation)) return;
        const edge = cy.add({
          group: "edges",
          data: {
            id: `e${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
            source: sourceId,
            target: targetId,
            label: relation,
            relation,
            evidence: "",
            explanation: "",
            title: buildEdgeTitle({
              source: sourceId,
              target: targetId,
              label: relation,
              relation,
              evidence: "",
              explanation: "",
            }),
          },
        });
        markAsAdded(edge);
      };

      (item.suggested_upstream_links || []).forEach((link) => {
        maybeAddEdge(link.source || "", nodeId, link.relation || "enables");
      });
      (item.suggested_downstream_links || []).forEach((link) => {
        maybeAddEdge(nodeId, link.target || "", link.relation || "enables");
      });
      revisionGeneratedEdges[card.key] = [
        ...(item.suggested_upstream_links || []).map((link) => `${link.source || ""}|${nodeId}|${link.relation || "enables"}`),
        ...(item.suggested_downstream_links || []).map((link) => `${nodeId}|${link.target || ""}|${link.relation || "enables"}`),
      ].filter(Boolean);

      runLayout();
      syncNodeOverlay();
      updateSummary();
      showNodeDetails(newNode[0], "Accepted revision applied.", "success");
    }

    function applyNodeDeletion(card) {
      const item = card.payload || {};
      const node = findNodeByNodeId(item.target_id || "");
      if (!node) throw new Error(`Node ${item.target_id || ""} not found.`);
      markAsDeleted(node);
      const connectedEdges = node.connectedEdges();
      if (connectedEdges.length) {
        markAsDeleted(connectedEdges);
      }
      syncNodeOverlay();
      showNodeDetails(node, "Accepted revision applied.", "success");
    }

    function applyEdgeAddition(card) {
      const item = card.payload || {};
      const source = item.source || "";
      const target = item.target || "";
      const relation = item.relation || "";
      if (!findNodeByNodeId(source) || !findNodeByNodeId(target)) {
        throw new Error("Source or target node for edge addition was not found.");
      }
      if (findEdgeByTriple(source, target, relation)) {
        throw new Error("Suggested edge already exists.");
      }
      const edge = cy.add({
        group: "edges",
        data: {
          id: `e${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
          source,
          target,
          label: relation,
          relation,
          evidence: item.evidence || "",
          explanation: item.explanation || item.reason || "",
          title: buildEdgeTitle({
            source,
            target,
            label: relation,
            relation,
            evidence: item.evidence || "",
            explanation: item.explanation || item.reason || "",
          }),
        },
      });
      markAsAdded(edge);
      runLayout();
      syncNodeOverlay();
      updateSummary();
      showEdgeDetails(edge[0]);
    }

    function applyEdgeDeletion(card) {
      const item = card.payload || {};
      const edge = findEdgeByTriple(item.source || "", item.target || "", item.relation || "");
      if (!edge) throw new Error("Suggested edge for deletion was not found.");
      markAsDeleted(edge);
      syncNodeOverlay();
      showEdgeDetails(edge);
    }

    function applyEdgeUpdate(card) {
      const item = card.payload || {};
      const edge = findEdgeByTriple(item.source || "", item.target || "", item.current_relation || "");
      if (!edge) throw new Error("Edge to update was not found.");
      edge.data({
        ...edge.data(),
        relation: item.suggested_relation || edge.data("relation") || edge.data("label") || "",
        label: item.suggested_relation || edge.data("relation") || edge.data("label") || "",
        evidence: item.evidence || edge.data("evidence") || "",
        explanation: item.explanation || item.reason || edge.data("explanation") || "",
        title: buildEdgeTitle({
          source: item.source || edge.data("source"),
          target: item.target || edge.data("target"),
          relation: item.suggested_relation || edge.data("relation") || edge.data("label") || "",
          label: item.suggested_relation || edge.data("relation") || edge.data("label") || "",
          evidence: item.evidence || edge.data("evidence") || "",
          explanation: item.explanation || item.reason || edge.data("explanation") || "",
        }),
      });
      markAsAdded(edge);
      syncNodeOverlay();
      showEdgeDetails(edge);
    }

    function applyRevisionCard(card) {
      if (!card || !card.actionable) {
        throw new Error("This suggestion is informational only.");
      }
      if (card.kind === "Node Update") return applyNodeUpdate(card);
      if (card.kind === "Node Addition") return applyNodeAddition(card);
      if (card.kind === "Node Deletion") return applyNodeDeletion(card);
      if (card.kind === "Edge Addition") return applyEdgeAddition(card);
      if (card.kind === "Edge Deletion") return applyEdgeDeletion(card);
      if (card.kind === "Edge Update") return applyEdgeUpdate(card);
      throw new Error(`Unsupported revision kind: ${card.kind}`);
    }

    function handleRevisionDecision(key, action) {
      const card = collectReviewCards().find((item) => item.key === key);
      if (!card) return;
      const previousTab = activeRightPanelTab;
      if (action === "reject") {
        openModal(
          "Reject Suggestion",
          "Record why this suggestion is being rejected.",
          `
            <label>
              Review reason
              <textarea id="review-reason-input" rows="5" placeholder="Explain why this suggestion is rejected."></textarea>
            </label>
          `,
          ({ showModalError }) => {
            const reasonInput = document.getElementById("review-reason-input");
            const reviewReason = String(reasonInput?.value || "").trim();
            if (!reviewReason) {
              showModalError("A rejection reason is required.", ["review-reason-input"]);
              return false;
            }
            pushUndoState();
            setRevisionDecision(key, "rejected", reviewReason);
            renderRevisionSuggestions(revisionFocus, { preserveScroll: true, anchorKey: key });
            setRightPanelVisibility(true, previousTab);
            setFormStatus(saveFormStatus, `Rejected suggestion: ${card.kind}.`, false);
            return true;
          },
        );
        return;
      }
      if (action === "accept") {
        try {
          pushUndoState();
          applyRevisionCard(card);
          setRevisionDecision(key, "accepted");
          renderRevisionSuggestions(revisionFocus, { preserveScroll: true, anchorKey: key });
          setRightPanelVisibility(true, previousTab);
          setFormStatus(saveFormStatus, `Accepted suggestion: ${card.kind}.`, false);
        } catch (error) {
          setFormStatus(saveFormStatus, `Could not apply suggestion: ${error}`, true);
        }
      }
    }

    function escapeHtml(value) {
      return String(value || "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;");
    }

    function syncNodeOverlay() {
      if (!overlay) return;
      const showName = true;
      const baseLabelFontSize = 18;
      const baseNameFontSize = 14;
      const baseLabelGap = 0;
      const baseHeaderPaddingTop = 8;
      const baseHeaderPaddingX = 10;
      const baseHeaderPaddingBottom = 7;
      const baseBodyPaddingY = 8;
      const baseBodyPaddingX = 10;
      const fragments = [];

      cy.nodes().forEach((node) => {
        const pos = node.renderedPosition();
        const width = node.renderedWidth();
        const height = node.renderedHeight();
        const left = pos.x - width / 2;
        const top = pos.y - height / 2;
        const modelHeight = Number(node.data("nodeHeight")) || height || 1;
        const scale = Math.max(0.1, height / modelHeight);
        const labelFontSize = baseLabelFontSize * scale;
        const nameFontSize = labelFontSize;
        const labelGap = baseLabelGap * scale;
        const headerPaddingTop = baseHeaderPaddingTop * scale;
        const headerPaddingX = baseHeaderPaddingX * scale;
        const headerPaddingBottom = baseHeaderPaddingBottom * scale;
        const bodyPaddingY = baseBodyPaddingY * scale;
      const bodyPaddingX = baseBodyPaddingX * scale;
        const bodyPaddingBottom = bodyPaddingY;
        let borderColor = "rgba(31, 41, 55, 0.18)";
        let borderWidth = 1 * scale;
        let borderStyle = "solid";
        if (node.selected()) {
          borderColor = "#2563eb";
          borderWidth = 3 * scale;
        }
        if (node.hasClass("added-highlight")) {
          borderColor = "#dc2626";
          borderWidth = 3 * scale;
        }
        if (node.hasClass("delete-mark")) {
          borderColor = "#b45309";
          borderWidth = Math.max(1.4, 3 * scale);
          borderStyle = "dashed";
        }
        const labelText = escapeHtml(node.data("labelWrapped") || "");
        const fillColor = String(node.data("fill") || "#6b7280");
        const headerColor = adjustHeaderColor(fillColor);
        let nameHtml = "";
        if (showName) {
          const rawName = String(node.data("name") || node.data("nameWrapped") || "")
            .replace(/\s*\n\s*/g, " ")
            .trim();
          if (rawName) {
            nameHtml = `<div class="node-overlay-name" style="font-size:${nameFontSize}px; line-height:${nameFontSize * 1.25}px; padding:${bodyPaddingY}px ${bodyPaddingX}px ${bodyPaddingBottom}px;">${escapeHtml(rawName)}</div>`;
          }
        }
        fragments.push(`
          <div
            class="node-overlay${node.selected() ? " selected-overlay" : ""}${node.hasClass("added-highlight") ? " added-overlay" : ""}${node.hasClass("delete-mark") ? " deleted-overlay" : ""}"
            style="left:${left}px; top:${top}px; width:${width}px; height:${height}px; border-color:${escapeHtml(borderColor)}; border-width:${borderWidth}px; border-style:${borderStyle};"
            title="${escapeHtml(node.data("title"))}"
          >
            <div class="node-overlay-label" style="margin-bottom:${labelGap}px; font-size:${labelFontSize}px; background:${escapeHtml(headerColor)}; padding:${headerPaddingTop}px ${headerPaddingX}px ${headerPaddingBottom}px;">${labelText}</div>
            ${nameHtml}
          </div>
        `);
      });
      overlay.innerHTML = fragments.join("");
    }

    function setFormStatus(target, message, isError = false) {
      if (!target) return;
      target.textContent = message || "";
      target.style.color = isError ? "#b91c1c" : "#4b5563";
    }

    if (toggleLeftPanelButton) {
      toggleLeftPanelButton.addEventListener("click", () => {
        setLeftPanelVisibility(!leftPanelVisible);
      });
    }
    if (showDetailsButton) {
      showDetailsButton.addEventListener("click", () => {
        setRightPanelVisibility(true, "details");
      });
    }
    if (showRevisionsButton) {
      showRevisionsButton.addEventListener("click", () => {
        setRightPanelVisibility(true, "revisions");
      });
    }
    if (hideRightPanelButton) {
      hideRightPanelButton.addEventListener("click", () => {
        setRightPanelVisibility(false);
      });
    }
    if (detailTabButton) {
      detailTabButton.addEventListener("click", () => {
        setRightPanelVisibility(true, "details");
      });
    }
    if (revisionTabButton) {
      revisionTabButton.addEventListener("click", () => {
        setRightPanelVisibility(true, "revisions");
      });
    }
    enableHorizontalResize(leftResizer, "left");
    enableHorizontalResize(rightResizer, "right");
    setLeftPanelVisibility(true);
    setDetailSummary("Review suggestions are open by default.");
    setRightPanelVisibility(true, "revisions");

    function updateSummary() {
      const summary = document.getElementById("summary");
      if (summary) {
        summary.textContent = `${cy.nodes().length} nodes, ${cy.edges().length} edges`;
      }
    }

    (function enableRightMousePan() {
      const container = cy.container();
      if (!container) return;

      let rightPanning = false;
      let moved = false;
      let lastPoint = { x: 0, y: 0 };

      container.addEventListener("contextmenu", (event) => {
        event.preventDefault();
      });

      container.addEventListener("mousedown", (event) => {
        if (event.button !== 2) return;
        rightPanning = true;
        moved = false;
        lastPoint = { x: event.clientX, y: event.clientY };
        event.preventDefault();
      });

      window.addEventListener("mousemove", (event) => {
        if (!rightPanning) return;
        const dx = event.clientX - lastPoint.x;
        const dy = event.clientY - lastPoint.y;
        if (dx !== 0 || dy !== 0) {
          moved = true;
          cy.panBy({ x: dx, y: dy });
          syncNodeOverlay();
        }
        lastPoint = { x: event.clientX, y: event.clientY };
        event.preventDefault();
      });

      window.addEventListener("mouseup", (event) => {
        if (event.button !== 2 || !rightPanning) return;
        rightPanning = false;
        if (moved) {
          event.preventDefault();
        }
      });
    })();

    (function enableWheelZoom() {
      const container = cy.container();
      if (!container) return;

      cy.userZoomingEnabled(true);

      container.addEventListener("wheel", (event) => {
        event.preventDefault();

        const current = cy.zoom();
        const factor = Math.pow(1.001, -event.deltaY);
        let next = current * factor;

        const minZoom = 0.08;
        const maxZoom = 5;
        next = Math.max(minZoom, Math.min(maxZoom, next));

        const rect = container.getBoundingClientRect();
        const renderedPosition = {
          x: event.clientX - rect.left,
          y: event.clientY - rect.top,
        };

        cy.zoom({ level: next, renderedPosition });
        syncNodeOverlay();
      }, { passive: false });
    })();

    function openModal(title, description, bodyHtml, onConfirm) {
      if (!modalBackdrop) return;
      modalBackdrop.innerHTML = `
        <div class="modal-card">
          <h3>${escapeHtml(title)}</h3>
          <p>${escapeHtml(description)}</p>
          <div class="modal-grid">${bodyHtml}</div>
          <div id="modal-error-box" class="modal-error"></div>
          <div class="modal-actions">
            <button type="button" id="modal-cancel-button">Cancel</button>
            <button type="button" class="primary" id="modal-confirm-button">Confirm</button>
          </div>
        </div>
      `;
      modalBackdrop.classList.add("open");

      const close = () => {
        modalBackdrop.classList.remove("open");
        modalBackdrop.innerHTML = "";
      };

      const cancelButton = document.getElementById("modal-cancel-button");
      const confirmButton = document.getElementById("modal-confirm-button");
      const errorBox = document.getElementById("modal-error-box");
      const clearFieldErrors = () => {
        modalBackdrop.querySelectorAll(".field-invalid").forEach((el) => {
          el.classList.remove("field-invalid");
        });
      };
      const clearModalError = () => {
        clearFieldErrors();
        if (errorBox) {
          errorBox.textContent = "";
          errorBox.classList.remove("open");
        }
      };
      const showModalError = (message, fieldIds = []) => {
        clearFieldErrors();
        if (errorBox) {
          errorBox.textContent = message || "";
          errorBox.classList.add("open");
        }
        fieldIds.forEach((fieldId) => {
          const field = document.getElementById(fieldId);
          if (field) {
            field.classList.add("field-invalid");
          }
        });
      };
      if (cancelButton) {
        cancelButton.addEventListener("click", close, { once: true });
      }
      if (confirmButton) {
        confirmButton.addEventListener("click", () => {
          confirmButton.disabled = true;
          clearModalError();
          try {
            const shouldClose = onConfirm
              ? onConfirm({ showModalError, clearModalError }) !== false
              : true;
            if (shouldClose) {
              close();
              return;
            }
          } catch (error) {
            showModalError(`Unexpected error: ${error}`);
          }
          confirmButton.disabled = false;
        });
      }
    }

    function markAsAdded(elements) {
      if (!elements || !elements.length) return;
      const activeElements = elements.filter((element) => !element.hasClass("delete-mark"));
      if (!activeElements.length) return;
      activeElements.style("display", "element");
      activeElements.addClass("added-highlight");
    }

    function markAsDeleted(elements) {
      if (!elements || !elements.length) return;
      elements.removeClass("added-highlight");
      elements.addClass("delete-mark");
    }

    function setDeletedVisibility(visible) {
      deletedVisible = !!visible;
      const display = deletedVisible ? "element" : "none";
      cy.$(".delete-mark").style("display", display);
      if (toggleDeletedButton) {
        toggleDeletedButton.textContent = deletedVisible ? "Hide Deleted" : "Show Deleted";
      }
      setFormStatus(
        deleteFormStatus,
        deletedVisible ? "Deleted traces are visible." : "Deleted traces are hidden.",
        false,
      );
      syncNodeOverlay();
    }

    function serializeGraphElements() {
      const nodes = cy.nodes().map((node) => {
        const json = node.json();
        return {
          group: "nodes",
          data: { ...json.data },
          position: json.position ? { ...json.position } : undefined,
          classes: json.classes || "",
        };
      });
      const edges = cy.edges().map((edge) => {
        const json = edge.json();
        return {
          group: "edges",
          data: { ...json.data },
          classes: json.classes || "",
        };
      });
      return { nodes, edges };
    }

    function cloneGraphSnapshot() {
      return {
        elements: serializeGraphElements(),
        deletedVisible,
        pan: { ...cy.pan() },
        zoom: cy.zoom(),
        reviewState: {
          decisions: { ...revisionDecisions },
          generatedEdges: { ...revisionGeneratedEdges },
        },
      };
    }

    function pushUndoState(snapshotOverride = null, options = {}) {
      const { clearRedo = true } = options;
      const snapshot = snapshotOverride || cloneGraphSnapshot();
      undoStack.push(snapshot);
      if (undoStack.length > MAX_HISTORY) {
        undoStack.shift();
      }
      if (clearRedo) {
        redoStack.length = 0;
      }
    }

    function restoreGraphSnapshot(snapshot) {
      if (!snapshot) return;
      edgeCreationSource = null;
      edgeCreationMode = false;
      cy.$(":selected").unselect();
      cy.elements().remove();
      const elements = snapshot.elements || { nodes: [], edges: [] };
      if (elements.nodes?.length) {
        cy.add(elements.nodes);
      }
      if (elements.edges?.length) {
        cy.add(elements.edges);
      }
      if (snapshot.pan) {
        cy.pan(snapshot.pan);
      }
      if (typeof snapshot.zoom === "number") {
        cy.zoom(snapshot.zoom);
      }
      const reviewState = snapshot.reviewState || {};
      Object.keys(revisionDecisions).forEach((key) => delete revisionDecisions[key]);
      Object.assign(revisionDecisions, reviewState.decisions || {});
      Object.keys(revisionGeneratedEdges).forEach((key) => delete revisionGeneratedEdges[key]);
      Object.assign(revisionGeneratedEdges, reviewState.generatedEdges || {});
      setDeletedVisibility(snapshot.deletedVisible !== false);
      updateSummary();
      syncNodeOverlay();
      if (detailContent) {
        detailContent.innerHTML = "Nothing selected.";
      }
      setDetailSummary("Nothing selected.");
      renderRevisionSuggestions();
    }

    function undoLastAction() {
      if (!undoStack.length) {
        setFormStatus(saveFormStatus, "Nothing to undo.", false);
        return;
      }
      const currentSnapshot = cloneGraphSnapshot();
      const previousSnapshot = undoStack.pop();
      redoStack.push(currentSnapshot);
      if (redoStack.length > MAX_HISTORY) {
        redoStack.shift();
      }
      restoreGraphSnapshot(previousSnapshot);
      setFormStatus(saveFormStatus, "Undo applied.", false);
    }

    function redoLastAction() {
      if (!redoStack.length) {
        setFormStatus(saveFormStatus, "Nothing to redo.", false);
        return;
      }
      const currentSnapshot = cloneGraphSnapshot();
      const nextSnapshot = redoStack.pop();
      undoStack.push(currentSnapshot);
      if (undoStack.length > MAX_HISTORY) {
        undoStack.shift();
      }
      restoreGraphSnapshot(nextSnapshot);
      setFormStatus(saveFormStatus, "Redo applied.", false);
    }

    function serializeUpdatePayload() {
      const activeNodes = cy.nodes().filter((node) => !node.hasClass("delete-mark"));
      const activeNodeIds = new Set(activeNodes.map((node) => node.id()));
      const activeEdges = cy.edges().filter((edge) =>
        !edge.hasClass("delete-mark") &&
        activeNodeIds.has(edge.data("source")) &&
        activeNodeIds.has(edge.data("target"))
      );

      const payload = {
        hazard_consequence_node: [],
        entity_nodes: [],
        condition_nodes: [],
        event_nodes: [],
        edges: [],
      };

      activeNodes.forEach((node) => {
        const data = node.data();
        const item = {
          label: data.label || "",
          name: data.name || "",
          node_id: data.nodeId || data.id || "",
          node_type: data.nodeType || "",
          evidence: data.evidence || "",
          explanation: data.explanation || "",
          source: data.source || "updated_graph",
        };
        const normalizedType = canonicalizeNodeType(data.nodeType || "");
        item.node_type = normalizedType || "";
        if (normalizedType === "hazardconsequence") {
          payload.hazard_consequence_node.push(item);
        } else if (normalizedType === "entity") {
          payload.entity_nodes.push(item);
        } else if (normalizedType === "condition") {
          payload.condition_nodes.push(item);
        } else if (normalizedType === "event") {
          payload.event_nodes.push(item);
        }
      });

      activeEdges.forEach((edge) => {
        const data = edge.data();
        payload.edges.push({
          source: data.source || "",
          target: data.target || "",
          relation: data.relation || data.label || "",
          evidence: data.evidence || "",
          explanation: data.explanation || "",
        });
      });

      return payload;
    }

    function serializeReviewDecisionPayload() {
      const deletedNodes = cy.nodes()
        .filter((node) => node.hasClass("delete-mark"))
        .map((node) => String(node.data("nodeId") || node.data("id") || "").trim())
        .filter((nodeId) => !!nodeId);
      const deletedEdges = cy.edges()
        .filter((edge) => edge.hasClass("delete-mark"))
        .map((edge) => ({
          source: String(edge.data("source") || "").trim(),
          target: String(edge.data("target") || "").trim(),
          relation: String(edge.data("relation") || edge.data("label") || "").trim(),
        }))
        .filter((edge) => edge.source && edge.target);
      return {
        review_decisions: { ...revisionDecisions },
        deleted_nodes: deletedNodes,
        deleted_edges: deletedEdges,
        deleted_visible: deletedVisible,
      };
    }

    function downloadText(filename, content) {
      const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      anchor.style.display = "none";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    }

    function exportCurrentHtml() {
      const graphStateJson = JSON.stringify(serializeGraphElements());
      const deletedVisibleJson = JSON.stringify(deletedVisible);
      const revisionDecisionsJson = JSON.stringify(revisionDecisions);
      let html = "<!DOCTYPE html>\n" + originalDocumentHtml;
      html = html.replace(
        /const elements = .*?;\s*const schemaForm = .*?;\s*const reviewSuggestions =/s,
        `const elements = ${graphStateJson};\n    const schemaForm = ${JSON.stringify(schemaForm)};\n    const reviewSuggestions =`,
      );
      html = html.replace(
        /const initialRevisionDecisions = .*?;/,
        `const initialRevisionDecisions = ${revisionDecisionsJson};`,
      );
      html = html.replace(
        /let deletedVisible = (true|false);/,
        `let deletedVisible = ${deletedVisibleJson};`,
      );
      return html;
    }

    function exportCurrentGraph() {
      try {
        const payload = serializeUpdatePayload();
        const reviewStatePayload = serializeReviewDecisionPayload();
        downloadText("updated_causal_graph.json", JSON.stringify(payload, null, 2));
        downloadText("updated_causal_graph_review_state.json", JSON.stringify(reviewStatePayload, null, 2));
        downloadText("updated_causal_graph.html", exportCurrentHtml());
        setFormStatus(saveFormStatus, "Saved updated_causal_graph.json, updated_causal_graph_review_state.json, and updated_causal_graph.html.", false);
      } catch (error) {
        const message = error && error.message ? error.message : String(error);
        console.error("Failed to save updates:", error);
        setFormStatus(saveFormStatus, `Save failed: ${message}`, true);
      }
    }

    function nextNodeIdForType(nodeType) {
      const normalized = canonicalizeNodeType(nodeType);
      const prefixMap = {
        hazardconsequence: "H",
        entity: "En",
        condition: "C",
        event: "Ev",
      };
      const prefix = prefixMap[normalized] || "N";
      let maxIndex = 0;
      cy.nodes().forEach((node) => {
        const nodeId = String(node.data("nodeId") || node.data("id") || "");
        if (!nodeId.startsWith(prefix)) return;
        const suffix = Number.parseInt(nodeId.slice(prefix.length), 10);
        if (Number.isFinite(suffix)) {
          maxIndex = Math.max(maxIndex, suffix);
        }
      });
      return `${prefix}${maxIndex + 1}`;
    }

    function nodeFillFromType(nodeType) {
      const normalized = canonicalizeNodeType(nodeType);
      if (normalized === "hazardconsequence") return "#ffd6d6";
      if (normalized === "condition") return "#d8ebff";
      if (normalized === "entity") return "#ddf5df";
      if (normalized === "event") return "#f3e7ff";
      return "#f4f4f4";
    }

    function wrapText(text, width) {
      const words = String(text || "").split(/\s+/).filter(Boolean);
      if (!words.length) return "";
      const lines = [];
      let current = words.shift();
      words.forEach((word) => {
        const candidate = `${current} ${word}`;
        if (candidate.length > width) {
          lines.push(current);
          current = word;
        } else {
          current = candidate;
        }
      });
      lines.push(current);
      return lines.join("\n");
    }

    function adjustHeaderColor(color) {
      const normalized = String(color || "").trim().toLowerCase();
      if (normalized === "#f3e7ff") return "#874fff";
      if (normalized === "#ddf5df") return "#66d575";
      if (normalized === "#d8ebff") return "#3dadff";
      if (normalized === "#ffd6d6") return "#ffc7c2";
      return "#9ca3af";
    }

    function buildMeasuredNodeMarkup(labelWrapped, nameWrapped, fill) {
      const safeLabel = escapeHtml(labelWrapped || "");
      const safeNameText = escapeHtml(
        String(nameWrapped || "")
          .replace(/\s*\n\s*/g, " ")
          .trim()
      );
      const headerColor = adjustHeaderColor(fill || "#6b7280");
      const nameHtml = safeNameText
        ? `<div class="node-measure-body" style="padding:8px 10px 8px;">${safeNameText}</div>`
        : `<div class="node-measure-body"></div>`;
      return `
        <div class="node-measure-card">
          <div class="node-measure-header" style="background:${escapeHtml(headerColor)};">${safeLabel}</div>
          ${nameHtml}
        </div>
      `;
    }

    function computeNodeSize(labelWrapped, nameWrapped) {
      if (!nodeMeasureBox) {
        return { nodeWidth: 260, nodeHeight: 96 };
      }
      nodeMeasureBox.innerHTML = buildMeasuredNodeMarkup(labelWrapped, nameWrapped, "#6b7280");
      const measured = nodeMeasureBox.firstElementChild;
      if (!measured) {
        nodeMeasureBox.innerHTML = "";
        return { nodeWidth: 260, nodeHeight: 96 };
      }

      const measuredHeight = measured.getBoundingClientRect().height || measured.scrollHeight || 0;
      nodeMeasureBox.innerHTML = "";
      return {
        nodeWidth: 260,
        nodeHeight: Math.max(64, Math.ceil(measuredHeight) + 0),
      };
    }

    function runLayout() {
      cy.layout({
        name: "dagre",
        rankDir: "LR",
        nodeSep: 40,
        rankSep: 100,
        edgeSep: 16,
        padding: 30
      }).run();
    }

    function normalizeInitialNodeSizes() {
      cy.nodes().forEach((node) => {
        const data = { ...node.data() };
        const labelWrapped = wrapText(data.label || "", 18);
        const nameWrapped = wrapText(data.name || "", 24);
        const size = computeNodeSize(labelWrapped, nameWrapped);
        node.data({
          labelWrapped,
          nameWrapped,
          nodeWidth: size.nodeWidth,
          nodeHeight: size.nodeHeight,
        });
      });
    }

    function renderDetailSections(title, fields) {
      const sections = fields.map(([label, value]) => `
        <div class="detail-section">
          <div class="detail-label">${escapeHtml(label)}</div>
          <div class="detail-value">${escapeHtml(value)}</div>
        </div>
      `).join("");
      detailContent.innerHTML = `
        <div class="detail-section">
          <div class="detail-label">Selected</div>
          <div class="detail-value">${escapeHtml(title)}</div>
        </div>
        ${sections}
      `;
      setDetailSummary(title);
    }

    function buildNodeTitle(nodeData) {
      return [
        `ID: ${nodeData.nodeId || nodeData.id || ""}`,
        `Label: ${nodeData.label || ""}`,
        `Name: ${nodeData.name || ""}`,
        `Type: ${nodeData.nodeType || ""}`,
        `Evidence: ${nodeData.evidence || ""}`,
        `Explanation: ${nodeData.explanation || ""}`,
      ].join("\n");
    }

    function buildEdgeTitle(edgeData) {
      return [
        `${edgeData.source || ""} -> ${edgeData.target || ""}`,
        `Relation: ${edgeData.relation || edgeData.label || ""}`,
        `Evidence: ${edgeData.evidence || ""}`,
        `Explanation: ${edgeData.explanation || ""}`,
      ].join("\n");
    }

    function showNodeDetails(node, detailStatusMessage = "", detailStatusKind = "") {
      setRightPanelVisibility(true, "details");
      const data = node.data();
      const isDeleted = node.hasClass("delete-mark");
      setDetailSummary(`${data.label || ""}: ${data.name || ""}`);
      const labelOptions = (schemaForm.labels || []).map((label) => {
        const selected = label === (data.label || "") ? " selected" : "";
        return `<option value="${escapeHtml(label)}"${selected}>${escapeHtml(label)}</option>`;
      }).join("");
      const typeOptions = (schemaForm.types || []).map((type) => {
        const selected = type === (data.nodeType || "") ? " selected" : "";
        return `<option value="${escapeHtml(type)}"${selected}>${escapeHtml(type)}</option>`;
      }).join("");
      const statusClass = detailStatusKind ? `detail-status ${detailStatusKind}` : "detail-status";
      detailContent.innerHTML = `
        <div class="detail-section">
          <div class="detail-label">Selected Node</div>
          <div class="detail-value">${escapeHtml(`${data.label || ""}: ${data.name || ""}`)}</div>
        </div>
        <form id="detail-node-form" class="detail-form">
          <label>Node ID
            <input id="detail-node-id" type="text" value="${escapeHtml(data.nodeId || data.id || "")}" readonly />
          </label>
          <label>Label
            <select id="detail-node-label">${labelOptions}</select>
          </label>
          <label>Type
            <select id="detail-node-type">${typeOptions}</select>
          </label>
          <label>Name
            <input id="detail-node-name" type="text" value="${escapeHtml(data.name || "")}" />
          </label>
          <label>Evidence
            <textarea id="detail-node-evidence">${escapeHtml(data.evidence || extractFieldFromTitle(data.title, "Evidence"))}</textarea>
          </label>
          <label>Explanation
            <textarea id="detail-node-explanation">${escapeHtml(data.explanation || extractFieldFromTitle(data.title, "Explanation"))}</textarea>
          </label>
          <div id="detail-node-status" class="${statusClass}">${escapeHtml(detailStatusMessage)}</div>
          <div class="detail-actions">
            <button id="detail-node-save" type="submit">Save Changes</button>
            <button id="detail-node-toggle-delete" type="button">${isDeleted ? "Restore Node" : "Delete Node"}</button>
          </div>
        </form>
      `;
      renderRevisionSuggestions({ type: "node", id: data.nodeId || data.id || "" });

      const detailNodeForm = document.getElementById("detail-node-form");
      const detailNodeLabel = document.getElementById("detail-node-label");
      const detailNodeType = document.getElementById("detail-node-type");
      const detailNodeName = document.getElementById("detail-node-name");
      const detailNodeEvidence = document.getElementById("detail-node-evidence");
      const detailNodeExplanation = document.getElementById("detail-node-explanation");
      const detailNodeStatus = document.getElementById("detail-node-status");
      const detailNodeToggleDelete = document.getElementById("detail-node-toggle-delete");

      const setDetailStatus = (message, kind = "") => {
        if (!detailNodeStatus) return;
        detailNodeStatus.textContent = message || "";
        detailNodeStatus.className = kind ? `detail-status ${kind}` : "detail-status";
      };

      if (detailNodeLabel && detailNodeType) {
        detailNodeLabel.addEventListener("change", () => {
          const mapped = (schemaForm.label_to_type || {})[detailNodeLabel.value];
          if (mapped) {
            detailNodeType.value = mapped;
          }
        });
      }

      if (detailNodeForm) {
        detailNodeForm.addEventListener("submit", (event) => {
          event.preventDefault();
          [detailNodeLabel, detailNodeType, detailNodeName].forEach((field) => {
            if (field) field.classList.remove("field-invalid");
          });

          const label = String(detailNodeLabel?.value || "").trim();
          const nodeType = String(detailNodeType?.value || "").trim();
          const name = String(detailNodeName?.value || "").trim();
          const evidence = String(detailNodeEvidence?.value || "").trim();
          const explanation = String(detailNodeExplanation?.value || "").trim();

          const invalidFields = [];
          if (!label) invalidFields.push(detailNodeLabel);
          if (!nodeType) invalidFields.push(detailNodeType);
          if (!name) invalidFields.push(detailNodeName);
          if (invalidFields.length) {
            invalidFields.forEach((field) => field && field.classList.add("field-invalid"));
            setDetailStatus("Label, type, and name are required.", "error");
            return;
          }

          pushUndoState();
          const labelWrapped = wrapText(label, 18);
          const nameWrapped = wrapText(name, 24);
          const size = computeNodeSize(labelWrapped, nameWrapped);
          const updatedData = {
            ...node.data(),
            label,
            nodeType,
            name,
            evidence,
            explanation,
            labelWrapped,
            nameWrapped,
            fill: nodeFillFromType(nodeType),
            nodeWidth: size.nodeWidth,
            nodeHeight: size.nodeHeight,
          };
          updatedData.title = buildNodeTitle(updatedData);
          node.data(updatedData);
          markAsAdded(node);
          runLayout();
          syncNodeOverlay();
          updateSummary();
          showNodeDetails(node, "Node updated.", "success");
        });
      }

      if (detailNodeToggleDelete) {
        detailNodeToggleDelete.addEventListener("click", () => {
          if (node.hasClass("delete-mark")) {
            pushUndoState();
            node.removeClass("delete-mark");
            setFormStatus(deleteFormStatus, `Restored node ${data.nodeId || data.id || ""}.`, false);
            showNodeDetails(node, "Node restored.", "success");
          } else {
            pushUndoState();
            markAsDeleted(node);
            const connectedEdges = node.connectedEdges();
            if (connectedEdges.length) {
              markAsDeleted(connectedEdges);
            }
            setFormStatus(deleteFormStatus, `Marked node ${data.nodeId || data.id || ""} as deleted.`, false);
            showNodeDetails(node, "Node marked as deleted.", "success");
          }
          syncNodeOverlay();
        });
      }
    }

    function showEdgeDetails(edge, detailStatusMessage = "", detailStatusKind = "") {
      setRightPanelVisibility(true, "details");
      const data = edge.data();
      const source = edge.source().data();
      const target = edge.target().data();
      const edgeTitle = `${source.label || data.source} -> ${target.label || data.target}`;
      const isDeleted = edge.hasClass("delete-mark");
      setDetailSummary(edgeTitle);
      const relationOptions = (schemaForm.relations || []).map((relation) => {
        const selected = relation === (data.relation || data.label || "") ? " selected" : "";
        return `<option value="${escapeHtml(relation)}"${selected}>${escapeHtml(relation)}</option>`;
      }).join("");
      const rawEvidence = data.evidence || extractFieldFromTitle(data.title, "Evidence");
      const rawExplanation = data.explanation || extractFieldFromTitle(data.title, "Explanation");
      detailContent.innerHTML = `
        <div class="detail-section">
          <div class="detail-label">Selected Edge</div>
          <div class="detail-value">${escapeHtml(edgeTitle)}</div>
        </div>
        <form id="detail-edge-form" class="detail-form">
          <label>Edge ID
            <input id="detail-edge-id" type="text" value="${escapeHtml(data.id || "")}" readonly />
          </label>
          <label>Source ID
            <input id="detail-edge-source-id" type="text" value="${escapeHtml(data.source || "")}" readonly />
          </label>
          <label>Source
            <input id="detail-edge-source-label" type="text" value="${escapeHtml(`${source.label || ""}: ${source.name || ""}`)}" readonly />
          </label>
          <label>Target ID
            <input id="detail-edge-target-id" type="text" value="${escapeHtml(data.target || "")}" readonly />
          </label>
          <label>Target
            <input id="detail-edge-target-label" type="text" value="${escapeHtml(`${target.label || ""}: ${target.name || ""}`)}" readonly />
          </label>
          <label>Relation
            <select id="detail-edge-relation">${relationOptions}</select>
          </label>
          <label>Evidence
            <textarea id="detail-edge-evidence">${escapeHtml(rawEvidence)}</textarea>
          </label>
          <label>Explanation
            <textarea id="detail-edge-explanation">${escapeHtml(rawExplanation)}</textarea>
          </label>
          <div id="detail-edge-status" class="${detailStatusKind ? `detail-status ${detailStatusKind}` : "detail-status"}">${escapeHtml(detailStatusMessage)}</div>
          <div class="detail-actions">
            <button id="detail-edge-save" type="submit">Save Changes</button>
            <button id="detail-edge-toggle-delete" type="button">${isDeleted ? "Restore Edge" : "Delete Edge"}</button>
          </div>
        </form>
      `;
      renderRevisionSuggestions({
        type: "edge",
        source: data.source || "",
        target: data.target || "",
        relation: data.relation || data.label || "",
      });

      const detailEdgeForm = document.getElementById("detail-edge-form");
      const detailEdgeRelation = document.getElementById("detail-edge-relation");
      const detailEdgeEvidence = document.getElementById("detail-edge-evidence");
      const detailEdgeExplanation = document.getElementById("detail-edge-explanation");
      const detailEdgeStatus = document.getElementById("detail-edge-status");
      const detailEdgeToggleDelete = document.getElementById("detail-edge-toggle-delete");

      const setEdgeDetailStatus = (message, kind = "") => {
        if (!detailEdgeStatus) return;
        detailEdgeStatus.textContent = message || "";
        detailEdgeStatus.className = kind ? `detail-status ${kind}` : "detail-status";
      };

      if (detailEdgeForm) {
        detailEdgeForm.addEventListener("submit", (event) => {
          event.preventDefault();
          if (detailEdgeRelation) {
            detailEdgeRelation.classList.remove("field-invalid");
          }
          const relation = String(detailEdgeRelation?.value || "").trim();
          const evidence = String(detailEdgeEvidence?.value || "").trim();
          const explanation = String(detailEdgeExplanation?.value || "").trim();
          if (!relation) {
            if (detailEdgeRelation) {
              detailEdgeRelation.classList.add("field-invalid");
            }
            setEdgeDetailStatus("Relation is required.", "error");
            return;
          }

          pushUndoState();
          edge.data({
            ...edge.data(),
            label: relation,
            relation,
            evidence,
            explanation,
            title: buildEdgeTitle({
              ...edge.data(),
              label: relation,
              relation,
              evidence,
              explanation,
            }),
          });
          markAsAdded(edge);
          updateSummary();
          showEdgeDetails(edge, "Edge updated.", "success");
        });
      }

      if (detailEdgeToggleDelete) {
        detailEdgeToggleDelete.addEventListener("click", () => {
          if (edge.hasClass("delete-mark")) {
            pushUndoState();
            edge.removeClass("delete-mark");
            showEdgeDetails(edge, "Edge restored.", "success");
            return;
          }
          pushUndoState();
          markAsDeleted(edge);
          showEdgeDetails(edge, "Edge marked as deleted.", "success");
        });
      }
    }

    function extractFieldFromTitle(title, fieldName) {
      const lines = String(title || "").split("\n");
      const prefix = `${fieldName}: `;
      const line = lines.find((item) => item.startsWith(prefix));
      return line ? line.slice(prefix.length) : "";
    }

    function showAddNodeDialog() {
      const labelOptions = (schemaForm.labels || []).map((label) =>
        `<option value="${escapeHtml(label)}">${escapeHtml(label)}</option>`
      ).join("");
      const typeOptions = (schemaForm.types || []).map((type) =>
        `<option value="${escapeHtml(type)}">${escapeHtml(type)}</option>`
      ).join("");
      openModal(
        "Add Node",
        "Choose label and type from the schema, then fill the free-text fields.",
        `
          <label>Label<select id="modal-node-label">${labelOptions}</select></label>
          <label>Type<select id="modal-node-type">${typeOptions}</select></label>
          <label>Name<input id="modal-node-name" type="text" /></label>
          <label>Evidence<textarea id="modal-node-evidence"></textarea></label>
          <label>Explanation<textarea id="modal-node-explanation"></textarea></label>
        `,
        ({ showModalError }) => {
          const labelEl = document.getElementById("modal-node-label");
          const typeEl = document.getElementById("modal-node-type");
          const nameEl = document.getElementById("modal-node-name");
          const evidenceEl = document.getElementById("modal-node-evidence");
          const explanationEl = document.getElementById("modal-node-explanation");
          const label = String(labelEl?.value || "").trim();
          const nodeType = String(typeEl?.value || "").trim();
          const name = String(nameEl?.value || "").trim();
          const evidence = String(evidenceEl?.value || "").trim();
          const explanation = String(explanationEl?.value || "").trim();
          if (!label || !nodeType || !name) {
            setFormStatus(nodeFormStatus, "Label, type, and name are required.", true);
            const invalidFields = [];
            if (!label) invalidFields.push("modal-node-label");
            if (!nodeType) invalidFields.push("modal-node-type");
            if (!name) invalidFields.push("modal-node-name");
            showModalError("Label, type, and name are required.", invalidFields);
            return false;
          }
          pushUndoState();
          const nodeId = nextNodeIdForType(nodeType);
          const labelWrapped = wrapText(label, 18);
          const nameWrapped = wrapText(name, 24);
          const size = computeNodeSize(labelWrapped, nameWrapped);
          const title = [
            `ID: ${nodeId}`,
            `Label: ${label}`,
            `Name: ${name}`,
            `Type: ${nodeType}`,
            `Evidence: ${evidence}`,
            `Explanation: ${explanation}`,
          ].join("\n");
          const newNode = cy.add({
            group: "nodes",
            data: {
              id: nodeId,
              nodeId,
              label,
              name,
              nodeType,
              labelWrapped,
              nameWrapped,
              evidence,
              explanation,
              fill: nodeFillFromType(nodeType),
              nodeWidth: size.nodeWidth,
              nodeHeight: size.nodeHeight,
              title,
            },
          });
          const center = cy.extent();
          newNode.position({
            x: (center.x1 + center.x2) / 2,
            y: (center.y1 + center.y2) / 2,
          });
          markAsAdded(newNode);
          runLayout();
          updateSummary();
          showNodeDetails(newNode[0]);
          setFormStatus(nodeFormStatus, `Added node ${nodeId}.`);
          return true;
        },
      );

      const modalNodeLabel = document.getElementById("modal-node-label");
      const modalNodeType = document.getElementById("modal-node-type");
      if (modalNodeLabel && modalNodeType) {
        const syncType = () => {
          const mapped = (schemaForm.label_to_type || {})[modalNodeLabel.value];
          if (mapped) modalNodeType.value = mapped;
        };
        modalNodeLabel.addEventListener("change", syncType);
        syncType();
      }
    }

    function beginEdgeCreation() {
      edgeCreationSource = null;
      edgeCreationMode = true;
      setFormStatus(edgeFormStatus, "Left-click the source node, then left-click the target node.", false);
    }

    function showAddEdgeDialog(sourceNode, targetNode) {
      const relationOptions = (schemaForm.relations || []).map((relation) =>
        `<option value="${escapeHtml(relation)}">${escapeHtml(relation)}</option>`
      ).join("");
      openModal(
        "Add Edge",
        `Choose a relation for ${sourceNode.data("nodeId")} -> ${targetNode.data("nodeId")}.`,
        `
          <label>Relation<select id="modal-edge-relation">${relationOptions}</select></label>
          <label>Evidence<textarea id="modal-edge-evidence"></textarea></label>
          <label>Explanation<textarea id="modal-edge-explanation"></textarea></label>
        `,
        ({ showModalError }) => {
          const relationEl = document.getElementById("modal-edge-relation");
          const evidenceEl = document.getElementById("modal-edge-evidence");
          const explanationEl = document.getElementById("modal-edge-explanation");
          const relation = String(relationEl?.value || "").trim();
          const evidence = String(evidenceEl?.value || "").trim();
          const explanation = String(explanationEl?.value || "").trim();
          if (!relation) {
            setFormStatus(edgeFormStatus, "Relation is required.", true);
            showModalError("Relation is required.", ["modal-edge-relation"]);
            return false;
          }
          const sourceId = sourceNode.data("id");
          const targetId = targetNode.data("id");
          const duplicate = cy.edges().some((edge) =>
            edge.data("source") === sourceId &&
            edge.data("target") === targetId &&
            (edge.data("relation") || edge.data("label")) === relation
          );
          if (duplicate) {
            setFormStatus(edgeFormStatus, "That edge already exists.", true);
            showModalError("That edge already exists.", ["modal-edge-relation"]);
            return false;
          }
          pushUndoState();
          const newEdge = cy.add({
            group: "edges",
            data: {
              id: `e${Date.now()}`,
              source: sourceId,
              target: targetId,
              label: relation,
              relation,
              evidence,
              explanation,
              title: buildEdgeTitle({
                source: sourceId,
                target: targetId,
                label: relation,
                relation,
                evidence,
                explanation,
              }),
            },
          });
          markAsAdded(newEdge);
          runLayout();
          updateSummary();
          showEdgeDetails(newEdge[0]);
          setFormStatus(edgeFormStatus, `Added edge ${sourceId} -> ${targetId} (${relation}).`);
          return true;
        },
      );
    }

    normalizeInitialNodeSizes();
    runLayout();
    cy.once("layoutstop", ensureNameVisibleInitialViewport);
    cy.on("render layoutstop dragfree position pan zoom add remove", syncNodeOverlay);
    syncNodeOverlay();
    applyStoredRevisionHighlights();
    syncNodeOverlay();
    updateSummary();
    renderRevisionSuggestions();

    cy.on("grab", "node", (evt) => {
      const node = evt.target;
      node.scratch("_dragStartPos", { ...node.position() });
      if (!dragUndoSnapshot) {
        dragUndoSnapshot = cloneGraphSnapshot();
        dragUndoCommitted = false;
      }
    });

    cy.on("dragfree", "node", (evt) => {
      const node = evt.target;
      const startPos = node.scratch("_dragStartPos");
      if (node.removeScratch) {
        node.removeScratch("_dragStartPos");
      } else {
        node.scratch("_dragStartPos", null);
      }
      const pos = node.position();
      const moved = startPos && (startPos.x !== pos.x || startPos.y !== pos.y);
      if (dragUndoSnapshot && !dragUndoCommitted && moved) {
        pushUndoState(dragUndoSnapshot);
        dragUndoCommitted = true;
        setFormStatus(saveFormStatus, "Node position updated. Press Ctrl+Z to undo.", false);
      }
      if (!cy.$(":grabbed").length) {
        dragUndoSnapshot = null;
        dragUndoCommitted = false;
      }
    });

    if (addNodeButton) {
      addNodeButton.addEventListener("click", showAddNodeDialog);
    }
    if (addEdgeButton) {
      addEdgeButton.addEventListener("click", beginEdgeCreation);
    }
    if (deleteSelectedButton) {
      deleteSelectedButton.addEventListener("click", () => {
        const selected = cy.$(":selected");
        if (!selected || !selected.length) {
          setFormStatus(deleteFormStatus, "Select at least one node or edge first.", true);
          return;
        }
        pushUndoState();
        const nodes = selected.filter((element) => element.isNode());
        const edges = selected.filter((element) => element.isEdge());
        if (nodes.length) {
          markAsDeleted(nodes);
          markAsDeleted(nodes.connectedEdges());
        }
        if (edges.length) {
          markAsDeleted(edges);
        }
        setFormStatus(deleteFormStatus, `Marked ${selected.length} selected element(s) as deleted.`, false);
        syncNodeOverlay();
      });
    }
    if (toggleDeletedButton) {
      toggleDeletedButton.addEventListener("click", () => {
        pushUndoState();
        setDeletedVisibility(!deletedVisible);
      });
      setDeletedVisibility(true);
    }
    if (saveUpdatesButton) {
      saveUpdatesButton.addEventListener("click", exportCurrentGraph);
    }

    cy.on("tap", "node", (evt) => {
      const node = evt.target;
      if (edgeCreationMode) {
        if (node.hasClass("delete-mark")) {
          edgeCreationSource = null;
          edgeCreationMode = false;
          setFormStatus(edgeFormStatus, "Deleted nodes cannot be used to create edges.", true);
          return;
        }
        if (!edgeCreationSource) {
          edgeCreationSource = node;
          setFormStatus(edgeFormStatus, `Source selected: ${node.data("nodeId")}. Now left-click the target node.`, false);
          return;
        }
        if (node.hasClass("delete-mark")) {
          edgeCreationSource = null;
          edgeCreationMode = false;
          setFormStatus(edgeFormStatus, "Deleted nodes cannot be used to create edges.", true);
          return;
        }
        if (edgeCreationSource.id() === node.id()) {
          edgeCreationSource = null;
          edgeCreationMode = false;
          setFormStatus(edgeFormStatus, "Source and target must be different. Edge creation reset.", true);
          return;
        }
        const sourceNode = edgeCreationSource;
        edgeCreationSource = null;
        edgeCreationMode = false;
        showAddEdgeDialog(sourceNode, node);
        return;
      }

      showNodeDetails(node);
    });

    cy.on("tap", "edge", (evt) => {
      showEdgeDetails(evt.target);
    });

    cy.on("tap", (evt) => {
      if (evt.target === cy) {
        if (edgeCreationMode) {
          edgeCreationMode = false;
          edgeCreationSource = null;
          setFormStatus(edgeFormStatus, "Edge creation cancelled.", false);
        }
        cy.$(":selected").unselect();
      }
    });

    document.addEventListener("keydown", (event) => {
      if (!event.key || !(event.ctrlKey || event.metaKey)) return;
      const target = event.target;
      const tag = target && target.tagName ? target.tagName.toUpperCase() : "";
      const isEditable =
        (target && target.isContentEditable) ||
        tag === "INPUT" ||
        tag === "TEXTAREA" ||
        tag === "SELECT";
      if (isEditable) return;

      const key = event.key.toLowerCase();
      if (!event.shiftKey && key === "z") {
        event.preventDefault();
        undoLastAction();
        return;
      }
      if ((event.shiftKey && key === "z") || (!event.shiftKey && key === "y")) {
        event.preventDefault();
        redoLastAction();
      }
    });
  </script>
</body>
</html>
"""

def _render_html(
    *,
    chain_lines: Union[str, Iterable[str]],
    conditions: Union[None, str, Iterable[str]],
    hazards: Union[None, str, Iterable[str]],
    condition_color: str,
    hazard_color: str,
    neutral_color: str,
    html_path: Path,
    case_id: str | None = None
) -> Path:
    
    def _safe_case_id(s: str) -> str:

        s = s.strip()
        s = re.sub(r"\s+", "_", s)
        s = re.sub(r"[^A-Za-z0-9._-]+", "_", s)
        return s or "case"

    final_case_id = _safe_case_id(case_id or html_path.parent.name)

    lines = _to_arrow_lines(chain_lines)

    nodes = _collect_nodes_from_arrow_lines(lines)
    # Effective highlight sets (same logic as your Python version)
    condition_nodes = _load_highlight_nodes(conditions)
    hazard_nodes = _load_highlight_nodes(hazards)

    auto_condition_nodes = {n.lower() for n in nodes if "<" in n and ">" in n}
    condition_nodes |= auto_condition_nodes
    hazard_nodes -= auto_condition_nodes

    # Embed as JSON for JS
    initial_text = "\n".join(lines)

    html = _HTML_TEMPLATE
    html = html.replace("{{INITIAL_TEXT_JSON}}", json.dumps(initial_text, ensure_ascii=False))
    html = html.replace("{{CONDITIONS_JSON}}", json.dumps(sorted(condition_nodes), ensure_ascii=False))
    html = html.replace("{{HAZARDS_JSON}}", json.dumps(sorted(hazard_nodes), ensure_ascii=False))
    html = html.replace("{{HAZARD_COLORS_JSON}}", json.dumps(HAZARD_COLORS, ensure_ascii=False))
    html = html.replace("{{CONDITION_COLOR}}", condition_color)
    html = html.replace("{{HAZARD_COLOR}}", hazard_color)
    html = html.replace("{{NEUTRAL_COLOR}}", neutral_color)
    html = html.replace("{{CASE_ID_JSON}}", json.dumps(final_case_id, ensure_ascii=False))
    html = html.replace("{{TRACK_DIFF_JSON}}", "null")
    html = html.replace("{{DELETED_VISIBLE_JSON}}", "true")

    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html, encoding="utf-8")
    return html_path


def _render_json_graph_html(
    *,
    graph_elements: Dict[str, List[Dict[str, object]]],
    schema_form_options: Dict[str, object],
    review_suggestions: Dict[str, object] | None,
    revision_decisions: Dict[str, object] | None,
    deleted_visible: bool = True,
    html_path: Path,
    case_id: str | None = None,
) -> Path:
    page_title = f"Interactive Causal Graph - {case_id or html_path.parent.name} [{STYLE_VERSION}]"
    html = _JSON_GRAPH_HTML_TEMPLATE
    html = html.replace("{{PAGE_TITLE}}", page_title)
    html = html.replace(
        "{{GRAPH_ELEMENTS_JSON}}",
        json.dumps(graph_elements, ensure_ascii=False),
    )
    html = html.replace(
        "{{SCHEMA_FORM_JSON}}",
        json.dumps(schema_form_options, ensure_ascii=False),
    )
    html = html.replace(
        "{{REVIEW_SUGGESTIONS_JSON}}",
        json.dumps(review_suggestions or {}, ensure_ascii=False),
    )
    html = html.replace(
        "{{REVISION_DECISIONS_JSON}}",
        json.dumps(revision_decisions or {}, ensure_ascii=False),
    )
    html = html.replace(
        "{{DELETED_VISIBLE_JSON}}",
        "true" if deleted_visible else "false",
    )
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html, encoding="utf-8")
    return html_path


# ============================================================
# Main function: draw_causal_graph_interactive
# ============================================================

def draw_causal_graph_interactive(
    chain_lines: Union[str, Iterable[str]],
    rankdir: str = "LR",
    width: int = 28,
    conditions: Union[None, str, Iterable[str]] = None,
    hazards: Union[None, str, Iterable[str]] = None,
    condition_color: str = "#cfe8ff",
    hazard_color: str = "#ffcccc",
    neutral_color: str = "#f9f9f9",
    *,
    save_path: Optional[Union[str, os.PathLike]] = None,
    fmt: str = "png",
    dpi: int = 200,
    case_id: str | None = None,
):
    """
    Render a causal graph.

    If save_path ends with .html (or fmt == "html"), generates an interactive HTML
    using Cytoscape.js + Dagre (CDN). Returns the output path.

    Otherwise, renders a static graph with Graphviz (requires 'graphviz' Python package
    and Graphviz installed). Returns the output path, or returns the Digraph object if
    save_path is None.

    Parameters mirror your original function for drop-in use.
    """
    if save_path is None:
        # preserve backward-compatible behavior: return a Digraph for static output
        # for HTML, require save_path because returning HTML string isn't expected
        if fmt.lower() in ("html", "htm"):
            raise ValueError("For interactive HTML output, please provide save_path ending with .html.")
        try:
            from graphviz import Digraph
        except Exception as e:
            raise RuntimeError("graphviz is required for static rendering. Install 'graphviz' Python package.") from e

        # Build static Digraph
        lines = _to_arrow_lines(chain_lines)

        # sanitize nodes in lines
        san_lines = []
        for ln in lines:
            if "->" not in ln:
                continue
            src, dst = ln.split("->", 1)
            src_s = _sanitize_name(src.strip())
            dst_s = _sanitize_name(dst.strip())
            san_lines.append(f"{src_s} -> {dst_s}")
        lines = san_lines
        nodes = [_sanitize_name(n) for n in _collect_nodes_from_arrow_lines(lines)]

        condition_nodes = _load_highlight_nodes(conditions)
        hazard_nodes = _load_highlight_nodes(hazards)
        auto_condition_nodes = {n.lower() for n in nodes if "<" in n and ">" in n}
        condition_nodes |= auto_condition_nodes
        hazard_nodes -= auto_condition_nodes

        dot = Digraph(format=fmt)
        dot.attr(rankdir=rankdir, dpi=str(dpi), bgcolor="white", splines="true",
                 ranksep="1.2", nodesep="0.5", pad="0.3", concentrate="false")
        dot.attr("node", shape="box", style="rounded,filled", color="#aaaaaa",
                 fontname="Helvetica", fontsize="10", penwidth="0.8")
        dot.attr("edge", color="#55555580", penwidth="1", arrowsize="0.7")

        id_map: Dict[str, str] = {}
        for name in nodes:
            key = name.lower()
            if key not in id_map:
                id_map[key] = f"n{len(id_map)}"

        for name in nodes:
            safe_name = _sanitize_name(name)
            label = _wrap_label(safe_name, width=width)
            node_id = id_map[safe_name.lower()]
            lower = safe_name.lower()
            hazard_tag = _extract_hazard_tag(safe_name)

            if hazard_tag:
                fill = HAZARD_COLORS.get(hazard_tag, condition_color)
            elif _is_hazard_consequence_node(safe_name):
                fill = hazard_color
            elif lower in hazard_nodes:
                fill = hazard_color
            elif lower in condition_nodes:
                fill = condition_color
            else:
                fill = neutral_color

            dot.node(node_id, label=label, fillcolor=fill)

        for line in lines:
            if "->" not in line:
                continue
            src, dst = [part.strip() for part in line.split("->", 1)]
            src = _sanitize_name(src)
            dst = _sanitize_name(dst)
            dot.edge(id_map[src.lower()], id_map[dst.lower()])

        return dot

    # save_path provided
    out_path = Path(save_path)
    ext = out_path.suffix.lower()
    if fmt.lower() in ("html", "htm") or ext in (".html", ".htm"):
        return _render_html(
            chain_lines=chain_lines,
            conditions=conditions,
            hazards=hazards,
            condition_color=condition_color,
            hazard_color=hazard_color,
            neutral_color=neutral_color,
            html_path=out_path,
            case_id=case_id,
        )

    # static output via graphviz
    try:
        from graphviz import Digraph
    except Exception as e:
        raise RuntimeError("graphviz is required for static rendering. Install 'graphviz' Python package.") from e

    dot = draw_causal_graph_interactive(
        chain_lines=chain_lines,
        rankdir=rankdir,
        width=width,
        conditions=conditions,
        hazards=hazards,
        condition_color=condition_color,
        hazard_color=hazard_color,
        neutral_color=neutral_color,
        save_path=None,
        fmt=fmt,
        dpi=dpi,
    )
    # dot is Digraph
    base_no_ext = out_path.with_suffix("")  # graphviz adds its own extension
    dot.format = ext.lstrip(".") if ext else fmt
    rendered = dot.render(str(base_no_ext), cleanup=True)

    # normalize double extensions sometimes produced by graphviz wrapper
    if rendered.endswith(f".{dot.format}.{dot.format}"):
        fixed = rendered[: -(len(dot.format) + 1)]
        os.replace(rendered, fixed)
        rendered = fixed
    return Path(rendered)


def draw_causal_graph_interactive_from_json(
    identify_accident_scenario: Union[str, os.PathLike, Dict[str, object]],
    causal_edge_linking: Union[str, os.PathLike, Dict[str, object]],
    *,
    save_path: Union[str, os.PathLike],
    accident_scenario_schema: Union[str, os.PathLike, Dict[str, object], None] = None,
    review_causal_graph: Union[str, os.PathLike, Dict[str, object], None] = None,
    revision_decisions: Union[str, os.PathLike, Dict[str, object], None] = None,
    case_id: str | None = None,
    width: int = 26,
) -> Path:
    scenario_payload = _load_json_payload(identify_accident_scenario)
    edge_payload = _load_json_payload(causal_edge_linking)
    schema_payload = (
        _load_json_payload(accident_scenario_schema)
        if accident_scenario_schema is not None
        else {}
    )
    review_payload = (
        _load_json_payload(review_causal_graph)
        if review_causal_graph is not None
        else {}
    )
    revision_decisions_payload = (
        _load_json_payload(revision_decisions)
        if revision_decisions is not None
        else {}
    )
    if not isinstance(scenario_payload, dict):
        raise TypeError("identify_accident_scenario must resolve to a JSON object.")
    if not isinstance(edge_payload, dict):
        raise TypeError("causal_edge_linking must resolve to a JSON object.")
    if not isinstance(schema_payload, dict):
        raise TypeError("accident_scenario_schema must resolve to a JSON object.")
    if not isinstance(review_payload, dict):
        raise TypeError("review_causal_graph must resolve to a JSON object.")
    if not isinstance(revision_decisions_payload, dict):
        raise TypeError("revision_decisions must resolve to a JSON object.")

    graph_elements = _build_elements_from_json_graph(
        scenario_payload,
        edge_payload,
        width=width,
    )
    schema_form_options = _build_schema_form_options(schema_payload)
    return _render_json_graph_html(
        graph_elements=graph_elements,
        schema_form_options=schema_form_options,
        review_suggestions=review_payload,
        revision_decisions=revision_decisions_payload.get("review_decisions", revision_decisions_payload),
        deleted_visible=bool(revision_decisions_payload.get("deleted_visible", True)),
        html_path=Path(save_path),
        case_id=case_id,
    )


def draw_updated_causal_graph_interactive_from_json(
    updated_causal_graph: Union[str, os.PathLike, Dict[str, object]],
    *,
    save_path: Union[str, os.PathLike],
    accident_scenario_schema: Union[str, os.PathLike, Dict[str, object], None] = None,
    review_causal_graph: Union[str, os.PathLike, Dict[str, object], None] = None,
    revision_decisions: Union[str, os.PathLike, Dict[str, object], None] = None,
    case_id: str | None = None,
    width: int = 26,
) -> Path:
    output_html_path = Path(save_path)
    updated_payload = _load_json_payload(updated_causal_graph)
    schema_payload = (
        _load_json_payload(accident_scenario_schema)
        if accident_scenario_schema is not None
        else {}
    )
    review_payload = (
        _load_json_payload(review_causal_graph)
        if review_causal_graph is not None
        else {}
    )
    revision_decisions_payload = (
        _load_json_payload(revision_decisions)
        if revision_decisions is not None
        else {}
    )
    if not isinstance(updated_payload, dict):
        raise TypeError("updated_causal_graph must resolve to a JSON object.")
    if not isinstance(schema_payload, dict):
        raise TypeError("accident_scenario_schema must resolve to a JSON object.")
    if not isinstance(review_payload, dict):
        raise TypeError("review_causal_graph must resolve to a JSON object.")
    if not isinstance(revision_decisions_payload, dict):
        raise TypeError("revision_decisions must resolve to a JSON object.")

    graph_elements = _build_elements_from_json_graph(
        updated_payload,
        updated_payload,
        width=width,
    )
    _ensure_unique_element_ids(graph_elements)
    schema_form_options = _build_schema_form_options(schema_payload)
    return _render_json_graph_html(
        graph_elements=graph_elements,
        schema_form_options=schema_form_options,
        review_suggestions=review_payload,
        revision_decisions=revision_decisions_payload.get("review_decisions", revision_decisions_payload),
        deleted_visible=bool(revision_decisions_payload.get("deleted_visible", True)),
        html_path=output_html_path,
        case_id=case_id,
    )
