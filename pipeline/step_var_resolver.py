from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List
from pipeline.step_registry import STEP_REGISTRY


def get_active_step_keys(
    base_step_keys: Iterable[str],
) -> List[str]:
    keys = list(base_step_keys)
    if "review_causal_graph" not in keys:
        return keys
    review_index = keys.index("review_causal_graph")
    return (
        keys[:review_index]
        + ["graph_diagnosis", "graph_revision_planning"]
        + keys[review_index + 1 :]
    )


def _extract_incident_text_from_json(path: Path) -> str:
    """Extract prompt-ready incident text from identify_incident JSON output."""
    with path.open("r", encoding="utf-8") as fp:
        data = json.load(fp)

    incidents = data.get("incidents", [])
    if not isinstance(incidents, list) or not incidents:
        return path.read_text(encoding="utf-8")

    incident = incidents[0] if isinstance(incidents[0], dict) else {}
    blocks: List[str] = []

    summary = incident.get("incident_summary_section", {})
    if isinstance(summary, dict):
        summary_text = str(summary.get("text") or "").strip()
        if summary_text:
            blocks.append("SUMMARY:")
            blocks.append(summary_text)

    description = incident.get("incident_description_section", {})
    if isinstance(description, dict):
        description_text = str(description.get("text") or "").strip()
        if description_text:
            blocks.append("INCIDENT DESCRIPTION:")
            blocks.append(description_text)

    related_sections = incident.get("other_related_sections", [])
    if isinstance(related_sections, list):
        related_texts: List[str] = []
        for section in related_sections:
            if not isinstance(section, dict):
                continue
            title = str(section.get("section_title") or "").strip()
            text = str(section.get("text") or "").strip()
            if not text:
                continue
            if title:
                related_texts.append(f"{title}\n{text}")
            else:
                related_texts.append(text)
        if related_texts:
            blocks.append("OTHER RELATED SECTIONS:")
            blocks.extend(related_texts)

    return "\n\n".join(blocks).strip() or path.read_text(encoding="utf-8")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _extract_candidate_evidence_snippets(path: Path, limit: int = 8) -> str:
    with path.open("r", encoding="utf-8") as fp:
        data = json.load(fp)

    snippets: List[str] = []
    keys = (
        "hazard_consequence_node",
        "candidate_entity_nodes",
        "candidate_condition_nodes",
        "candidate_event_nodes",
    )
    for key in keys:
        nodes = data.get(key, [])
        if isinstance(nodes, dict):
            nodes = [nodes]
        if not isinstance(nodes, list):
            continue
        for node in nodes:
            if not isinstance(node, dict):
                continue
            label = str(node.get("label") or "").strip()
            name = str(node.get("name") or "").strip()
            evidence = str(node.get("evidence") or "").strip()
            if not evidence:
                continue
            snippets.append(f"{label}:{name} -> {evidence}")
            if len(snippets) >= limit:
                return "\n".join(snippets)
    return "\n".join(snippets)


def _extract_edge_candidate_evidence_snippets(path: Path, limit: int = 10) -> str:
    with path.open("r", encoding="utf-8") as fp:
        data = json.load(fp)

    snippets: List[str] = []
    edges = data.get("candidate_edges", [])
    if not isinstance(edges, list):
        return ""
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        source = str(edge.get("source") or "").strip()
        target = str(edge.get("target") or "").strip()
        relation = str(edge.get("relation") or "").strip()
        evidence = str(edge.get("evidence") or "").strip()
        if not evidence:
            continue
        snippets.append(f"{source} -[{relation}]-> {target} :: {evidence}")
        if len(snippets) >= limit:
            break
    return "\n".join(snippets)


def _format_few_shot_example(title: str, sections: Iterable[tuple[str, str]]) -> str:
    lines: List[str] = [title, ""]
    for label, content in sections:
        lines.append(label)
        lines.append(content.strip())
        lines.append("")
    return "\n".join(lines).strip()


