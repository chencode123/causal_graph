from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from openai import OpenAI

from pipeline.io_utils import (
    extract_text_from_responses_body,
    get_response_dir,
    render_prompt,
    save_step_input_snapshot,
    write_text,
)
from pipeline.runner import ensure_causal_graph_json
from pipeline.step_registry import STEP_REGISTRY
from pipeline.step_var_resolver import get_step_var_builder


@dataclass(frozen=True)
class SingleStepRerunConfig:
    case_dir: Path
    prompt_path: Path
    step_key: str
    model_name: str
    reasoning_effort: str
    verbosity: str
    max_output_tokens: int
    hazards_json_path: Path
    conditions_json_path: Path
    project_root: Path


def copy_case_tree(source_case_dir: Path, destination_case_dir: Path) -> None:
    if destination_case_dir.exists():
        shutil.rmtree(destination_case_dir)
    shutil.copytree(source_case_dir, destination_case_dir)


def rerun_single_step(config: SingleStepRerunConfig) -> Path:
    client = OpenAI()
    template = config.prompt_path.read_text(encoding="utf-8")
    build_vars = get_step_var_builder(
        key=config.step_key,
        hazards_json=config.hazards_json_path,
        conditions_json=config.conditions_json_path,
        project_root=config.project_root,
        use_few_shot=False,
        few_shot_cases=(),
    )
    vars_dict = build_vars(config.case_dir)
    prompt_text = render_prompt(template, vars_dict)
    messages = [
        {"role": "system", "content": "You are a professional process safety analyst."},
        {"role": "user", "content": prompt_text},
    ]
    save_step_input_snapshot(
        folder=config.case_dir,
        step_key=config.step_key,
        template=template,
        vars_dict=vars_dict,
        prompt_text=prompt_text,
        messages=messages,
        truncate_limit=80000,
    )

    response = client.responses.create(
        model=config.model_name,
        input=messages,
        max_output_tokens=config.max_output_tokens,
        text={"verbosity": config.verbosity, "format": {"type": "json_object"}},
        reasoning={"effort": config.reasoning_effort},
    )
    body = response.model_dump() if hasattr(response, "model_dump") else dict(response)
    out_text = extract_text_from_responses_body(body)

    output_filename = STEP_REGISTRY[config.step_key]["output_file"]
    output_path = config.case_dir / output_filename
    write_text(output_path, out_text)

    response_dir = get_response_dir(config.case_dir)
    write_text(
        response_dir / f"{config.step_key}_response_raw.json",
        json.dumps(body, ensure_ascii=False, indent=2),
    )

    ensure_causal_graph_json(config.case_dir)
    return output_path
