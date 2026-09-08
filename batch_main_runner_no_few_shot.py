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
from utils.batch_pipeline_utils import PipelineConfig

ENV_FILE = Path(__file__).with_name(".env_openai")
if not ENV_FILE.is_file():
    raise FileNotFoundError(
        f"Missing {ENV_FILE.name}. Create it with OPENAI_API_KEY."
    )
load_dotenv(dotenv_path=ENV_FILE, override=True)

# ================================================================
# CONFIG
# ================================================================
BASE_DIR = Path(r"runs\stability_test\rounds\round_4")
EXECUTION_MODE = "batch"  # "batch" uses OpenAI Batch API; "responses" uses direct Responses API for faster iteration/debugging.
RESPONSES_ASYNC_ENABLED = True  # Only applies when EXECUTION_MODE="responses"; when True, folders within each step run concurrently.
UPLOAD_ALL_FILES_IN_ONE_BATCH = True
TARGET_CASES = None
TARGET_BATCHES = None  # Process every batch under the source round.
STABILITY_ROUNDS = 1
STABILITY_START_ROUND = 5
STABILITY_RESUME = False  # Skip a round when its output folder already exists.
STABILITY_OUTPUT_ROOT = Path(r"runs\stability_test\rounds")

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
USE_FEW_SHOT = False
FEW_SHOT_PATTERN_FILES_BY_STEP = {}
ACTIVE_STEP_KEYS = (
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
        target_batches=TARGET_BATCHES,
    )

    print("Done.")
    winsound.Beep(1000, 500)
