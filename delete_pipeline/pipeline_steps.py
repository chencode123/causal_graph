from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List

from utils.combined_text_preprocess import build_prep_final_check_vars


@dataclass
class Step:
    key: str
    output_filename: str
    build_vars: Callable[[Path], Dict[str, Any]]
    enabled: bool = True
    reasoning_effort: str | None = None
    temperature: float | None = None
    verbosity: str | None = None

    def output_path(self, folder: Path) -> Path:
        return folder / self.output_filename


def build_pipeline(hazards_json: Path, conditions_json: Path) -> List[Step]:

    return [

        # Step(
        #     key="identify_hazard_consequence",
        #     output_filename="identify_hazard_consequence_output.txt",
        #     build_vars=lambda folder: {
        #         "identify_incident_output": (folder / "identify_incident_output.txt"),
        #         "hazards_consequence_json": hazards_json,
        #     },
        # ),
        # Step(
        #     key="identify_condition",
        #     output_filename="identify_condition_output.txt",
        #     build_vars=lambda folder: {
        #         "identify_hazard_consequence_output": folder / "identify_hazard_consequence_output.txt",
        #         "identify_incident_output": folder / "identify_incident_output.txt",
        #         "conditions_json": conditions_json,
        #     },
        # ),

        # Step(
        #     key="identify_evidence",
        #     output_filename="identify_evidence_output.txt",
        #     build_vars=lambda folder: {
        #         "identify_condition_output": folder / "identify_condition_output.txt",
        #         "identify_incident_output": folder / "identify_incident_output.txt",
        #         "conditions_json": conditions_json,
        #     },
        # ),

        # Step(
        #     key="extract_event",
        #     output_filename="extract_event_output.txt",
        #     build_vars=lambda folder: {
        #         "identify_evidence_output": folder / "identify_evidence_output.txt",
        #         "conditions_json": conditions_json,
        #     },
        #     reasoning_effort="none",
        #     temperature=0
        # ),

        # Step(
        #     key="chain_events",
        #     output_filename="chain_events_output.txt",
        #     build_vars=lambda folder: {
        #         "extract_event_output": folder / "extract_event_output.txt",
        #         "conditions_json": conditions_json,
        #     },
        # ),

        # Step(
        #     key="identify_relationship",
        #     output_filename="identify_relationship_output.txt",
        #     build_vars=lambda folder: {
        #         "chain_events_output": folder / "chain_events_output.txt",
        #         "identify_incident_output": folder / "identify_incident_output.txt",
        #         "conditions_json": conditions_json,
        #     },
        # ),
        # Step(
        #     key="chain_conditions_events",
        #     output_filename="chain_conditions_events_output.txt",
        #     build_vars=lambda folder: {
        #         "identify_relationship_output": folder / "identify_relationship_output.txt",
        #         "identify_hazard_consequence_output": folder / "identify_hazard_consequence_output.txt",
        #         "chain_events_output": folder / "chain_events_output.txt",
        #         "conditions_json": conditions_json,
        #     },
        # ),

        # Step(
        #     key="chain_hazards",
        #     output_filename="chain_hazards_output.txt",
        #     build_vars=lambda folder: {
        #         "identify_hazard_consequence_output": folder / "identify_hazard_consequence_output.txt",
        #         "identify_incident_output": folder / "identify_incident_output.txt",
        #         "conditions_json": conditions_json,
        #         "chain_scenario_output": folder / "chain_scenario_output.txt",
        #     },
        # ),
        Step(
            key="prep_final_check",
            output_filename="prep_final_check_output.txt",
            build_vars=lambda folder: build_prep_final_check_vars(
                folder=folder,
                chain_hazards=folder / "chain_hazards_output.txt",
                chain_conditions_events=folder / "chain_conditions_events_output.txt",
                hazards_json=hazards_json,
                conditions_json=conditions_json,
                step_key="prep_final_check",
            ),
            # Example override: set to "low"/"medium"/"high" for this step only.
            # reasoning_effort="high",
        ),
    ]


def build_update_chain_vars(folder: Path) -> Dict[str, Any]:
    combined_text = "\n\n".join(
        (folder / filename).read_text(encoding="utf-8")
        for filename in [
            "chain_scenario_output.txt",
            "chain_hazards_output.txt",
            "chain_conditions_events_output.txt",
        ]
    )

    delete_report_path = folder / "delete_repetitive_events_output.txt"
    delete_report = (
        delete_report_path.read_text(encoding="utf-8")
        if delete_report_path.exists()
        else ""
    )

    print(f"[DEBUG] combined_text length = {len(combined_text)}")
    print(f"[DEBUG] delete_report length = {len(delete_report)}")

    return {
        "combined_text": combined_text,
        "delete_repetitive_events_output": delete_report,
    }
