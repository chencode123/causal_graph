from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List
from pipeline.step_registry import STEP_REGISTRY


ACTIVE_STEP_KEYS: List[str] = [
    # "identify_hazard_consequence",
    # "causal_narrative_extraction",
    # "identify_accident_scenario",
    "causal_edge_linking",
    "review_causal_graph",
]


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
                    _read_text(case_dir / "identify_accident_scenario_output.json"),
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
                    "INCIDENT_DESCRIPTION",
                    _extract_incident_text_from_json(case_dir / "identify_incident_output.json"),
                ),
                (
                    "IDENTIFY_ACCIDENT_SCENARIO",
                    _read_text(case_dir / "identify_accident_scenario_output.json"),
                ),
                (
                    "CORRECT OUTPUT",
                    _read_text(case_dir / "causal_edge_linking_output.json"),
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
    hazards_json: Path,
    conditions_json: Path,
    project_root: Path,
) -> Any:
    required_vars = STEP_REGISTRY.get(key, {}).get("required_vars", {})
    explicit_source = required_vars.get(var_name) if isinstance(required_vars, dict) else None
    if explicit_source is not None:
        if explicit_source == "config:hazards_json":
            return hazards_json
        if explicit_source == "config:conditions_json":
            return conditions_json
        if isinstance(explicit_source, str) and explicit_source.startswith("folder:"):
            return folder / explicit_source.split(":", 1)[1]
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
        if incident_json_path.exists():
            return _extract_incident_text_from_json(incident_json_path)
        return folder / "identify_incident_output.txt"

    if var_name == "identify_incident_output":
        incident_json_path = folder / "identify_incident_output.json"
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
) -> Callable[[Path], Dict[str, Any]]:
    if key not in STEP_REGISTRY:
        raise KeyError(f"Unsupported step key in STEP_REGISTRY: {key}")

    return lambda folder: _build_vars_from_registry(
        key=key,
        folder=folder,
        hazards_json=hazards_json,
        conditions_json=conditions_json,
        project_root=project_root,
        use_few_shot=use_few_shot,
        few_shot_cases=few_shot_cases,
    )
