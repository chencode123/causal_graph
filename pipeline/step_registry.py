from __future__ import annotations

from typing import Any, Dict


STEP_REGISTRY: Dict[str, Dict[str, Any]] = {
    "identify_hazard_consequence": {
        "output_file": "identify_hazard_consequence_output.json",
        "required_vars": {
            "identify_incident_output": "folder:identify_incident_output.json",
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
    "causal_narrative_extraction": {
        "output_file": "causal_narrative_extraction_output.json",
        "required_vars": {
            "incident_description": "folder:identify_incident_output.json",
            "identify_hazard_consequence_output": (
                "folder:identify_hazard_consequence_output.json"
            ),
        },
        "default_params": {
            "enabled": True,
            "reasoning_effort": None,
            "temperature": None,
            "verbosity": None,
        },
    },
    "scenario_candidate_extraction": {
        "output_file": "scenario_candidate_extraction_output.json",
        "required_vars": {
            "incident_description": "folder:identify_incident_output.json",
            "identify_hazard_consequence_output": (
                "folder:identify_hazard_consequence_output.json"
            ),
            "causal_narrative_extraction_output": (
                "folder:causal_narrative_extraction_output.json"
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
    "scenario_structure_validation": {
        "output_file": "scenario_structure_validation_output.json",
        "required_vars": {
            "identify_hazard_consequence_output": (
                "folder:identify_hazard_consequence_output.json"
            ),
            "causal_narrative_extraction_output": (
                "folder:causal_narrative_extraction_output.json"
            ),
            "accident_scenario_schema": "project:scheme/accident_scenario_schema.json",
            "accident_scenario_schema_definition": (
                "project:scheme/accident_scenario_scheme_definition.txt"
            ),
            "scenario_candidate_extraction_output": (
                "folder:scenario_candidate_extraction_output.json"
            ),
            "candidate_evidence_snippets": (
                "folder:scenario_candidate_extraction_output.json"
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
            "identify_hazard_consequence_output": (
                "folder:identify_hazard_consequence_output.json"
            ),
            "causal_narrative_extraction_output": (
                "folder:causal_narrative_extraction_output.json"
            ),
            "accident_scenario_schema": "project:scheme/accident_scenario_schema.json",
            "accident_scenario_schema_definition": (
                "project:scheme/accident_scenario_scheme_definition.txt"
            ),
            "scenario_candidate_extraction_output": (
                "folder:scenario_candidate_extraction_output.json"
            ),
            "scenario_structure_validation_output": (
                "folder:scenario_structure_validation_output.json"
            ),
        },
        "default_params": {
            "enabled": True,
            "reasoning_effort": None,
            "temperature": None,
            "verbosity": None,
        },
    },
    "edge_candidate_extraction": {
        "output_file": "edge_candidate_extraction_output.json",
        "required_vars": {
            "incident_description": "folder:identify_incident_output.json",
            "causal_narrative_extraction_output": (
                "folder:causal_narrative_extraction_output.json"
            ),
            "identify_accident_scenario_output": (
                "folder:identify_accident_scenario_output.json"
            ),
        },
        "default_params": {
            "enabled": True,
            "reasoning_effort": None,
            "temperature": None,
            "verbosity": None,
        },
    },
    "edge_structure_validation": {
        "output_file": "edge_structure_validation_output.json",
        "required_vars": {
            "causal_narrative_extraction_output": (
                "folder:causal_narrative_extraction_output.json"
            ),
            "identify_accident_scenario_output": (
                "folder:identify_accident_scenario_output.json"
            ),
            "edge_candidate_extraction_output": (
                "folder:edge_candidate_extraction_output.json"
            ),
            "edge_candidate_evidence_snippets": (
                "folder:edge_candidate_extraction_output.json"
            ),
        },
        "default_params": {
            "enabled": True,
            "reasoning_effort": None,
            "temperature": None,
            "verbosity": None,
        },
    },
    "causal_edge_linking": {
        "output_file": "causal_edge_linking_output.json",
        "required_vars": {
            "causal_narrative_extraction_output": (
                "folder:causal_narrative_extraction_output.json"
            ),
            "identify_accident_scenario_output": (
                "folder:identify_accident_scenario_output.json"
            ),
            "edge_candidate_extraction_output": (
                "folder:edge_candidate_extraction_output.json"
            ),
            "edge_structure_validation_output": (
                "folder:edge_structure_validation_output.json"
            ),
        },
        "default_params": {
            "enabled": True,
            "reasoning_effort": None,
            "temperature": None,
            "verbosity": None,
        },
    },
    "review_causal_graph": {
        "output_file": "review_causal_graph_output.json",
        "required_vars": {
            "incident_description": "folder:identify_incident_output.json",
            "accident_scenario_schema": "project:scheme/accident_scenario_schema.json",
            "accident_scenario_schema_definition": (
                "project:scheme/accident_scenario_scheme_definition.txt"
            ),
            "causal_narrative_extraction_output": (
                "folder:causal_narrative_extraction_output.json"
            ),
            "identify_accident_scenario_output": (
                "folder:identify_accident_scenario_output.json"
            ),
            "causal_edge_linking_output": "folder:causal_edge_linking_output.json",
            "causal_graph_json": "folder:causal_graph.json",
        },
        "default_params": {
            "enabled": True,
            "reasoning_effort": None,
            "temperature": None,
            "verbosity": None,
        },
    },
    "graph_diagnosis": {
        "output_file": "graph_diagnosis_output.json",
        "required_vars": {
            "incident_description": "folder:identify_incident_output.json",
            "accident_scenario_schema": "project:scheme/accident_scenario_schema.json",
            "accident_scenario_schema_definition": (
                "project:scheme/accident_scenario_scheme_definition.txt"
            ),
            "causal_narrative_extraction_output": (
                "folder:causal_narrative_extraction_output.json"
            ),
            "causal_graph_json": "folder:causal_graph.json",
        },
        "default_params": {
            "enabled": True,
            "reasoning_effort": None,
            "temperature": None,
            "verbosity": None,
        },
    },
    "graph_revision_planning": {
        "output_file": "graph_revision_planning_output.json",
        "required_vars": {
            "incident_description": "folder:identify_incident_output.json",
            "accident_scenario_schema": "project:scheme/accident_scenario_schema.json",
            "accident_scenario_schema_definition": (
                "project:scheme/accident_scenario_scheme_definition.txt"
            ),
            "causal_narrative_extraction_output": (
                "folder:causal_narrative_extraction_output.json"
            ),
            "causal_graph_json": "folder:causal_graph.json",
            "graph_diagnosis_output": "folder:graph_diagnosis_output.json",
        },
        "default_params": {
            "enabled": True,
            "reasoning_effort": None,
            "temperature": None,
            "verbosity": None,
        },
    },
    "review_feedback_analysis": {
        "output_file": "review_feedback_analysis_output.json",
        "required_vars": {
            "causal_graph_json": "folder:causal_graph.json",
            "updated_causal_graph_json": "folder:updated_causal_graph.json",
            "updated_causal_graph_review_state_json": (
                "folder:updated_causal_graph_review_state.json"
            ),
            "graph_diagnosis_output": "folder:graph_diagnosis_output.json",
            "graph_revision_planning_output": (
                "folder:graph_revision_planning_output.json"
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