def _build_few_shot_examples(step_key: str, case_dirs: Iterable[Path]) -> str:
    cases = list(case_dirs)
    if not cases:
        return ""

    lines: List[str] = ["FEW-SHOT EXAMPLES", ""]
    for index, case_dir in enumerate(cases, start=1):
        if step_key == "identify_hazard_consequence":
            sections = [
                (
                    "IDENTIFY_INCIDENT_OUTPUT",
                    _extract_incident_text_from_json(case_dir / "identify_incident_output.json"),
                ),
                (
                    "CORRECT OUTPUT",
                    _read_text(case_dir / "identify_hazard_consequence_output.json"),
                ),
            ]
        elif step_key == "identify_accident_scenario":
            sections = [
                (
                    "SCENARIO_CANDIDATE_EXTRACTION_OUTPUT",
                    _read_text(case_dir / "scenario_candidate_extraction_output.json"),
                ),
                (
                    "SCENARIO_STRUCTURE_VALIDATION_OUTPUT",
                    _read_text(case_dir / "scenario_structure_validation_output.json"),
                ),
                (
                    "CORRECT OUTPUT",
                    _read_text(case_dir / "identify_accident_scenario_output.json"),
                ),
            ]
        elif step_key == "scenario_candidate_extraction":
            sections = [
                (
                    "INCIDENT_DESCRIPTION",
                    _extract_incident_text_from_json(case_dir / "identify_incident_output.json"),
                ),
                (
                    "IDENTIFIED_HAZARD_CONSEQUENCE",
                    _read_text(case_dir / "identify_hazard_consequence_output.json"),
                ),
                (
                    "CAUSAL_NARRATIVE_EXTRACTION",
                    _read_text(case_dir / "causal_narrative_extraction_output.json"),
                ),
                (
                    "CORRECT OUTPUT",
                    _read_text(case_dir / "scenario_candidate_extraction_output.json"),
                ),
            ]
        elif step_key == "scenario_structure_validation":
            sections = [
                (
                    "IDENTIFIED_HAZARD_CONSEQUENCE",
                    _read_text(case_dir / "identify_hazard_consequence_output.json"),
                ),
                (
                    "CAUSAL_NARRATIVE_EXTRACTION",
                    _read_text(case_dir / "causal_narrative_extraction_output.json"),
                ),
                (
                    "SCENARIO_CANDIDATE_EXTRACTION_OUTPUT",
                    _read_text(case_dir / "scenario_candidate_extraction_output.json"),
                ),
                (
                    "CANDIDATE_EVIDENCE_SNIPPETS",
                    _extract_candidate_evidence_snippets(
                        case_dir / "scenario_candidate_extraction_output.json"
                    ),
                ),
                (
                    "CORRECT OUTPUT",
                    _read_text(case_dir / "scenario_structure_validation_output.json"),
                ),
            ]
        elif step_key == "causal_narrative_extraction":
            sections = [
                (
                    "INCIDENT_DESCRIPTION",
                    _extract_incident_text_from_json(case_dir / "identify_incident_output.json"),
                ),
                (
                    "IDENTIFIED_HAZARD_CONSEQUENCE",
                    _read_text(case_dir / "identify_hazard_consequence_output.json"),
                ),
                (
                    "CORRECT OUTPUT",
                    _read_text(case_dir / "causal_narrative_extraction_output.json"),
                ),
            ]
        elif step_key == "causal_edge_linking":
            sections = [
                (
                    "CAUSAL_NARRATIVE_EXTRACTION",
                    _read_text(case_dir / "causal_narrative_extraction_output.json"),
                ),
                (
                    "IDENTIFY_ACCIDENT_SCENARIO_OUTPUT",
                    _read_text(case_dir / "identify_accident_scenario_output.json"),
                ),
                (
                    "EDGE_CANDIDATE_EXTRACTION_OUTPUT",
                    _read_text(case_dir / "edge_candidate_extraction_output.json"),
                ),
                (
                    "EDGE_STRUCTURE_VALIDATION_OUTPUT",
                    _read_text(case_dir / "edge_structure_validation_output.json"),
                ),
                (
                    "CORRECT OUTPUT",
                    _read_text(case_dir / "causal_edge_linking_output.json"),
                ),
            ]
        elif step_key == "edge_candidate_extraction":
            sections = [
                (
                    "INCIDENT_DESCRIPTION",
                    _extract_incident_text_from_json(case_dir / "identify_incident_output.json"),
                ),
                (
                    "CAUSAL_NARRATIVE_EXTRACTION",
                    _read_text(case_dir / "causal_narrative_extraction_output.json"),
                ),
                (
                    "IDENTIFY_ACCIDENT_SCENARIO_OUTPUT",
                    _read_text(case_dir / "identify_accident_scenario_output.json"),
                ),
                (
                    "CORRECT OUTPUT",
                    _read_text(case_dir / "edge_candidate_extraction_output.json"),
                ),
            ]
        elif step_key == "edge_structure_validation":
            sections = [
                (
                    "CAUSAL_NARRATIVE_EXTRACTION",
                    _read_text(case_dir / "causal_narrative_extraction_output.json"),
                ),
                (
                    "IDENTIFY_ACCIDENT_SCENARIO_OUTPUT",
                    _read_text(case_dir / "identify_accident_scenario_output.json"),
                ),
                (
                    "EDGE_CANDIDATE_EXTRACTION_OUTPUT",
                    _read_text(case_dir / "edge_candidate_extraction_output.json"),
                ),
                (
                    "EDGE_CANDIDATE_EVIDENCE_SNIPPETS",
                    _extract_edge_candidate_evidence_snippets(
                        case_dir / "edge_candidate_extraction_output.json"
                    ),
                ),
                (
                    "CORRECT OUTPUT",
                    _read_text(case_dir / "edge_structure_validation_output.json"),
                ),
            ]
        elif step_key == "joint_accident_graph_extraction":
            sections = [
                (
                    "INCIDENT_DESCRIPTION",
                    _extract_incident_text_from_json(case_dir / "identify_incident_output.json"),
                ),
                (
                    "IDENTIFIED_HAZARD_CONSEQUENCE",
                    _read_text(case_dir / "identify_hazard_consequence_output.json"),
                ),
                (
                    "CAUSAL_NARRATIVE_EXTRACTION",
                    _read_text(case_dir / "causal_narrative_extraction_output.json"),
                ),
                (
                    "CORRECT OUTPUT",
                    _read_text(case_dir / "joint_accident_graph_extraction_output.json"),
                ),
            ]
        else:
            return ""

        lines.append(_format_few_shot_example(f"Example {index}", sections))
        lines.append("")

    lines.extend(
        [
            "End of examples.",
            "Use the examples only as references for reasoning style and output structure.",
            "Do not copy incident-specific content from the examples.",
            "",
        ]
    )
    return "\n".join(lines)


