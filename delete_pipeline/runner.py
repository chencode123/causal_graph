from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List

from openai import OpenAI
from tqdm import tqdm

import utils.incident_card_to_word as incident_card_to_word
import utils.prompt_manager as prompt_manager
from causal_graphviz.plot_conditions import draw_causal_graph as draw_causal_graph_png
from utils.causal_graph_interactive_pkg.causal_graph_interactive import (
    draw_causal_graph_interactive as draw_causal_graph_html,
)

from .io_utils import (
    extract_text_from_responses_body,
    get_response_dir,
    read_text,
    render_prompt,
    save_step_input_snapshot,
    write_text,
)
from .pipeline_steps import Step, build_pipeline


def _mask(key: str | None) -> str:
    if not key:
        return "<None>"
    return key[:8] + "..." + key[-4:]


def run_step_sync(
    client: OpenAI,
    all_prompts: Dict[str, str],
    folders: List[Path],
    step: Step,
    config: Any,
    call_sleep_seconds: float = 0.0,
) -> None:
    if step.key == "prep_final_check":
        ok = 0
        for folder in folders:
            try:
                step.build_vars(folder)
                ok += 1
            except Exception as exc:
                write_text(folder / f"{step.key}_error.txt", f"{exc}\n")
        print(f"[{step.key}] Local preprocessing done for {ok}/{len(folders)} folders.")
        return

    template = all_prompts[step.key]
    ok, fail = 0, 0

    for folder in folders:
        try:
            vars_dict = step.build_vars(folder)
            prompt_text = render_prompt(template, vars_dict)
        except Exception as exc:
            fail += 1
            write_text(folder / f"{step.key}_error.txt", f"Prompt build failed: {exc}\n")
            continue

        messages = [
            {"role": "system", "content": "You are a professional process safety analyst."},
            {"role": "user", "content": prompt_text},
        ]

        save_step_input_snapshot(
            folder=folder,
            step_key=step.key,
            template=template,
            vars_dict=vars_dict,
            prompt_text=prompt_text,
            messages=messages,
            truncate_limit=80000,
        )

        try:
            reasoning_effort = step.reasoning_effort or config.reasoning_effort
            step_temperature = step.temperature
            verbosity = step.verbosity or config.verbosity

            request_payload = {
                "model": config.model_name,
                "input": messages,
                "max_output_tokens": config.max_output_tokens,
                "text": {"verbosity": verbosity},
            }
            # `temperature` and `reasoning` cannot be sent together for your target flow.
            if step_temperature is not None:
                request_payload["temperature"] = step_temperature
            else:
                request_payload["reasoning"] = {"effort": reasoning_effort}

            # print(f"[DEBUG][{step.key}] request_payload = {request_payload}")
            resp = client.responses.create(**request_payload)

            body = resp.model_dump() if hasattr(resp, "model_dump") else dict(resp)
            out_text = extract_text_from_responses_body(body)

            write_text(step.output_path(folder), out_text)
            ok += 1

            if config.save_raw_response:
                response_dir = get_response_dir(folder)
                write_text(
                    response_dir / f"{step.key}_response_raw.json",
                    json.dumps(body, ensure_ascii=False, indent=2),
                )
        except Exception as exc:
            fail += 1
            write_text(folder / f"{step.key}_error.txt", f"API call failed: {exc}\n")

        if call_sleep_seconds > 0:
            time.sleep(call_sleep_seconds)

    print(f"[{step.key}] Sync done. ok={ok}, fail={fail}")


def run_local_postprocess(
    all_prompts: Dict[str, str],
    folder: Path,
    hazards_json_path: Path,
    conditions_json_path: Path,
) -> None:
    chain_text = read_text(folder / "prep_final_check_output.txt")

    draw_causal_graph_png(
        chain_lines=chain_text,
        conditions=str(conditions_json_path),
        hazards=str(hazards_json_path),
        save_path=folder / "causal_graph.png",
    )

    draw_causal_graph_html(
        chain_lines=chain_text,
        conditions=str(conditions_json_path),
        hazards=str(hazards_json_path),
        save_path=folder / "causal_graph.html",
    )

    incident_card_to_word.incident_card_to_word(
        identify_incident_prompt=all_prompts.get("identify_incident", ""),
        identify_hazard_consequence_prompt=all_prompts.get("identify_hazard_consequence", ""),
        identify_condition_prompt=all_prompts.get("identify_condition", ""),
        identify_evidence_prompt=all_prompts.get("identify_evidence", ""),
        chain_events_prompt=all_prompts.get("chain_events", ""),
        identify_relationship_prompt=all_prompts.get("identify_relationship", ""),
        chain_conditions_events_prompt=all_prompts.get("chain_conditions_events", ""),
        chain_scenario_prompt=all_prompts.get("chain_scenario", ""),
        chain_hazards_prompt=all_prompts.get("chain_hazards", ""),
        prep_final_check_prompt=all_prompts.get("prep_final_check", ""),
        identify_incident_output=folder / "identify_incident_output.txt",
        identify_hazard_consequence_output=folder / "identify_hazard_consequence_output.txt",
        identify_condition_output=folder / "identify_condition_output.txt",
        identify_evidence_output=folder / "identify_evidence_output.txt",
        chain_events_output=folder / "chain_events_output.txt",
        identify_relationship_output=folder / "identify_relationship_output.txt",
        chain_conditions_events_output=folder / "chain_conditions_events_output.txt",
        chain_scenario_output=folder / "chain_scenario_output.txt",
        chain_hazards_output=folder / "chain_hazards_output.txt",
        prep_final_check_output=folder / "prep_final_check_output.txt",
        prep_final_check_removed_edges_report=folder / "prep_final_check_removed_edges_report.txt",
        hazard_consequence_json=str(hazards_json_path),
        conditions_json=str(conditions_json_path),
        graph_png=folder / "causal_graph.png",
        output_docx_path=folder / "incident_card_report.docx",
    )


def run_batch_pipeline(config: Any) -> None:
    client = OpenAI()
    print("[RUNTIME] OPENAI_API_KEY =", _mask(os.getenv("OPENAI_API_KEY")))
    print("[RUNTIME] OPENAI_BASE_URL env =", os.getenv("OPENAI_BASE_URL"))
    print("[RUNTIME] client base_url =", getattr(client, "base_url", None))

    all_prompts = prompt_manager.prompts.load_all()
    folders = [
        folder
        for folder in config.base_dir.iterdir()
        if folder.is_dir() and not folder.name.startswith("_")
    ]
    print(f"Found {len(folders)} folders under {config.base_dir}")

    for folder in folders:
        get_response_dir(folder)

    pipeline = build_pipeline(
        hazards_json=config.hazards_json_path,
        conditions_json=config.conditions_json_path,
    )
    for step in tqdm(pipeline, desc="Steps (sync)", unit="step"):
        if not step.enabled:
            continue
        run_step_sync(
            client=client,
            all_prompts=all_prompts,
            folders=folders,
            step=step,
            config=config,
            call_sleep_seconds=config.call_sleep_seconds,
        )

    for folder in tqdm(folders, desc="Local postprocess", unit="folder"):
        try:
            run_local_postprocess(
                all_prompts=all_prompts,
                folder=folder,
                hazards_json_path=config.hazards_json_path,
                conditions_json_path=config.conditions_json_path,
            )
        except Exception as exc:
            print(f"Postprocess skipped for {folder.name}: {exc}")
