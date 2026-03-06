from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Union
import json

from utils.causal_postprocess import process_combined_text_with_report


def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def write_text(p: Path, s: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s, encoding="utf-8")


JSONLike = Union[Dict[str, Any], list]
TaxonomyInput = Union[Path, str, JSONLike]


def _load_json_if_path(x: TaxonomyInput, *, name: str) -> JSONLike:
    if isinstance(x, (dict, list)):
        return x

    if isinstance(x, Path):
        try:
            return json.loads(read_text(x))
        except FileNotFoundError as e:
            raise FileNotFoundError(f"{name} path not found: {x}") from e
        except json.JSONDecodeError as e:
            raise ValueError(f"{name} is not valid JSON: {x}") from e
        except Exception as e:
            raise ValueError(f"Failed to load {name} from path: {x}") from e

    if isinstance(x, str):
        p = Path(x)
        if p.exists():
            try:
                return json.loads(read_text(p))
            except json.JSONDecodeError as e:
                raise ValueError(f"{name} is not valid JSON: {p}") from e
            except Exception as e:
                raise ValueError(f"Failed to load {name} from path: {p}") from e
        raise TypeError(
            f"{name} received a string that is not a file path: {x!r}. "
            f"Pass a Path, dict, or list."
        )

    raise TypeError(
        f"{name} must be a Path/str path to JSON, or a dict/list. Got: {type(x).__name__}"
    )


def build_prep_final_check_vars(
    folder: Path,
    hazards_json: TaxonomyInput,
    conditions_json: TaxonomyInput,
    chain_hazards: Path | None = None,
    chain_conditions_events: Path | None = None,
    *,
    step_key: str = "prep_final_check",
    dedupe_edges: bool = True,
) -> Dict[str, Any]:
    hazards_obj = _load_json_if_path(hazards_json, name="hazards_json")
    conditions_obj = _load_json_if_path(conditions_json, name="conditions_json")

    required_inputs = {
        "chain_hazards": chain_hazards,
        "chain_conditions_events": chain_conditions_events,
    }
    missing = [name for name, p in required_inputs.items() if p is None or not p.exists()]
    if missing:
        raise FileNotFoundError(
            f"{step_key} missing upstream outputs in {folder}: {', '.join(missing)}"
        )

    combined_text = (
        read_text(chain_hazards)
        + "\n\n"
        + read_text(chain_conditions_events)
    )

    processed_text, removed_edges_report = process_combined_text_with_report(
        combined_text=combined_text,
        conditions=conditions_obj,
        hazard_consequence=hazards_obj,
        dedupe_edges=dedupe_edges,
    )

    output_filename = f"{step_key}_output.txt"
    write_text(folder / output_filename, processed_text)

    removed_edges_report_filename = f"{step_key}_removed_edges_report.txt"
    removed_edges_report_text = _format_removed_edges_report_text(
        removed_edges_report
    )
    write_text(folder / removed_edges_report_filename, removed_edges_report_text)

    return {
        "prep_ok": True,
        "processed_text_path": output_filename,
        "removed_edges_report_path": removed_edges_report_filename,
    }


def _format_removed_edges_report_text(removed_edges_report: Dict[str, list]) -> str:
    reason_labels = {
        "deduplicated_edges": "Deduplicated Edges",
        "remove_short_circuit_edges_any_length": "Short-Circuit Edges",
        "tagged_reverse_edges": "Tagged Reverse Edges",
        "hazard_upstream_edges": "Hazard Upstream Edges",
    }
    added_reason_key = "added_tagged_condition_to_hazard_edges"
    added_reason_label = "Newly Added Tagged Condition -> Hazard Edges"
    lines = []
    total_removed = 0

    for reason_key, reason_label in reason_labels.items():
        edges = removed_edges_report.get(reason_key, [])
        total_removed += len(edges)
        lines.append(f"[{reason_label}]")
        lines.append(f"count: {len(edges)}")
        if edges:
            lines.extend(edges)
        else:
            lines.append("(none)")
        lines.append("")

    added_edges = removed_edges_report.get(added_reason_key, [])
    lines.append(f"[{added_reason_label}]")
    lines.append("note: these are NEW edges added during postprocess (not removed edges)")
    lines.append(f"count: {len(added_edges)}")
    if added_edges:
        lines.extend(added_edges)
    else:
        lines.append("(none)")
    lines.append("")

    lines.append(f"total_removed_edges: {total_removed}")
    lines.append(f"total_added_edges: {len(added_edges)}")
    return "\n".join(lines).rstrip() + "\n"