def _resolve_required_var(
    var_name: str,
    *,
    key: str,
    folder: Path,
    source_folder: Path,
    hazards_json: Path,
    conditions_json: Path,
    project_root: Path,
) -> Any:
    required_vars = STEP_REGISTRY.get(key, {}).get("required_vars", {})
    explicit_source = required_vars.get(var_name) if isinstance(required_vars, dict) else None
    if var_name == "candidate_evidence_snippets":
        candidate_path = folder / "scenario_candidate_extraction_output.json"
        if not candidate_path.exists():
            candidate_path = source_folder / "scenario_candidate_extraction_output.json"
        if candidate_path.exists():
            return _extract_candidate_evidence_snippets(candidate_path)
        return ""
    if var_name == "edge_candidate_evidence_snippets":
        candidate_path = folder / "edge_candidate_extraction_output.json"
        if not candidate_path.exists():
            candidate_path = source_folder / "edge_candidate_extraction_output.json"
        if candidate_path.exists():
            return _extract_edge_candidate_evidence_snippets(candidate_path)
        return ""
    if explicit_source is not None:
        if explicit_source == "config:hazards_json":
            return hazards_json
        if explicit_source == "config:conditions_json":
            return conditions_json
        if isinstance(explicit_source, str) and explicit_source.startswith("folder:"):
            relative_path = explicit_source.split(":", 1)[1]
            output_path = folder / relative_path
            if output_path.exists():
                return output_path
            return source_folder / relative_path
        if isinstance(explicit_source, str) and explicit_source.startswith("project:"):
            return project_root / explicit_source.split(":", 1)[1]
        raise KeyError(
            f"Invalid explicit source '{explicit_source}' for var '{var_name}' in step '{key}'. "
            "Use 'folder:<path>', 'project:<path>', 'config:hazards_json', or 'config:conditions_json'."
        )

    # Common path-based conventions used in this repository.
    if var_name == "hazards_consequence_json":
        return hazards_json
    if var_name == "conditions_json":
        return conditions_json

    if var_name == "incident_description":
        incident_json_path = folder / "identify_incident_output.json"
        if not incident_json_path.exists():
            incident_json_path = source_folder / "identify_incident_output.json"
        if incident_json_path.exists():
            return _extract_incident_text_from_json(incident_json_path)
        return folder / "identify_incident_output.txt"

    if var_name == "identify_incident_output":
        incident_json_path = folder / "identify_incident_output.json"
        if not incident_json_path.exists():
            incident_json_path = source_folder / "identify_incident_output.json"
        if incident_json_path.exists():
            return _extract_incident_text_from_json(incident_json_path)
        return folder / "identify_incident_output.txt"

    if var_name.endswith("_output"):
        return folder / f"{var_name}.txt"

    if var_name.endswith("_schema"):
        return project_root / "scheme" / f"{var_name}.json"

    if var_name.endswith("_scheme"):
        return project_root / "scheme" / f"{var_name}.json"

    if var_name.endswith("_schema_definition"):
        return project_root / "scheme" / f"{var_name}.txt"

    raise KeyError(
        f"Cannot auto-resolve required var '{var_name}'. "
        "Add a resolver rule in pipeline/step_var_resolver.py::_resolve_required_var."
    )


