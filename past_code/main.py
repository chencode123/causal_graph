from pathlib import Path
from openai import OpenAI
from tqdm import tqdm  # for progress bar
import json

import utils.prompt_manager as prompt_manager
import utils.incident_card_utils as incident_card_utils
from causal_graphviz.plot_conditions import draw_causal_graph
import model.model as model
from docx.shared import Pt
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
import utils.incident_card_to_word as incident_card_to_word

def run_incident_pipeline(folder: Path, all_prompts, model_name="gpt-5"):
    """
    Run the full incident-card generation pipeline for one folder.
    Each step uses previous output text as input.
    """
    # === Define sequential pipeline steps ===
    pipeline = [

        # 1. identify_hazard_consequence
        {
            "key": "identify_hazard_consequence",
            "vars": {
                "hazards_consequence_json": hazard_consequence_json,
                "identify_incident_output": folder / "identify_incident_output.txt",
            },
            "prev": None
        },

        # 2. identify_condition
        {
            "key": "identify_condition",
            "vars": {
                "identify_hazard_consequence_output": folder / "identify_hazard_consequence_output.txt",
                "identify_incident_output": folder / "identify_incident_output.txt",
                "conditions_json": conditions_json
            },
            "prev": None
        },

        # 3. identify_evidence
        {
            "key": "identify_evidence",
            "vars": {
                "identify_condition_output": folder/"identify_condition_output.txt",
                "identify_incident_output": folder/"identify_incident_output.txt",
                "conditions_json": conditions_json
            },
            "prev": None
        },

        # 4. chain_events
        {
            "key": "chain_events",
            "vars": {
                "identify_evidence_output": folder / "identify_evidence_output.txt",
            },
            "prev": None
        },

        # 5. relationship_of_conditions
        {
            "key": "relationship_of_conditions",
            "vars": {
                "conditions_json": "prompt/conditions.json",
                "identify_condition_output": folder / "identify_condition_output.txt",
            },
            "prev": None
        },

        # 6. chain_conditions
        {
            "key": "chain_conditions",
            "vars": {
                "relationship_of_conditions_output": folder / "relationship_of_conditions_output.txt",
                "identify_hazard_consequence_output": folder / "identify_hazard_consequence_output.txt",
            },
            "prev": None
        },

        # 7. chain_scenario
        {
            "key": "chain_scenario",
            "vars": {
                "identify_hazard_consequence_output": folder / "identify_hazard_consequence_output.txt",
                "chain_events_output": folder / "chain_events_output.txt",
                "conditions_json": "prompt/conditions.json",
            },
            "prev": None
        },

        # 8. chain_hazards
        {
            "key": "chain_hazards",
            "vars": {
                "identify_hazard_consequence_output": folder / "identify_hazard_consequence_output.txt",
                "identify_incident_output": folder / "identify_incident_output.txt",
                "conditions_json": "prompt/conditions.json",
                "chain_scenario_output": folder / "chain_scenario_output.txt",
            },
            "prev": None
        }
    ]

    # === Run each prompt sequentially ===
    with tqdm(total=len(pipeline),
              desc=f"Pipeline ({folder.name})",
              unit="step",
              position=1,     # appear below outer bar
              leave=False) as pbar_inner:

        for step in pipeline:
            key = step["key"]

            model.run_prompt(
                prompt=all_prompts[key],
                variables=step["vars"],
                output_dir=folder,
                model_name=model_name,
                prompt_key=key,
                prev_prompt=None,
                prev_output=None
            )

            pbar_inner.update(1)

    # === Combine and visualize ===
    try:
        chain_scenario_text = (folder / "chain_scenario_output.txt").read_text(encoding="utf-8")
        chain_hazards_text = (folder / "chain_hazards_output.txt").read_text(encoding="utf-8")
        chain_conditions_text = (folder / "chain_conditions_output.txt").read_text(encoding="utf-8")
        combined_text = chain_scenario_text + "\n" + chain_hazards_text + "\n" + chain_conditions_text

        graph_png = draw_causal_graph(
            chain_lines=combined_text,
            conditions="prompt/conditions.json",
            hazards = "prompt/hazards_consequence.json",
            save_path=folder / "causal_graph.png"
        )

        # === Generate incident card summary ===
        incident_card_utils.incident_card_utils(
            identify_incident_prompt = all_prompts["identify_incident"],
            identify_hazard_consequence_prompt = all_prompts["identify_hazard_consequence"],
            identify_condition_prompt = all_prompts["identify_condition"],
            identify_evidence_prompt = all_prompts["identify_evidence"],
            relationship_of_conditions_prompt = all_prompts["relationship_of_conditions"],
            chain_events_prompt = all_prompts["chain_events"],
            chain_conditions_prompt = all_prompts["chain_conditions"],
            chain_scenario_prompt = all_prompts["chain_scenario"],
            chain_hazards_prompt = all_prompts["chain_hazards"],

            identify_incident_output = folder / "identify_incident_output.txt",
            identify_hazard_consequence_output = folder / "identify_hazard_consequence_output.txt",
            identify_condition_output = folder / "identify_condition_output.txt",
            identify_evidence_output = folder / "identify_evidence_output.txt",
            relationship_of_conditions_output = folder / "relationship_of_conditions_output.txt",
            chain_events_output = folder / "chain_events_output.txt",
            chain_conditions_output = folder / "chain_conditions_output.txt",
            chain_scenario_output = folder / "chain_scenario_output.txt",
            chain_hazards_output = folder / "chain_hazards_output.txt",

            hazard_consequence_json = hazard_consequence_json,
            conditions_json = conditions_json,

            graph_png = folder / "causal_graph.png",

            md_path=folder,
            file_name=f"results.md"
        )
        incident_card_to_word.incident_card_to_word(
            identify_incident_prompt = all_prompts["identify_incident"],
            identify_hazard_consequence_prompt = all_prompts["identify_hazard_consequence"],
            identify_condition_prompt = all_prompts["identify_condition"],
            identify_evidence_prompt = all_prompts["identify_evidence"],
            relationship_of_conditions_prompt = all_prompts["relationship_of_conditions"],
            chain_events_prompt = all_prompts["chain_events"],
            chain_conditions_prompt = all_prompts["chain_conditions"],
            chain_scenario_prompt = all_prompts["chain_scenario"],
            chain_hazards_prompt = all_prompts["chain_hazards"],

            identify_incident_output = folder / "identify_incident_output.txt",
            identify_hazard_consequence_output = folder / "identify_hazard_consequence_output.txt",
            identify_condition_output = folder / "identify_condition_output.txt",
            identify_evidence_output = folder / "identify_evidence_output.txt",
            relationship_of_conditions_output = folder / "relationship_of_conditions_output.txt",
            chain_events_output = folder / "chain_events_output.txt",
            chain_conditions_output = folder / "chain_conditions_output.txt",
            chain_scenario_output = folder / "chain_scenario_output.txt",
            chain_hazards_output = folder / "chain_hazards_output.txt",

            hazard_consequence_json = hazard_consequence_json,
            conditions_json = conditions_json,

            graph_png = folder / "causal_graph.png",
            output_docx_path = folder / "incident_card_report.docx"
        )
    except Exception as e:
        print(f"⚠️ Skipped visualization for {folder.name}: {e}")


if __name__ == "__main__":
    client = OpenAI()
    all_prompts = prompt_manager.prompts.load_all()
    hazard_consequence_json = "prompt\hazards_consequence.json"
    conditions_json = "prompt\conditions.json"

    base_dir = Path(r"runs\test_batch\batch_2")
    subfolders = [f for f in base_dir.iterdir() if f.is_dir()]

    with tqdm(total=len(subfolders),
              desc="Processing incident cards",
              unit="folder",
              position=0) as pbar_outer:

        for folder in subfolders:
            run_incident_pipeline(folder, all_prompts, model_name="gpt-5")
            pbar_outer.update(1)

    print("\n✅ All folders processed successfully!")
