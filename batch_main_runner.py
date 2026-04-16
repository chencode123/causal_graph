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

from pipeline.entrypoint import run_with_stability
from utils.batch_pipeline_utils import (
    PipelineConfig,
    build_few_shot_cases_by_step,
)


load_dotenv(dotenv_path=Path(__file__).with_name(".env_openai"), override=True)

# ================================================================
# CONFIG
# ================================================================
#############################################################################更新所有的update_html
BASE_DIR = Path(r"runs\stability_test\batch_4_without_few_shot_reruns\round_2")  # Can point to a single batch dir or a folder containing batch_* subdirs.
EXECUTION_MODE = "responses"  # "batch" uses OpenAI Batch API; "responses" uses direct Responses API for faster iteration/debugging.
RESPONSES_ASYNC_ENABLED = True  # Only applies when EXECUTION_MODE="responses"; when True, folders within each step run concurrently.
UPLOAD_ALL_FILES_IN_ONE_BATCH = False  # Merge all discovered case folders into one large job per step when multiple batch_* dirs are present.
TARGET_CASES = None
# TARGET_CASES = ("round_1",)  # Only use round_1 as the source case for stability reruns.
STABILITY_ROUNDS = 1  # Generate round_2 and round_3 from the source case.
STABILITY_START_ROUND = 1  # Starting round index for resumable naming.
STABILITY_RESUME = False  # Skip a round when its output folder already exists.
STABILITY_OUTPUT_ROOT = Path(r"runs\stability_test\batch_4_without_few_shot_reruns")
  # Defaults to BASE_DIR.parent / f"{BASE_DIR.name}_stability".

MODEL_NAME = "gpt-5.4-2026-03-05"
REASONING_EFFORT = "high"
VERBOSITY = "medium"
FORCE_JSON_OUTPUT = True
SAVE_RAW_RESPONSE = True
MAX_OUTPUT_TOKENS = 128000
CALL_SLEEP_SECONDS = 0.0
REMOVE_SHORTCUT_EDGES = False
HAZARDS_JSON_PATH = Path("prompt/hazards_consequence.json")
CONDITIONS_JSON_PATH = Path("prompt/conditions.json")
USE_FEW_SHOT = False
FEW_SHOT_CASES = (
    Path("runs/few-shot/test_confined_explosion/batch_1_9_ignition"),
)
FEW_SHOT_PATTERN_FILES_BY_STEP = {
    "graph_diagnosis": (
        Path(r"runs\stability_test\batch4_4_reruns\round_1\review_feedback_analysis_output.json"),
    ),
    "graph_revision_planning": (
        Path(r"runs\stability_test\batch4_4_reruns\round_1\review_feedback_analysis_output.json"),
    ),
}
ACTIVE_STEP_KEYS = (
    # "identify_hazard_consequence",
    # "causal_narrative_extraction",
    # "scenario_candidate_extraction",
    # "scenario_structure_validation",
    # "identify_accident_scenario",
    # "edge_candidate_extraction",
    # "edge_structure_validation",
    # "causal_edge_linking",
    # "graph_diagnosis",
    # "graph_revision_planning",
    # "review_feedback_analysis", 
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
        remove_shortcut_edges=REMOVE_SHORTCUT_EDGES,
        hazards_json_path=HAZARDS_JSON_PATH,
        conditions_json_path=CONDITIONS_JSON_PATH,
        use_few_shot=USE_FEW_SHOT,
        few_shot_cases_by_step=build_few_shot_cases_by_step(FEW_SHOT_CASES),
        few_shot_pattern_files_by_step=FEW_SHOT_PATTERN_FILES_BY_STEP,
        target_cases=TARGET_CASES,
        active_step_keys=ACTIVE_STEP_KEYS,
        responses_async_enabled=RESPONSES_ASYNC_ENABLED,
    )
    run_with_stability(
        config=config,
        base_dir=BASE_DIR,
        execution_mode=EXECUTION_MODE,
        upload_all_files_in_one_batch=UPLOAD_ALL_FILES_IN_ONE_BATCH,
        stability_rounds=STABILITY_ROUNDS,
        stability_start_round=STABILITY_START_ROUND,
        stability_resume=STABILITY_RESUME,
        stability_output_root=STABILITY_OUTPUT_ROOT,
    )

    print("Done.")
    winsound.Beep(1000, 500)
