from __future__ import annotations
"""
Batch pipeline entrypoint for running the process-safety extraction workflow.

This script supports two execution scopes:
1. Single-batch mode:
   Run the pipeline only for `BASE_DIR`.
2. Multi-batch mode:
   Discover child `batch_*` directories under `BASE_DIR` and run them all.

It also supports two upload strategies when multi-batch mode is enabled:
1. Per-batch submission:
   Submit one OpenAI Batch job per discovered batch directory.
2. Combined submission:
   Merge all discovered case folders into one large OpenAI Batch job per
   pipeline step, while still writing outputs back to the original case
   folders.

Recommended usage:
- Point `BASE_DIR` at either one batch directory or a parent folder that
  contains multiple `batch_*` directories.
- Use `UPLOAD_ALL_FILES_IN_ONE_BATCH = True` only when you explicitly want
  to maximize request consolidation across multiple batch directories.
"""

from dataclasses import dataclass, replace
from pathlib import Path
import shutil
import winsound

from dotenv import load_dotenv

from pipeline.batch_runner import run_batch_pipeline as run_batch_api_pipeline
from pipeline.runner import run_batch_pipeline as run_responses_pipeline


load_dotenv(dotenv_path=Path(__file__).with_name(".env_openai"), override=True)

# ================================================================
# CONFIG
# ================================================================
#############################################################################更新所有的update_html
BASE_DIR = Path(r"runs\few-shot\test_confined_explosion")  # Can point to a single batch dir or a folder containing batch_* subdirs.
EXECUTION_MODE = "responses"  # "batch" uses OpenAI Batch API; "responses" uses direct Responses API for faster iteration/debugging.
UPLOAD_ALL_FILES_IN_ONE_BATCH = True  # Merge all discovered case folders into one large job per step when multiple batch_* dirs are present.
# TARGET_CASES: tuple[str, ...] | None = None  # Example: ("1",) to run only case folder 1 under BASE_DIR.
TARGET_CASES = ("batch_1_9_ignition",)
STABILITY_ROUNDS = 1  # Repeat count for stability runs. Use 1 to keep current single-run behavior.
STABILITY_START_ROUND = 1  # Starting round index for resumable naming.
STABILITY_RESUME = False  # Skip a round when its output folder already exists.
STABILITY_OUTPUT_ROOT: Path | None = None  # Defaults to BASE_DIR.parent / f"{BASE_DIR.name}_stability".

MODEL_NAME = "gpt-5.4-2026-03-05"
REASONING_EFFORT = "high"
VERBOSITY = "medium"
FORCE_JSON_OUTPUT = True
SAVE_RAW_RESPONSE = True
MAX_OUTPUT_TOKENS = 128000
CALL_SLEEP_SECONDS = 0.0
HAZARDS_JSON_PATH = Path("prompt/hazards_consequence.json")
CONDITIONS_JSON_PATH = Path("prompt/conditions.json")
USE_FEW_SHOT = False
FEW_SHOT_CASES_BY_STEP = {
    "identify_hazard_consequence": [
        Path("prompt/few-shot/fire_explosion_toxicity/toxicity_dispersion"),
        Path("prompt/few-shot/fire_explosion_toxicity/jet_fire"),
        Path("prompt/few-shot/fire_explosion_toxicity/pressure_driven_without_ignition_confined_explosion"),
    ],
    "identify_accident_scenario": [
        Path("prompt/few-shot/fire_explosion_toxicity/toxicity_dispersion"),
        Path("prompt/few-shot/fire_explosion_toxicity/jet_fire"),
        Path("prompt/few-shot/fire_explosion_toxicity/pressure_driven_without_ignition_confined_explosion"),
    ],
    "causal_edge_linking": [
        Path("prompt/few-shot/fire_explosion_toxicity/toxicity_dispersion"),
        Path("prompt/few-shot/fire_explosion_toxicity/jet_fire"),
        Path("prompt/few-shot/fire_explosion_toxicity/pressure_driven_without_ignition_confined_explosion"),
    ],
}

@dataclass(frozen=True)
class PipelineConfig:
    """Runtime configuration passed into the pipeline batch runner."""
    base_dir: Path
    model_name: str
    reasoning_effort: str
    verbosity: str
    force_json_output: bool
    save_raw_response: bool
    max_output_tokens: int
    call_sleep_seconds: float
    hazards_json_path: Path
    conditions_json_path: Path
    use_few_shot: bool = False
    few_shot_cases_by_step: dict[str, tuple[Path, ...]] | None = None
    target_folders: tuple[Path, ...] | None = None
    target_cases: tuple[str, ...] | None = None
    batch_workdir: Path | None = None


def iter_target_batch_dirs(base_dir: Path) -> list[Path]:
    """Return target batch dirs based on the current BASE_DIR contents."""
    child_batch_dirs = sorted(
        path
        for path in base_dir.iterdir()
        if path.is_dir() and path.name.startswith("batch_")
    )
    return child_batch_dirs or [base_dir]


def filter_case_folders(
    folders: tuple[Path, ...],
    target_cases: tuple[str, ...] | None,
) -> tuple[Path, ...]:
    if not target_cases:
        return folders
    allowed = {case_name.strip() for case_name in target_cases if case_name.strip()}
    return tuple(folder for folder in folders if folder.name in allowed)


