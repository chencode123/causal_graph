from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil

from pipeline.batch_runner import run_batch_pipeline as run_batch_api_pipeline
from pipeline.runner import run_batch_pipeline as run_responses_pipeline
from pipeline.step_registry import STEP_REGISTRY
from utils.batch_pipeline_utils import (
    PipelineConfig,
    copy_case_seed_files,
    discover_case_folders,
    filter_case_folders,
    iter_target_batch_dirs,
    prepare_round_output_dirs,
)


def _resolve_target_folders_for_batch(
    *,
    batch_dir: Path,
    config: PipelineConfig,
) -> tuple[Path, ...]:
    source_folder_map = config.source_folder_map or {}
    mapped_folders = tuple(
        folder
        for folder in source_folder_map
        if folder == batch_dir or folder.parent == batch_dir
    )
    if mapped_folders:
        return filter_case_folders(mapped_folders, config.target_cases)
    return filter_case_folders(
        discover_case_folders(batch_dir),
        config.target_cases,
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
            for folder in _resolve_target_folders_for_batch(
                batch_dir=batch_dir,
                config=config,
            )
        )
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
        target_folders = _resolve_target_folders_for_batch(
            batch_dir=batch_dir,
            config=config,
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
    target_batches: tuple[str, ...] | None = None,
) -> None:
    rounds = max(1, int(stability_rounds))
    start_round = max(1, int(stability_start_round))

    if rounds == 1 and stability_output_root is None and start_round == 1:
        run_single_or_multi_batch(
            config=config,
            run_base_dir=base_dir,
            execution_mode=execution_mode,
            upload_all_files_in_one_batch=upload_all_files_in_one_batch,
        )
        return

    source_batch_dirs = iter_target_batch_dirs(base_dir)
    if target_batches:
        requested_batches = set(target_batches)
        available_batches = {path.name for path in source_batch_dirs}
        missing_batches = sorted(requested_batches - available_batches)
        if missing_batches:
            raise ValueError(
                "Requested TARGET_BATCHES were not found under "
                f"{base_dir}: {', '.join(missing_batches)}"
            )
        source_batch_dirs = [
            path for path in source_batch_dirs if path.name in requested_batches
        ]
    source_case_dirs = tuple(
        folder
        for batch_dir in source_batch_dirs
        for folder in filter_case_folders(discover_case_folders(batch_dir), config.target_cases)
    )
    output_root = stability_output_root or (base_dir.parent / f"{base_dir.name}_stability")
    output_root.mkdir(parents=True, exist_ok=True)
    print(f"Stability mode enabled: rounds={rounds}, start_round={start_round}")
    print(f"Stability outputs root: {output_root}")

    flatten_single_case = len(source_case_dirs) == 1
    excluded_filenames = {
        STEP_REGISTRY[step_key]["output_file"]
        for step_key in (config.active_step_keys or ())
        if step_key in STEP_REGISTRY
    }

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
        source_folder_map: dict[Path, Path] = {}

        if flatten_single_case:
            source_case_dir = source_case_dirs[0]
            copy_case_seed_files(
                source_case_dir=source_case_dir,
                target_case_dir=round_base_dir,
                excluded_filenames=excluded_filenames,
            )
            source_folder_map[round_base_dir] = source_case_dir
            run_pipeline_for_mode(
                config=replace(
                    config,
                    base_dir=round_base_dir,
                    target_folders=(round_base_dir,),
                    target_cases=None,
                    source_folder_map=source_folder_map,
                    batch_workdir=round_base_dir / "_batch_pipeline",
                ),
                execution_mode=execution_mode,
            )
            continue

        # Preserve the batch directory whenever BASE_DIR is a parent containing
        # batch_* folders, even if TARGET_BATCHES selects only one of them.
        flatten_single_batch = (
            len(source_batch_dirs) == 1 and source_batch_dirs[0] == base_dir
        )
        for source_batch_dir in source_batch_dirs:
            round_batch_dir = (
                round_base_dir
                if flatten_single_batch
                else round_base_dir / source_batch_dir.name
            )
            source_folder_map.update(
                prepare_round_output_dirs(
                    source_batch_dir=source_batch_dir,
                    target_batch_dir=round_batch_dir,
                    target_cases=config.target_cases,
                    excluded_filenames=excluded_filenames,
                )
            )

        if flatten_single_batch:
            run_pipeline_for_mode(
                config=replace(
                    config,
                    base_dir=round_base_dir,
                    target_folders=tuple(source_folder_map),
                    source_folder_map=source_folder_map,
                    batch_workdir=round_base_dir / "_batch_pipeline",
                ),
                execution_mode=execution_mode,
            )
        else:
            run_single_or_multi_batch(
                config=replace(config, source_folder_map=source_folder_map),
                run_base_dir=round_base_dir,
                execution_mode=execution_mode,
                upload_all_files_in_one_batch=upload_all_files_in_one_batch,
            )
