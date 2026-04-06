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
from utils.causal_graph_interactive_pkg.causal_graph_interactive import (
    draw_causal_graph_interactive_from_json,
    draw_updated_causal_graph_interactive_from_json,
)
from utils.prompt_validator import assert_prompt_step_configuration_valid

from .io_utils import (
    extract_text_from_responses_body,
    get_response_dir,
    render_prompt,
    save_step_input_snapshot,
    write_text,
)
from .step_factory import Step, build_pipeline
from .step_registry import STEP_REGISTRY


def _mask(key: str | None) -> str:
    if not key:
        return "<None>"
    return key[:8] + "..." + key[-4:]


def _build_causal_graph_json(
    *,
    identify_accident_scenario_path: Path,
    causal_edge_linking_path: Path,
    output_path: Path,
) -> None:
    with identify_accident_scenario_path.open("r", encoding="utf-8") as fp:
        scenario_data = json.load(fp)
    with causal_edge_linking_path.open("r", encoding="utf-8") as fp:
        edge_data = json.load(fp)

    edges = edge_data.get("edges", [])
    linked_node_ids = {
        node_id
        for edge in edges
        for node_id in (edge.get("source"), edge.get("target"))
        if node_id
    }

    graph_data = {
        "hazard_consequence_node": [],
        "entity_nodes": [],
        "condition_nodes": [],
        "event_nodes": [],
        "edges": [],
    }

    for key in (
        "hazard_consequence_node",
        "entity_nodes",
        "condition_nodes",
        "event_nodes",
    ):
        graph_data[key] = [
            node
            for node in scenario_data.get(key, [])
            if node.get("node_id") in linked_node_ids
        ]

    valid_node_ids = {
        node.get("node_id")
        for key in (
            "hazard_consequence_node",
            "entity_nodes",
            "condition_nodes",
            "event_nodes",
        )
        for node in graph_data[key]
        if node.get("node_id")
    }
    graph_data["edges"] = [
        edge
        for edge in edges
        if edge.get("source") in valid_node_ids and edge.get("target") in valid_node_ids
    ]

    write_text(output_path, json.dumps(graph_data, ensure_ascii=False, indent=2))


def _format_causal_narrative_markdown(payload: Dict[str, Any], case_id: str) -> str:
    """Render causal_narrative_extraction JSON into a readable Markdown file."""
    steps = payload.get("causal_steps", [])
    lines: List[str] = [
        "# Causal Narrative Extraction",
        "",
        f"- Case: `{case_id}`",
        f"- Step count: `{len(steps) if isinstance(steps, list) else 0}`",
        "",
    ]

    if not isinstance(steps, list) or not steps:
        lines.extend(
            [
                "## Narrative",
                "",
                "_No causal steps found in `causal_narrative_extraction_output.json`._",
                "",
            ]
        )
        return "\n".join(lines)

    lines.extend(["## Narrative", ""])
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            lines.append(f"{index}. {str(step).strip()}")
            continue
        step_number = step.get("step_number", index)
        description = str(step.get("description") or "").strip()
        lines.append(
            f"{step_number}. {description}" if description else f"{step_number}. _No description provided._"
        )
    lines.append("")
    return "\n".join(lines)


def write_causal_narrative_markdown(folder: Path) -> None:
    """Create a Markdown companion file for causal_narrative_extraction output."""
    json_path = folder / "causal_narrative_extraction_output.json"
    if not json_path.exists():
        return
    with json_path.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)
    write_text(
        folder / "causal_narrative_extraction_output.md",
        _format_causal_narrative_markdown(payload, folder.name),
    )


def ensure_causal_graph_json(folder: Path) -> None:
    """Build causal_graph.json if the required upstream step outputs are present."""
    identify_accident_scenario_path = folder / "identify_accident_scenario_output.json"
    causal_edge_linking_path = folder / "causal_edge_linking_output.json"
    if not identify_accident_scenario_path.exists():
        raise FileNotFoundError(
            f"Missing identify_accident_scenario_output.json for {folder.name}"
        )
    if not causal_edge_linking_path.exists():
        raise FileNotFoundError(
            f"Missing causal_edge_linking_output.json for {folder.name}"
        )
    _build_causal_graph_json(
        identify_accident_scenario_path=identify_accident_scenario_path,
        causal_edge_linking_path=causal_edge_linking_path,
        output_path=folder / "causal_graph.json",
    )