def is_case_folder(folder: Path) -> bool:
    """Heuristic: treat a directory as a case folder when core case artifacts exist."""
    marker_files = (
        "identify_incident_output.json",
        "identify_hazard_consequence_output.json",
        "identify_accident_scenario_output.json",
        "causal_edge_linking_output.json",
        "causal_graph.json",
        "review_causal_graph_output.json",
    )
    return any((folder / marker).exists() for marker in marker_files)


def discover_case_folders(batch_dir: Path) -> tuple[Path, ...]:
    """
    Discover case folders under one batch directory.
    If batch_dir itself already looks like a case folder, return it directly.
    """
    if is_case_folder(batch_dir):
        return (batch_dir,)
    return tuple(
        folder
        for folder in sorted(batch_dir.iterdir())
        if folder.is_dir() and not folder.name.startswith("_")
    )


def run_pipeline_for_mode(config: PipelineConfig) -> None:
    mode = EXECUTION_MODE.strip().lower()
    if mode == "batch":
        run_batch_api_pipeline(config)
        return
    if mode == "responses":
        run_responses_pipeline(config)
        return
    raise ValueError(
        f"Unsupported EXECUTION_MODE={EXECUTION_MODE!r}. Use 'batch' or 'responses'."
    )


def copy_batch_for_round(
    *,
    source_batch_dir: Path,
    target_batch_dir: Path,
    target_cases: tuple[str, ...] | None,
) -> None:
    """Prepare one round's input directory by copying selected case folders."""
    if target_batch_dir.exists():
        shutil.rmtree(target_batch_dir)
    target_batch_dir.mkdir(parents=True, exist_ok=True)

    allowed = None
    if target_cases:
        allowed = {name.strip() for name in target_cases if name.strip()}

    source_case_dirs = [
        folder
        for folder in sorted(source_batch_dir.iterdir())
        if folder.is_dir() and not folder.name.startswith("_")
    ]
    for source_case_dir in source_case_dirs:
        if allowed is not None and source_case_dir.name not in allowed:
            continue
        shutil.copytree(
            source_case_dir,
            target_batch_dir / source_case_dir.name,
            dirs_exist_ok=False,
        )


def run_single_or_multi_batch(config: PipelineConfig, run_base_dir: Path) -> None:
    """Run pipeline once for a base dir (single-batch or multi-batch mode)."""
    target_batch_dirs = iter_target_batch_dirs(run_base_dir)
    if UPLOAD_ALL_FILES_IN_ONE_BATCH and len(target_batch_dirs) > 1:
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
            replace(
                config,
                base_dir=combined_base_dir,
                target_folders=target_folders,
                batch_workdir=combined_workdir,
            )
        )
        return

    for batch_dir in target_batch_dirs:
        target_folders = filter_case_folders(
            discover_case_folders(batch_dir),
            config.target_cases,
        )
        print(f"Running {EXECUTION_MODE} pipeline for: {batch_dir}")
        run_pipeline_for_mode(
            replace(
                config,
                base_dir=batch_dir,
                target_folders=target_folders,
            )
        )


if __name__ == "__main__":
    config = PipelineConfig(
        base_dir=BASE_DIR,
        model_name=MODEL_NAME,
        reasoning_effort=REASONING_EFFORT,
        verbosity=VERBOSITY,
        force_json_output=FORCE_JSON_OUTPUT,
        save_raw_response=SAVE_RAW_RESPONSE,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        call_sleep_seconds=CALL_SLEEP_SECONDS,
        hazards_json_path=HAZARDS_JSON_PATH,
        conditions_json_path=CONDITIONS_JSON_PATH,
        use_few_shot=USE_FEW_SHOT,
        few_shot_cases_by_step={
            key: tuple(paths) for key, paths in FEW_SHOT_CASES_BY_STEP.items()
        },
        target_cases=TARGET_CASES,
    )
    rounds = max(1, int(STABILITY_ROUNDS))
    start_round = max(1, int(STABILITY_START_ROUND))
    if rounds == 1:
        run_single_or_multi_batch(config, BASE_DIR)
    else:
        source_batch_dirs = iter_target_batch_dirs(BASE_DIR)
        output_root = STABILITY_OUTPUT_ROOT or (BASE_DIR.parent / f"{BASE_DIR.name}_stability")
        output_root.mkdir(parents=True, exist_ok=True)
        print(f"Stability mode enabled: rounds={rounds}, start_round={start_round}")
        print(f"Stability outputs root: {output_root}")
        for round_offset in range(rounds):
            round_index = start_round + round_offset
            print(f"\n=== Stability Round {round_index} ===")
            round_base_dir = output_root / f"round_{round_index}"
            if round_base_dir.exists():
                if STABILITY_RESUME:
                    print(f"Round {round_index} exists, skipping (--resume enabled).")
                    continue
                shutil.rmtree(round_base_dir)
            round_base_dir.mkdir(parents=True, exist_ok=True)

            for source_batch_dir in source_batch_dirs:
                round_batch_dir = round_base_dir / f"{source_batch_dir.name}_output_round_{round_index}"
                copy_batch_for_round(
                    source_batch_dir=source_batch_dir,
                    target_batch_dir=round_batch_dir,
                    target_cases=TARGET_CASES,
                )

            run_single_or_multi_batch(config, round_base_dir)

    print("Done.")
    winsound.Beep(1000, 500)
