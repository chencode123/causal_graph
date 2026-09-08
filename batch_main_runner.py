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

from pathlib import Path
import winsound

from dotenv import load_dotenv

from pipeline.entrypoint import run_single_or_multi_batch, run_with_stability
from pipeline.step_registry import STEP_REGISTRY
from utils.batch_pipeline_utils import PipelineConfig, discover_case_folders, iter_target_batch_dirs

load_dotenv(dotenv_path=Path(__file__).with_name(".env_openai"), override=True)

# ================================================================
# CONFIG
# ================================================================
STABILITY_OUTPUT_ROOT = Path(r"runs\stability_test\rounds_with_few_shot")
ROUND4_DIR = STABILITY_OUTPUT_ROOT / "round_4"
ROUND5_DIR = STABILITY_OUTPUT_ROOT / "round_5"
EXECUTION_MODE = "batch"
RESPONSES_ASYNC_ENABLED = True  # Only applies when EXECUTION_MODE="responses"; when True, folders within each step run concurrently.
UPLOAD_ALL_FILES_IN_ONE_BATCH = True
TARGET_CASES = None
TARGET_BATCHES = None

MODEL_NAME = "gpt-5.4-2026-03-05"
REASONING_EFFORT = "medium"
VERBOSITY = "medium"
FORCE_JSON_OUTPUT = True
SAVE_RAW_RESPONSE = True
MAX_OUTPUT_TOKENS = 32000
CALL_SLEEP_SECONDS = 0.0
REMOVE_SHORTCUT_EDGES = False
HAZARDS_JSON_PATH = Path("prompt/hazards_consequence.json")
CONDITIONS_JSON_PATH = Path("prompt/conditions.json")
USE_FEW_SHOT = True
FEW_SHOT_PATTERN_FILES_BY_STEP = {
    "graph_diagnosis": (
        Path(r"runs\few-shot\review_feedback\case_coverage_12\review_feedback_analysis_few_shot_balanced_small.json"),
    ),
    "graph_revision_planning": (
        Path(r"runs\few-shot\review_feedback\case_coverage_12\review_feedback_analysis_few_shot_balanced_small.json"),
    ),
}
ALL_STEP_KEYS = (
    # "identify_hazard_consequence",
    "causal_narrative_extraction",
    "scenario_candidate_extraction",
    "scenario_structure_validation",
    "identify_accident_scenario",
    "edge_candidate_extraction",
    "edge_structure_validation",
    "causal_edge_linking",
    "graph_diagnosis",
    "graph_revision_planning",
    # "review_feedback_analysis", 
)


def build_config(base_dir: Path, active_step_keys: tuple[str, ...]) -> PipelineConfig:
    return PipelineConfig(
        base_dir=base_dir,
        model_name=MODEL_NAME,
        reasoning_effort=REASONING_EFFORT,
        verbosity=VERBOSITY,
        force_json_output=FORCE_JSON_OUTPUT,
        save_raw_response=SAVE_RAW_RESPONSE,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        call_sleep_seconds=CALL_SLEEP_SECONDS,
        remove_shortcut_edges=REMOVE_SHORTCUT_EDGES,
        hazards_json_path=HAZARDS_JSON_PATH,
        conditions_json_path=CONDITIONS_JSON_PATH,
        use_few_shot=USE_FEW_SHOT,
        few_shot_pattern_files_by_step=FEW_SHOT_PATTERN_FILES_BY_STEP,
        target_cases=TARGET_CASES,
        active_step_keys=active_step_keys,
        responses_async_enabled=RESPONSES_ASYNC_ENABLED,
    )


def discover_round_cases(round_dir: Path) -> tuple[Path, ...]:
    return tuple(
        case_dir
        for batch_dir in iter_target_batch_dirs(round_dir)
        for case_dir in discover_case_folders(batch_dir)
    )


def missing_step_suffix(round_dir: Path) -> tuple[str, ...]:
    case_dirs = discover_round_cases(round_dir)
    if not case_dirs:
        raise RuntimeError(f"No runnable case folders found under {round_dir}")
    for index, step_key in enumerate(ALL_STEP_KEYS):
        output_name = STEP_REGISTRY[step_key]["output_file"]
        completed = sum((case_dir / output_name).is_file() for case_dir in case_dirs)
        print(f"[{round_dir.name}] {step_key}: {completed}/{len(case_dirs)} outputs")
        if completed != len(case_dirs):
            return ALL_STEP_KEYS[index:]
    return ()


def resume_existing_round(round_dir: Path) -> None:
    pending_steps = missing_step_suffix(round_dir)
    if not pending_steps:
        print(f"{round_dir.name} already has all {len(ALL_STEP_KEYS)} step outputs.")
        return
    print(f"Resuming {round_dir.name} from: {pending_steps[0]}")
    run_single_or_multi_batch(
        config=build_config(round_dir, pending_steps),
        run_base_dir=round_dir,
        execution_mode=EXECUTION_MODE,
        upload_all_files_in_one_batch=UPLOAD_ALL_FILES_IN_ONE_BATCH,
    )


if __name__ == "__main__":
    if not ROUND4_DIR.is_dir():
        raise FileNotFoundError(f"Round 4 source directory does not exist: {ROUND4_DIR}")

    resume_existing_round(ROUND4_DIR)

    if ROUND5_DIR.exists():
        resume_existing_round(ROUND5_DIR)
    else:
        run_with_stability(
            config=build_config(ROUND4_DIR, ALL_STEP_KEYS),
            base_dir=ROUND4_DIR,
            execution_mode=EXECUTION_MODE,
            upload_all_files_in_one_batch=UPLOAD_ALL_FILES_IN_ONE_BATCH,
            stability_rounds=1,
            stability_start_round=5,
            stability_resume=False,
            stability_output_root=STABILITY_OUTPUT_ROOT,
            target_batches=TARGET_BATCHES,
        )

    print("Done.")
    winsound.Beep(1000, 500)