def run_step_sync(
    client: OpenAI,
    all_prompts: Dict[str, str],
    folders: List[Path],
    step: Step,
    config: Any,
    call_sleep_seconds: float = 0.0,
) -> None:
    if step.key == "review_causal_graph":
        prep_ok = 0
        prep_fail = 0
        for folder in folders:
            try:
                ensure_causal_graph_json(folder)
                prep_ok += 1
            except Exception as exc:
                prep_fail += 1
                write_text(folder / f"{step.key}_error.txt", f"Graph prep failed: {exc}\n")
        print(
            f"[{step.key}] Graph prep done. ok={prep_ok}, fail={prep_fail}"
        )

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
            force_json_output = getattr(config, "force_json_output", False)

            text_cfg: Dict[str, Any] = {"verbosity": verbosity}
            if force_json_output:
                text_cfg["format"] = {"type": "json_object"}

            request_payload = {
                "model": config.model_name,
                "input": messages,
                "max_output_tokens": config.max_output_tokens,
                "text": text_cfg,
            }
            if step_temperature is not None:
                request_payload["temperature"] = step_temperature
            else:
                request_payload["reasoning"] = {"effort": reasoning_effort}

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
    accident_scenario_schema_path: Path,
) -> None:
    identify_accident_scenario_path = folder / "identify_accident_scenario_output.json"
    causal_edge_linking_path = folder / "causal_edge_linking_output.json"
    write_causal_narrative_markdown(folder)
    ensure_causal_graph_json(folder)

    draw_causal_graph_interactive_from_json(
        identify_accident_scenario=identify_accident_scenario_path,
        causal_edge_linking=causal_edge_linking_path,
        save_path=folder / "causal_graph.html",
        accident_scenario_schema=accident_scenario_schema_path,
        review_causal_graph=(
            folder / "review_causal_graph_output.json"
            if (folder / "review_causal_graph_output.json").exists()
            else None
        ),
        revision_decisions=None,
        case_id=folder.name,
    )

    updated_graph_path = folder / "updated_causal_graph.json"
    if updated_graph_path.exists():
        draw_updated_causal_graph_interactive_from_json(
            updated_causal_graph=updated_graph_path,
            save_path=folder / "updated_causal_graph.html",
            accident_scenario_schema=accident_scenario_schema_path,
            review_causal_graph=(
                folder / "review_causal_graph_output.json"
                if (folder / "review_causal_graph_output.json").exists()
                else None
            ),
            revision_decisions=(
                folder / "updated_causal_graph_review_state.json"
                if (folder / "updated_causal_graph_review_state.json").exists()
                else None
            ),
            case_id=folder.name,
        )

    incident_card_to_word.incident_card_to_word(
        identify_incident_prompt=all_prompts.get("identify_incident", ""),
        identify_hazard_consequence_prompt=all_prompts.get("identify_hazard_consequence", ""),
        identify_accident_scenario_prompt=all_prompts.get("identify_accident_scenario", ""),
        causal_edge_linking_prompt=all_prompts.get("causal_edge_linking", ""),
        identify_incident_output=folder / "identify_incident_output.json",
        identify_hazard_consequence_output=folder / "identify_hazard_consequence_output.json",
        identify_accident_scenario_output=folder / "identify_accident_scenario_output.json",
        causal_edge_linking_output=folder / "causal_edge_linking_output.json",
        hazard_consequence_json=str(hazards_json_path),
        accident_scenario_schema_json=str(accident_scenario_schema_path),
        output_docx_path=folder / "incident_card_report.docx",
    )


def run_batch_pipeline(config: Any) -> None:
    assert_prompt_step_configuration_valid(step_registry=STEP_REGISTRY)

    client = OpenAI()
    print("[RUNTIME] OPENAI_API_KEY =", _mask(os.getenv("OPENAI_API_KEY")))
    print("[RUNTIME] OPENAI_BASE_URL env =", os.getenv("OPENAI_BASE_URL"))
    print("[RUNTIME] client base_url =", getattr(client, "base_url", None))

    all_prompts = prompt_manager.prompts.load_all()
    configured_folders = getattr(config, "target_folders", None)
    if configured_folders is not None:
        folders = list(configured_folders)
    else:
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
        use_few_shot=getattr(config, "use_few_shot", False),
        few_shot_cases_by_step=getattr(config, "few_shot_cases_by_step", None),
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
                accident_scenario_schema_path=Path("scheme/accident_scenario_schema.json"),
            )
        except Exception as exc:
            print(f"Postprocess skipped for {folder.name}: {exc}")
