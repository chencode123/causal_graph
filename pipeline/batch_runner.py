from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List

from openai import OpenAI
from tqdm import tqdm

import utils.prompt_manager as prompt_manager
from utils.prompt_validator import assert_prompt_step_configuration_valid

from .io_utils import (
    extract_text_from_responses_body,
    get_response_dir,
    render_prompt,
    save_step_input_snapshot,
    write_text,
)
from .runner import ensure_causal_graph_json, run_local_postprocess, write_review_feedback_analysis_markdown
from .step_factory import Step, build_pipeline
from .step_registry import STEP_REGISTRY


ENDPOINT = "/v1/responses"
COMPLETION_WINDOW = "24h"
INPUT_FILE_RETRY_ATTEMPTS = 3


def _mask(key: str | None) -> str:
    if not key:
        return "<None>"
    return key[:8] + "..." + key[-4:]


def _load_required_prompts() -> Dict[str, str]:
    """Load prompt templates from the shared manifest-backed prompt manager."""
    return prompt_manager.prompts.load_all()


def poll_batch_until_done(
    client: OpenAI,
    batch_id: str,
    poll_seconds: int = 15,
    progress_bar: tqdm | None = None,
) -> Dict[str, Any]:
    """Poll a batch until it reaches a terminal state."""
    while True:
        batch = client.batches.retrieve(batch_id)
        status = batch.status
        if progress_bar is not None:
            batch_dict = batch.model_dump() if hasattr(batch, "model_dump") else dict(batch)
            request_counts = batch_dict.get("request_counts") or {}
            completed = int(request_counts.get("completed", 0) or 0)
            failed = int(request_counts.get("failed", 0) or 0)
            total_done = completed + failed
            if total_done > progress_bar.n:
                progress_bar.update(total_done - progress_bar.n)
            progress_bar.set_description(f"{batch_id} | {status}")
        if status in ("completed", "failed", "expired", "cancelled"):
            return batch.model_dump() if hasattr(batch, "model_dump") else dict(batch)
        time.sleep(poll_seconds)


def download_file_text(client: OpenAI, file_id: str) -> str:
    """Download a batch output or error file as text."""
    response = client.files.content(file_id)
    return response.text if hasattr(response, "text") else str(response)


def _is_missing_input_file_failure(batch: Dict[str, Any]) -> bool:
    errors = (batch.get("errors") or {}).get("data") or []
    return any(
        error.get("code") == "invalid_request"
        and "cannot find file" in str(error.get("message", "")).lower()
        for error in errors
        if isinstance(error, dict)
    )


