from __future__ import annotations

from typing import Any, Dict, List, Tuple
import json
import ast
import os

from .edges import Edge, extract_edges, format_edges
from .rules import (
    # remove_condition_short_circuits,
    remove_short_circuit_edges_any_length,
    normalize_hazard_numbering,
    remove_tagged_reverse_edges,
    remove_hazard_upstream_edges,
    connect_tagged_conditions_to_hazards,
)


def _strip_invisible(s: str) -> str:
    return (
        s.replace("\ufeff", "")
        .replace("\u200b", "")
        .replace("\u00a0", " ")
        .strip()
    )


def _maybe_load_json_file(path: str):
    p = _strip_invisible(path)
    if p.startswith("{") or p.startswith("["):
        return None

    candidates = [p, p.replace("\\", os.sep), os.path.normpath(p)]
    for cand in candidates:
        if os.path.exists(cand) and os.path.isfile(cand) and cand.lower().endswith(".json"):
            with open(cand, "r", encoding="utf-8") as f:
                return json.load(f)
    return None


def _extract_json_object_block(s: str) -> str | None:
    s = _strip_invisible(s)
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return s[start:end + 1]


def _extract_json_array_block(s: str) -> str | None:
    s = _strip_invisible(s)
    start = s.find("[")
    end = s.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return None
    return s[start:end + 1]


def _coerce_conditions(x: Any) -> Dict[str, List[str]]:
    if isinstance(x, dict):
        return x

    if isinstance(x, str):
        s = _strip_invisible(x)

        obj = _maybe_load_json_file(s)
        if isinstance(obj, dict):
            return obj

        try:
            obj = json.loads(s)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass

        block = _extract_json_object_block(s)
        if block:
            try:
                obj = json.loads(block)
                if isinstance(obj, dict):
                    return obj
            except Exception:
                pass

        try:
            obj = ast.literal_eval(s)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass

        if block:
            try:
                obj = ast.literal_eval(block)
                if isinstance(obj, dict):
                    return obj
            except Exception:
                pass

    raise TypeError(
        f"conditions must be dict, JSON string of dict, or path to .json dict; got {type(x)}"
    )


def _coerce_hazard_consequence(x: Any) -> List[str]:
    if isinstance(x, list):
        return x

    if isinstance(x, str):
        s = _strip_invisible(x)

        obj = _maybe_load_json_file(s)
        if isinstance(obj, list):
            return obj
        if isinstance(obj, dict) and "hazards" in obj and isinstance(obj["hazards"], list):
            return obj["hazards"]

        try:
            obj = json.loads(s)
            if isinstance(obj, list):
                return obj
        except Exception:
            pass

        block = _extract_json_array_block(s)
        if block:
            try:
                obj = json.loads(block)
                if isinstance(obj, list):
                    return obj
            except Exception:
                pass

        try:
            obj = ast.literal_eval(s)
            if isinstance(obj, list):
                return obj
        except Exception:
            pass

        if block:
            try:
                obj = ast.literal_eval(block)
                if isinstance(obj, list):
                    return obj
            except Exception:
                pass

    raise TypeError(
        f"hazard_consequence must be list, JSON string of list, or path to .json list; got {type(x)}"
    )


def process_combined_text(
    combined_text: str,
    *,
    conditions,
    hazard_consequence,
    dedupe_edges: bool = False,
) -> str:
    conditions = _coerce_conditions(conditions)
    hazard_consequence = _coerce_hazard_consequence(hazard_consequence)

    edges = extract_edges(combined_text, dedupe=dedupe_edges)

    edges = remove_short_circuit_edges_any_length(
        edges,
    )

    edges = remove_tagged_reverse_edges(edges)

    edges = remove_hazard_upstream_edges(
        edges,
        hazard_consequence=hazard_consequence,
    )

    edges = connect_tagged_conditions_to_hazards(
        edges,
        hazard_consequence=hazard_consequence,
    )

    edges = normalize_hazard_numbering(
        edges,
        hazard_consequence=hazard_consequence,
    )

    return format_edges(edges)


def _ordered_removed(before: List[Edge], after: List[Edge]) -> List[Edge]:
    after_set = set(after)
    return [e for e in before if e not in after_set]


def process_combined_text_with_report(
    combined_text: str,
    *,
    conditions,
    hazard_consequence,
    dedupe_edges: bool = False,
) -> Tuple[str, Dict[str, List[str]]]:
    conditions = _coerce_conditions(conditions)
    hazard_consequence = _coerce_hazard_consequence(hazard_consequence)

    extraction_input = extract_edges(combined_text, dedupe=False)
    edges = extract_edges(combined_text, dedupe=dedupe_edges)

    removed_by_reason: Dict[str, List[str]] = {
        "deduplicated_edges": [],
        "condition_short_circuit_edges": [],
        "tagged_reverse_edges": [],
        "hazard_upstream_edges": [],
        "added_tagged_condition_to_hazard_edges": [],
    }

    if dedupe_edges:
        removed_by_reason["deduplicated_edges"] = [
            e.as_text() for e in _ordered_removed(extraction_input, edges)
        ]

    before = edges
    edges = remove_short_circuit_edges_any_length(
        edges,
    )
    removed_by_reason["remove_short_circuit_edges_any_length"] = [
        e.as_text() for e in _ordered_removed(before, edges)
    ]

    before = edges
    edges = remove_tagged_reverse_edges(edges)
    removed_by_reason["tagged_reverse_edges"] = [
        e.as_text() for e in _ordered_removed(before, edges)
    ]

    before = edges
    edges = remove_hazard_upstream_edges(
        edges,
        hazard_consequence=hazard_consequence,
    )
    removed_by_reason["hazard_upstream_edges"] = [
        e.as_text() for e in _ordered_removed(before, edges)
    ]

    before = edges
    edges = connect_tagged_conditions_to_hazards(
        edges,
        hazard_consequence=hazard_consequence,
    )
    before_set = set(before)
    removed_by_reason["added_tagged_condition_to_hazard_edges"] = [
        e.as_text() for e in edges if e not in before_set
    ]

    edges = normalize_hazard_numbering(
        edges,
        hazard_consequence=hazard_consequence,
    )

    return format_edges(edges), removed_by_reason