def _build_vars_from_registry(
    key: str,
    *,
    folder: Path,
    source_folder: Path,
    hazards_json: Path,
    conditions_json: Path,
    project_root: Path,
    use_few_shot: bool,
    few_shot_cases: Iterable[Path],
) -> Dict[str, Any]:
    required_vars = STEP_REGISTRY[key].get("required_vars", {})
    if not isinstance(required_vars, dict):
        raise TypeError(
            f"STEP_REGISTRY['{key}']['required_vars'] must be a dict of var->source."
        )
    resolved = {
        var_name: _resolve_required_var(
            var_name,
            key=key,
            folder=folder,
            source_folder=source_folder,
            hazards_json=hazards_json,
            conditions_json=conditions_json,
            project_root=project_root,
        )
        for var_name in required_vars
    }
    resolved["few_shot_examples"] = (
        _build_few_shot_examples(key, few_shot_cases) if use_few_shot else ""
    )
    return resolved


def get_step_var_builder(
    key: str,
    *,
    hazards_json: Path,
    conditions_json: Path,
    project_root: Path,
    use_few_shot: bool = False,
    few_shot_cases: Iterable[Path] = (),
    source_folder_map: dict[Path, Path] | None = None,
) -> Callable[[Path], Dict[str, Any]]:
    if key not in STEP_REGISTRY:
        raise KeyError(f"Unsupported step key in STEP_REGISTRY: {key}")

    return lambda folder: _build_vars_from_registry(
        key=key,
        folder=folder,
        source_folder=(source_folder_map or {}).get(folder, folder),
        hazards_json=hazards_json,
        conditions_json=conditions_json,
        project_root=project_root,
        use_few_shot=use_few_shot,
        few_shot_cases=few_shot_cases,
    )