def run_step_as_batch(
    client: OpenAI,
    all_prompts: Dict[str, str],
    folders: List[Path],
    step: Step,
    config: Any,
    batch_workdir: Path,
) -> None:
    """Run one pipeline step as a single OpenAI Batch job across all folders."""
    if step.key in {"review_causal_graph", "graph_diagnosis", "graph_revision_planning"}:
        prep_ok = 0
        prep_fail = 0
        for folder in folders:
            try:
                ensure_causal_graph_json(
                    folder,
                    remove_shortcut_edges=getattr(config, "remove_shortcut_edges", True),
                )
                prep_ok += 1
            except Exception as exc:
                prep_fail += 1
                write_text(folder / f"{step.key}_error.txt", f"Graph prep failed: {exc}\n")
        tqdm.write(f"[{step.key}] Graph prep done. ok={prep_ok}, fail={prep_fail}")
    template = all_prompts[step.key]
    batch_input_path = batch_workdir / f"{step.key}_batchinput.jsonl"

    id_to_folder: Dict[str, Path] = {}
    lines: List[str] = []

    for folder in folders:
        try:
            vars_dict = step.build_vars(folder)
            prompt_text = render_prompt(template, vars_dict)
        except Exception as exc:
            write_text(folder / f"{step.key}_error.txt", f"Prompt build failed: {exc}\n")
            continue

        custom_id = str(folder.relative_to(config.base_dir)).replace("\\", "__").replace("/", "__")
        id_to_folder[custom_id] = folder

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

        text_cfg: Dict[str, Any] = {"verbosity": step.verbosity or config.verbosity}
        structured_schema = (
            getattr(config, "structured_output_schemas", None) or {}
        ).get(step.key)
        if structured_schema is not None:
            text_cfg["format"] = {
                "type": "json_schema",
                "name": f"{step.key}_output",
                "strict": True,
                "schema": structured_schema,
            }
        elif getattr(config, "force_json_output", False):
            text_cfg["format"] = {"type": "json_object"}

        body: Dict[str, Any] = {
            "model": config.model_name,
            "input": messages,
            "max_output_tokens": config.max_output_tokens,
            "text": text_cfg,
        }
        if step.temperature is not None:
            body["temperature"] = step.temperature
        else:
            body["reasoning"] = {"effort": step.reasoning_effort or config.reasoning_effort}

        req = {
            "custom_id": custom_id,
            "method": "POST",
            "url": ENDPOINT,
            "body": body,
        }
        lines.append(json.dumps(req, ensure_ascii=False))

    if not lines:
        tqdm.write(f"[{step.key}] No runnable folders. Skipping.")
        return

    write_text(batch_input_path, "\n".join(lines) + "\n")
    tqdm.write(f"[{step.key}] Prepared {len(lines)} requests: {batch_input_path}")

    final: Dict[str, Any] | None = None
    for upload_attempt in range(1, INPUT_FILE_RETRY_ATTEMPTS + 1):
        with batch_input_path.open("rb") as fp:
            uploaded = client.files.create(file=fp, purpose="batch")

        # Confirm that the same project can retrieve the uploaded file before
        # handing its ID to asynchronous Batch validation.
        client.files.retrieve(uploaded.id)
        batch = client.batches.create(
            input_file_id=uploaded.id,
            endpoint=ENDPOINT,
            completion_window=COMPLETION_WINDOW,
            metadata={"step": step.key},
        )
        tqdm.write(
            f"[{step.key}] Created batch: {batch.id} "
            f"(upload attempt {upload_attempt}/{INPUT_FILE_RETRY_ATTEMPTS})"
        )

        batch_job_progress = tqdm(
            total=len(lines), desc=f"{step.key} batch", unit="req", leave=False
        )
        final = poll_batch_until_done(
            client,
            batch_id=batch.id,
            poll_seconds=15,
            progress_bar=batch_job_progress,
        )
        if batch_job_progress.n < batch_job_progress.total:
            batch_job_progress.update(batch_job_progress.total - batch_job_progress.n)
        batch_job_progress.close()
        if not _is_missing_input_file_failure(final):
            break
        if upload_attempt < INPUT_FILE_RETRY_ATTEMPTS:
            tqdm.write(
                f"[{step.key}] Uploaded input file was unavailable during Batch "
                "validation; uploading a fresh copy and retrying."
            )

    if final is None:
        raise RuntimeError(f"[{step.key}] Batch submission produced no Batch object.")
    write_text(
        batch_workdir / f"{step.key}_batch_object.json",
        json.dumps(final, ensure_ascii=False, indent=2),
    )
    tqdm.write(f"[{step.key}] Final status: {final.get('status')}")

    error_file_id = final.get("error_file_id")
    if error_file_id:
        err_text = download_file_text(client, error_file_id)
        write_text(batch_workdir / f"{step.key}_errors.jsonl", err_text)

    output_file_id = final.get("output_file_id")
    if not output_file_id:
        raise RuntimeError(
            f"[{step.key}] Batch ended with status={final.get('status')} and "
            "returned no successful outputs; stopping before dependent steps."
        )

    out_text = download_file_text(client, output_file_id)
    write_text(batch_workdir / f"{step.key}_output_raw.jsonl", out_text)

    ok = 0
    fail = 0
    for line in out_text.splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        custom_id = obj.get("custom_id")
        folder = id_to_folder.get(custom_id)
        if folder is None:
            continue

        error = obj.get("error")
        response = obj.get("response")

        if error:
            fail += 1
            write_text(folder / f"{step.key}_error.txt", json.dumps(error, ensure_ascii=False, indent=2))
            continue

        if not response or response.get("status_code") != 200:
            fail += 1
            write_text(folder / f"{step.key}_error.txt", json.dumps(obj, ensure_ascii=False, indent=2))
            continue

        text = extract_text_from_responses_body(response.get("body", {}))
        write_text(step.output_path(folder), text)
        if step.key == "review_feedback_analysis":
            write_review_feedback_analysis_markdown(folder)
        ok += 1

        if config.save_raw_response:
            response_dir = get_response_dir(folder)
            write_text(
                response_dir / f"{step.key}_response_raw.json",
                json.dumps(response.get("body", {}), ensure_ascii=False, indent=2),
            )

    tqdm.write(f"[{step.key}] Batch done. ok={ok}, fail={fail}")


