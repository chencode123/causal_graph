#!/usr/bin/env python3
"""
Repair missing revision decision state by comparing review suggestions with the
current graph embedded in updated_causal_graph.html.

This script updates, for each case folder:
  - updated_causal_graph.html: const initialRevisionDecisions = {...}
  - updated_causal_graph_review_state.json: {"review_decisions": {...}, ...}

It does not infer manual edits that were not represented in reviewSuggestions.

Examples:
  python scripts/repair_revision_decisions.py runs/stability_test/rounds/round_1 --recursive --dry-run
  python scripts/repair_revision_decisions.py runs/stability_test/rounds/round_1 --recursive
  python scripts/repair_revision_decisions.py runs/stability_test/rounds/round_1/batch_1/1
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


HTML_FILE_NAME = "updated_causal_graph.html"
REVIEW_STATE_FILE_NAME = "updated_causal_graph_review_state.json"

# ============================================================
# Editable defaults for direct runs with no command-line args.
# Command-line args still take priority when provided.
# ============================================================
DEFAULT_PATHS = [
    r"runs\stability_test\rounds\round_1",  # Example specific batch folder
]
DEFAULT_RECURSIVE = True
DEFAULT_DRY_RUN = False
DEFAULT_BACKUP = False
DEFAULT_MARK_UNKNOWN = ""


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


@dataclass
class CaseResult:
    case_dir: Path
    status: str
    decisions: dict[str, str]
    changed_html: bool = False
    changed_state: bool = False
    message: str = ""


def normalize(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def decision_status(value: Any) -> str:
    if isinstance(value, dict):
        return normalize(value.get("status"))
    return normalize(value)


def find_json_after_const(text: str, var_name: str) -> tuple[Any, int, int]:
    marker = re.search(rf"\bconst\s+{re.escape(var_name)}\s*=\s*", text)
    if not marker:
        raise ValueError(f"Could not find const {var_name}")

    start = marker.end()
    while start < len(text) and text[start].isspace():
        start += 1

    if start >= len(text) or text[start] not in "{[":
        raise ValueError(f"const {var_name} does not start with JSON object/array")

    open_char = text[start]
    close_char = "}" if open_char == "{" else "]"
    depth = 0
    in_string = False
    escape = False

    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                end = index + 1
                return json.loads(text[start:end]), start, end

    raise ValueError(f"Could not parse JSON for const {var_name}")


def replace_const_json(text: str, var_name: str, value: Any) -> tuple[str, bool]:
    _, start, end = find_json_after_const(text, var_name)
    replacement = json.dumps(value, ensure_ascii=False)
    updated = text[:start] + replacement + text[end:]
    return updated, updated != text


def get_elements_and_suggestions(html_text: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    elements, _, _ = find_json_after_const(html_text, "elements")
    suggestions, _, _ = find_json_after_const(html_text, "reviewSuggestions")
    try:
        decisions, _, _ = find_json_after_const(html_text, "initialRevisionDecisions")
    except ValueError:
        decisions = {}
    if not isinstance(elements, dict):
        raise ValueError("elements is not an object")
    if not isinstance(suggestions, dict):
        raise ValueError("reviewSuggestions is not an object")
    if not isinstance(decisions, dict):
        decisions = {}
    return elements, suggestions, decisions


def node_data_by_id(elements: dict[str, Any]) -> dict[str, dict[str, Any]]:
    nodes = {}
    for item in elements.get("nodes") or []:
        data = item.get("data") if isinstance(item, dict) else None
        if not isinstance(data, dict):
            continue
        for key in (data.get("id"), data.get("nodeId"), data.get("node_id")):
            if key:
                nodes[str(key)] = data
    return nodes


def edge_data_list(elements: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for item in elements.get("edges") or []:
        data = item.get("data") if isinstance(item, dict) else None
        if isinstance(data, dict):
            out.append(data)
    return out


def get_node_field(data: dict[str, Any], field: str) -> Any:
    aliases = {
        "id": ("id", "nodeId", "node_id"),
        "node_id": ("nodeId", "id", "node_id"),
        "node_type": ("nodeType", "node_type", "type"),
        "nodeType": ("nodeType", "node_type", "type"),
    }
    for candidate in aliases.get(field, (field,)):
        if candidate in data:
            return data[candidate]
    return None


def parse_state_string(value: str) -> dict[str, str]:
    """
    Best-effort parser for strings like:
      label: IntermediateEvent
      name -> Foo
      "direct quote"
    """
    text = value.strip().strip('"')
    if not text:
        return {}

    fields = {}
    for part in re.split(r"\s*[,;]\s*", text):
        match = re.match(r"(?i)^\s*(label|name|node_type|type|evidence|explanation)\s*(?::|->)\s*(.+?)\s*$", part)
        if match:
            key = match.group(1).lower()
            if key == "type":
                key = "node_type"
            fields[key] = match.group(2).strip().strip('"')
    return fields


def node_state_matches(data: dict[str, Any], state: Any, change_type: str = "") -> bool:
    if not isinstance(data, dict):
        return False

    if isinstance(state, dict):
        if not state:
            return False
        return all(normalize(get_node_field(data, key)) == normalize(value) for key, value in state.items())

    if isinstance(state, str):
        fields = parse_state_string(state)
        if fields:
            return all(normalize(get_node_field(data, key)) == normalize(value) for key, value in fields.items())

        change_type = normalize(change_type)
        candidates = []
        if change_type == "rename":
            candidates = [data.get("name")]
        elif change_type == "relabel":
            candidates = [data.get("label")]
        elif change_type == "retype":
            candidates = [data.get("nodeType"), data.get("node_type")]
        elif change_type == "update_evidence":
            candidates = [data.get("evidence")]
        elif change_type in {"update_explanation", "clarify_role"}:
            candidates = [data.get("explanation")]
        else:
            candidates = [data.get("label"), data.get("name"), data.get("nodeType"), data.get("evidence"), data.get("explanation")]
        return any(normalize(candidate) == normalize(state.strip().strip('"')) for candidate in candidates)

    return False


def suggested_node_signature(item: dict[str, Any]) -> tuple[str, str, str]:
    node_id = item.get("node_id") or item.get("nodeId") or item.get("id") or item.get("suggested_node_id")
    label = item.get("label") or item.get("suggested_label")
    name = item.get("name") or item.get("suggested_name")
    node_type = item.get("node_type") or item.get("nodeType") or item.get("suggested_node_type")
    return normalize(node_id), normalize(label), normalize(name) or normalize(item.get("description")), normalize(node_type)


def find_node_addition(nodes: dict[str, dict[str, Any]], item: dict[str, Any]) -> bool:
    node_id, label, name, node_type = suggested_node_signature(item)
    if node_id and node_id in {normalize(key) for key in nodes}:
        return True
    for data in nodes.values():
        label_ok = not label or normalize(data.get("label")) == label
        name_ok = not name or normalize(data.get("name")) == name
        type_ok = not node_type or normalize(data.get("nodeType") or data.get("node_type")) == node_type
        if label_ok and name_ok and type_ok:
            return True
    return False


def node_target_id(item: dict[str, Any]) -> str:
    return str(
        item.get("target_id")
        or item.get("node_id")
        or item.get("nodeId")
        or item.get("id")
        or ""
    )


def edge_tuple(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        normalize(item.get("source")),
        normalize(item.get("target")),
        normalize(item.get("relation") or item.get("label")),
    )


def edge_exists(edges: list[dict[str, Any]], item: dict[str, Any]) -> bool:
    source, target, relation = edge_tuple(item)
    for edge in edges:
        edge_key = (
            normalize(edge.get("source")),
            normalize(edge.get("target")),
            normalize(edge.get("relation") or edge.get("label")),
        )
        if edge_key == (source, target, relation):
            return True
    return False


def edge_update_matches(edges: list[dict[str, Any]], item: dict[str, Any]) -> bool:
    source, target, relation = edge_tuple(item)
    candidates = [
        edge for edge in edges
        if normalize(edge.get("source")) == source and normalize(edge.get("target")) == target
    ]
    if relation:
        candidates = [edge for edge in candidates if normalize(edge.get("relation") or edge.get("label")) == relation]
    if not candidates:
        return False

    suggested = item.get("suggested_state") or {}
    if isinstance(suggested, dict) and suggested:
        for edge in candidates:
            if all(normalize(edge.get(key)) == normalize(value) for key, value in suggested.items()):
                return True
    if isinstance(suggested, str) and suggested.strip():
        parsed = parse_state_string(suggested)
        if parsed:
            for edge in candidates:
                if all(normalize(edge.get(key)) == normalize(value) for key, value in parsed.items()):
                    return True
    return False


def infer_decisions(
    elements: dict[str, Any],
    suggestions: dict[str, Any],
    existing_decisions: dict[str, Any] | None = None,
    mark_unknown: str = "",
) -> dict[str, str]:
    nodes = node_data_by_id(elements)
    edges = edge_data_list(elements)
    existing_decisions = existing_decisions or {}
    decisions: dict[str, str] = {}

    def preserve_or_unknown(key: str) -> None:
        existing = decision_status(existing_decisions.get(key))
        if existing in {"accepted", "rejected"}:
            decisions[key] = existing
        elif mark_unknown in {"accepted", "rejected"}:
            decisions[key] = mark_unknown

    for index, item in enumerate(suggestions.get("node_updates") or []):
        if not isinstance(item, dict):
            continue
        key = f"node_update_{index}"
        data = nodes.get(node_target_id(item))
        if data and node_state_matches(data, item.get("suggested_state"), item.get("change_type")):
            decisions[key] = "accepted"
        elif data and node_state_matches(data, item.get("current_state"), item.get("change_type")):
            decisions[key] = "rejected"
        else:
            preserve_or_unknown(key)

    for index, item in enumerate(suggestions.get("node_additions") or []):
        if not isinstance(item, dict):
            continue
        key = f"node_addition_{index}"
        decisions[key] = "accepted" if find_node_addition(nodes, item) else "rejected"

    for index, item in enumerate(suggestions.get("node_deletions") or []):
        if not isinstance(item, dict):
            continue
        key = f"node_deletion_{index}"
        target = node_target_id(item)
        decisions[key] = "accepted" if target and target not in nodes else "rejected"

    for index, item in enumerate(suggestions.get("edge_additions") or []):
        if not isinstance(item, dict):
            continue
        key = f"edge_addition_{index}"
        decisions[key] = "accepted" if edge_exists(edges, item) else "rejected"

    for index, item in enumerate(suggestions.get("edge_deletions") or []):
        if not isinstance(item, dict):
            continue
        key = f"edge_deletion_{index}"
        decisions[key] = "accepted" if not edge_exists(edges, item) else "rejected"

    for index, item in enumerate(suggestions.get("edge_updates") or []):
        if not isinstance(item, dict):
            continue
        key = f"edge_update_{index}"
        if edge_update_matches(edges, item):
            decisions[key] = "accepted"
        else:
            preserve_or_unknown(key)

    return decisions


def load_review_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"review_decisions": {}, "deleted_nodes": [], "deleted_edges": [], "deleted_visible": True}
    data = json.loads(read_text(path))
    if not isinstance(data, dict):
        return {"review_decisions": {}, "deleted_nodes": [], "deleted_edges": [], "deleted_visible": True}
    data.setdefault("review_decisions", {})
    data.setdefault("deleted_nodes", [])
    data.setdefault("deleted_edges", [])
    data.setdefault("deleted_visible", True)
    return data


def write_review_state(path: Path, state: dict[str, Any], dry_run: bool) -> bool:
    old_text = read_text(path) if path.exists() else ""
    new_text = json.dumps(state, indent=2, ensure_ascii=False) + "\n"
    changed = old_text != new_text
    if changed and not dry_run:
        path.write_text(new_text, encoding="utf-8")
    return changed


def repair_case(case_dir: Path, dry_run: bool, backup: bool, mark_unknown: str) -> CaseResult:
    html_path = case_dir / HTML_FILE_NAME
    state_path = case_dir / REVIEW_STATE_FILE_NAME
    if not html_path.exists():
        return CaseResult(case_dir, "skipped", {}, message=f"missing {HTML_FILE_NAME}")

    html_text = read_text(html_path)
    try:
        elements, suggestions, html_decisions = get_elements_and_suggestions(html_text)
    except Exception as exc:
        return CaseResult(case_dir, "failed", {}, message=str(exc))

    state = load_review_state(state_path)
    state_decisions = state.get("review_decisions")
    existing_decisions = state_decisions if isinstance(state_decisions, dict) and state_decisions else html_decisions
    decisions = infer_decisions(elements, suggestions, existing_decisions, mark_unknown=mark_unknown)

    updated_html, changed_html = replace_const_json(html_text, "initialRevisionDecisions", decisions)
    state["review_decisions"] = decisions
    changed_state = write_review_state(state_path, state, dry_run=dry_run)

    if changed_html and not dry_run:
        if backup:
            backup_path = html_path.with_suffix(html_path.suffix + ".bak")
            if not backup_path.exists():
                backup_path.write_text(html_text, encoding="utf-8")
        html_path.write_text(updated_html, encoding="utf-8")

    return CaseResult(
        case_dir=case_dir,
        status="updated" if changed_html or changed_state else "unchanged",
        decisions=decisions,
        changed_html=changed_html,
        changed_state=changed_state,
    )


def find_case_dirs(paths: list[Path], recursive: bool) -> list[Path]:
    case_dirs: set[Path] = set()
    for path in paths:
        if path.is_file() and path.name == HTML_FILE_NAME:
            case_dirs.add(path.parent)
        elif path.is_dir() and (path / HTML_FILE_NAME).exists():
            case_dirs.add(path)
        elif path.is_dir() and recursive:
            case_dirs.update(p.parent for p in path.rglob(HTML_FILE_NAME))
    return sorted(case_dirs)


def format_result(result: CaseResult) -> str:
    accepted = sum(1 for value in result.decisions.values() if value == "accepted")
    rejected = sum(1 for value in result.decisions.values() if value == "rejected")
    total = len(result.decisions)
    changes = []
    if result.changed_html:
        changes.append("html")
    if result.changed_state:
        changes.append("state")
    change_text = ",".join(changes) if changes else "-"
    suffix = f" | {result.message}" if result.message else ""
    return (
        f"{result.status:9} {result.case_dir} "
        f"| decisions={total} accepted={accepted} rejected={rejected} changed={change_text}{suffix}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair missing revision decisions from updated graph state.")
    parser.add_argument("paths", nargs="*", help="Case folder, updated_causal_graph.html, or root directory.")
    parser.add_argument("--recursive", action="store_true", help="Search recursively for updated_causal_graph.html.")
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing files.")
    parser.add_argument("--backup", action="store_true", help="Create .bak backup next to each changed HTML file.")
    parser.add_argument(
        "--mark-unknown",
        choices=["", "accepted", "rejected"],
        default="",
        help="Status to use when a suggestion cannot be inferred. Default keeps existing known status or omits it.",
    )
    args = parser.parse_args()

    raw_paths = args.paths or DEFAULT_PATHS
    recursive = args.recursive if args.paths else DEFAULT_RECURSIVE
    dry_run = args.dry_run if args.paths else DEFAULT_DRY_RUN
    backup = args.backup if args.paths else DEFAULT_BACKUP
    mark_unknown = args.mark_unknown if args.paths else DEFAULT_MARK_UNKNOWN

    paths = [Path(value) for value in raw_paths]
    missing = [path for path in paths if not path.exists()]
    for path in missing:
        print(f"ERROR: path not found: {path}")
    paths = [path for path in paths if path.exists()]
    if not paths:
        return 2

    case_dirs = find_case_dirs(paths, recursive=recursive)
    if not case_dirs:
        print("No updated_causal_graph.html files found.")
        return 1

    results = [repair_case(case_dir, dry_run, backup, mark_unknown) for case_dir in case_dirs]
    for result in results:
        print(format_result(result))

    failed = sum(1 for result in results if result.status == "failed")
    updated = sum(1 for result in results if result.status == "updated")
    unchanged = sum(1 for result in results if result.status == "unchanged")
    skipped = sum(1 for result in results if result.status == "skipped")
    mode = "dry-run" if dry_run else "write"
    print(f"Summary ({mode}): updated={updated}, unchanged={unchanged}, skipped={skipped}, failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
