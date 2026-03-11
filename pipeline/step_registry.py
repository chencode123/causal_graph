from __future__ import annotations

from typing import Any, Dict


STEP_REGISTRY: Dict[str, Dict[str, Any]] = {
    "identify_hazard_consequence": {
        "output_file": "identify_hazard_consequence_output.json",
        "required_vars": {
            "identify_incident_output": "folder:identify_incident_output.txt",
            "hazards_consequence_json": "config:hazards_json",
            "identify_hazard_consequence_scheme": (
                "project:scheme/identify_hazard_consequence_scheme.json"
            ),
        },
        "default_params": {
            "enabled": True,
            "reasoning_effort": None,
            "temperature": None,
            "verbosity": None,
        },
    },
    "identify_accident_scenario": {
        "output_file": "identify_accident_scenario_output.json",
        "required_vars": {
            "incident_description": "folder:identify_incident_output.txt",
            "identify_hazard_consequence_output": (
                "folder:identify_hazard_consequence_output.txt"
            ),
            "accident_scenario_schema": "project:scheme/accident_scenario_schema.json",
            "accident_scenario_schema_definition": (
                "project:scheme/accident_scenario_scheme_definition.txt"
            ),
        },
        "default_params": {
            "enabled": True,
            "reasoning_effort": None,
            "temperature": None,
            "verbosity": None,
        },
    },
}