def run_batch_pipeline(config: Any) -> None:
    """Run the current pipeline using OpenAI Batch API for LLM steps."""
    assert_prompt_step_configuration_valid(step_registry=STEP_REGISTRY)

    client = OpenAI()
    tqdm.write(f"[RUNTIME] OPENAI_API_KEY = {_mask(os.getenv('OPENAI_API_KEY'))}")
    tqdm.write(f"[RUNTIME] OPENAI_BASE_URL env = {os.getenv('OPENAI_BASE_URL')}")
    tqdm.write(f"[RUNTIME] client base_url = {getattr(client, 'base_url', None)}")

    all_prompts = _load_required_prompts()
    configured_folders = getattr(config, "target_folders", None)
    if configured_folders is not None:
        folders = list(configured_folders)
    else:
        folders = [
            folder
            for folder in config.base_dir.iterdir()
            if folder.is_dir() and not folder.name.startswith("_")
        ]
    tqdm.write(f"Found {len(folders)} folders under {config.base_dir}")

    for folder in folders:
        get_response_dir(folder)

    pipeline = build_pipeline(
        hazards_json=config.hazards_json_path,
        conditions_json=config.conditions_json_path,
        use_few_shot=getattr(config, "use_few_shot", False),
        few_shot_cases_by_step=getattr(config, "few_shot_cases_by_step", None),
        few_shot_pattern_files_by_step=getattr(
            config, "few_shot_pattern_files_by_step", None
        ),
        active_step_keys=getattr(config, "active_step_keys", None),
        source_folder_map=getattr(config, "source_folder_map", None),
    )
    batch_workdir = getattr(config, "batch_workdir", None) or (config.base_dir / "_batch_pipeline")
    batch_workdir.mkdir(parents=True, exist_ok=True)

    for step in tqdm(pipeline, desc="Batch Steps", unit="step"):
        if not step.enabled:
            continue
        run_step_as_batch(
            client=client,
            all_prompts=all_prompts,
            folders=folders,
            step=step,
            config=config,
            batch_workdir=batch_workdir,
        )

    if getattr(config, "enable_local_postprocess", True):
        for folder in tqdm(folders, desc="Local postprocess", unit="folder"):
            try:
                run_local_postprocess(
                    all_prompts=all_prompts,
                    folder=folder,
                    hazards_json_path=config.hazards_json_path,
                    accident_scenario_schema_path=Path("scheme/accident_scenario_schema.json"),
                    source_folder=(getattr(config, "source_folder_map", None) or {}).get(folder, folder),
                    remove_shortcut_edges=getattr(config, "remove_shortcut_edges", True),
                )
            except Exception as exc:
                tqdm.write(f"Postprocess skipped for {folder.name}: {exc}")
