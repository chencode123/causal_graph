from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil

from pipeline.batch_runner import run_batch_pipeline as run_batch_api_pipeline
from pipeline.runner import run_batch_pipeline as run_responses_pipeline
from utils.batch_pipeline_utils import (
    PipelineConfig,
    copy_batch_for_round,
    discover_case_folders,
    filter_case_folders,
    iter_target_batch_dirs,
)


def run_pipeline_for_mode(
    *,
    config: PipelineConfig,
    execution_mode: str,
) -> None:
    mode = execution_mode.strip().lower()
    if mode == "batch":
        run_batch_api_pipeline(config)
        return
    if mode == "responses":
        run_responses_pipeline(config)
        return
    raise ValueError(
        f"Unsupported EXECUTION_MODE={execution_mode!r}. Use 'batch' or 'responses'."
    )


def run_single_or_multi_batch(
    *,
    config: PipelineConfig,
    run_base_dir: Path,
    execution_mode: str,
    upload_all_files_in_one_batch: bool,
) -> None:
    """Run pipeline once for a base dir (single-batch or multi-batch mode)."""
    target_batch_dirs = iter_target_batch_dirs(run_base_dir)
    if upload_all_files_in_one_batch and len(target_batch_dirs) > 1:
        target_folders = tuple(
            folder
            for batch_dir in target_batch_dirs
            for folder in discover_case_folders(batch_dir)
        )
        target_folders = filter_case_folders(target_folders, config.target_cases)
        combined_base_dir = run_base_dir
        combined_workdir = combined_base_dir / "_batch_pipeline_all"
        print(f"Running one combined batch pipeline for: {combined_base_dir}")
        print(f"Combined folders: {len(target_folders)}")
        run_pipeline_for_mode(
            config=replace(
                config,
                base_dir=combined_base_dir,
                target_folders=target_folders,
                batch_workdir=combined_workdir,
            ),
            execution_mode=execution_mode,
        )
        return

    for batch_dir in target_batch_dirs:
        target_folders = filter_case_folders(
            discover_case_folders(batch_dir),
            config.target_cases,
        )
        print(f"Running {execution_mode} pipeline for: {batch_dir}")
        run_pipeline_for_mode(
            config=replace(
                config,
                base_dir=batch_dir,
                target_folders=target_folders,
            ),
            execution_mode=execution_mode,
        )


def run_with_stability(
    *,
    config: PipelineConfig,
    base_dir: Path,
    execution_mode: str,
    upload_all_files_in_one_batch: bool,
    stability_rounds: int,
    stability_start_round: int,
    stability_resume: bool,
    stability_output_root: Path | None,
) -> None:
    rounds = max(1, int(stability_rounds))
    start_round = max(1, int(stability_start_round))

    if rounds == 1:
        run_single_or_multi_batch(
            config=config,
            run_base_dir=base_dir,
            execution_mode=execution_mode,
            upload_all_files_in_one_batch=upload_all_files_in_one_batch,
        )
        return

    source_batch_dirs = iter_target_batch_dirs(base_dir)
    output_root = stability_output_root or (base_dir.parent / f"{base_dir.name}_stability")
    output_root.mkdir(parents=True, exist_ok=True)
    print(f"Stability mode enabled: rounds={rounds}, start_round={start_round}")
    print(f"Stability outputs root: {output_root}")

    for round_offset in range(rounds):
        round_index = start_round + round_offset
        print(f"\n=== Stability Round {round_index} ===")
        round_base_dir = output_root / f"round_{round_index}"
        if round_base_dir.exists():
            if stability_resume:
                print(f"Round {round_index} exists, skipping (--resume enabled).")
                continue
            shutil.rmtree(round_base_dir)
        round_base_dir.mkdir(parents=True, exist_ok=True)

        for source_batch_dir in source_batch_dirs:
            round_batch_dir = round_base_dir / f"{source_batch_dir.name}_output_round_{round_index}"
            copy_batch_for_round(
                source_batch_dir=source_batch_dir,
                target_batch_dir=round_batch_dir,
                target_cases=config.target_cases,
            )

        run_single_or_multi_batch(
            config=config,
            run_base_dir=round_base_dir,
            execution_mode=execution_mode,
            upload_all_files_in_one_batch=upload_all_files_in_one_batch,
        )
