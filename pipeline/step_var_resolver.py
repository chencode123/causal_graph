from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List

from pipeline.step_registry import STEP_REGISTRY


ACTIVE_STEP_KEYS: List[str] = [
    # "identify_hazard_consequence",
    "identify_accident_scenario",
]


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
) -> Dict[str, Any]:
    required_vars = STEP_REGISTRY[key].get("required_vars", {})
    if not isinstance(required_vars, dict):
        raise TypeError(
            f"STEP_REGISTRY['{key}']['required_vars'] must be a dict of var->source."
        )
    return {
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


def get_step_var_builder(
    key: str,
    *,
    hazards_json: Path,
    conditions_json: Path,
    project_root: Path,
) -> Callable[[Path], Dict[str, Any]]:
    if key not in STEP_REGISTRY:
        raise KeyError(f"Unsupported step key in STEP_REGISTRY: {key}")

    return lambda folder: _build_vars_from_registry(
        key=key,
        folder=folder,
        hazards_json=hazards_json,
        conditions_json=conditions_json,
        project_root=project_root,
    )
