from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict


TARGET_PROMPT_FILES = {
    "identify_accident_scenario": Path("prompt/identify_accident_scenario.txt"),
    "causal_edge_linking": Path("prompt/causal_edge_linking.txt"),
}

NODE_KEYS = (
    "hazard_consequence_node",
    "entity_nodes",
    "condition_nodes",
    "event_nodes",
)


@dataclass
class StepOptimizationInput:
    step_key: str
    prompt_path: Path
    current_prompt: str
    step_input: Dict[str, Any]
    current_output: Dict[str, Any]
    gold_target: Dict[str, Any]
    case_dir: Path


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_materialized_vars(case_dir: Path, step_key: str) -> Dict[str, Any]:
    return _read_json(case_dir / "_debug_inputs" / f"{step_key}_vars_materialized.json")


def _build_scenario_step_input(materialized: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "incident_description": materialized.get("incident_description", ""),
        "identify_hazard_consequence_output": materialized.get(
            "identify_hazard_consequence_output", ""
        ),
    }


def _build_edge_step_input(materialized: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "incident_description": materialized.get("incident_description", ""),
        "identify_accident_scenario": materialized.get("identify_accident_scenario", ""),
    }


def _gold_nodes_only(updated_graph: Dict[str, Any]) -> Dict[str, Any]:
    return {key: updated_graph.get(key, []) for key in NODE_KEYS}


def load_step_optimization_input(case_dir: Path, step_key: str) -> StepOptimizationInput:
    prompt_path = TARGET_PROMPT_FILES[step_key]
    current_prompt = _read_text(prompt_path)
    materialized = _load_materialized_vars(case_dir, step_key)
    updated_graph = _read_json(case_dir / "updated_causal_graph.json")

    if step_key == "identify_accident_scenario":
        step_input = _build_scenario_step_input(materialized)
        current_output = _read_json(case_dir / "identify_accident_scenario_output.json")
        gold_target = _gold_nodes_only(updated_graph)
    elif step_key == "causal_edge_linking":
        step_input = _build_edge_step_input(materialized)
        current_output = _read_json(case_dir / "causal_edge_linking_output.json")
        gold_target = updated_graph
    else:
        raise KeyError(f"Unsupported optimization step: {step_key}")

    return StepOptimizationInput(
        step_key=step_key,
        prompt_path=prompt_path,
        current_prompt=current_prompt,
        step_input=step_input,
        current_output=current_output,
        gold_target=gold_target,
        case_dir=case_dir,
    )
