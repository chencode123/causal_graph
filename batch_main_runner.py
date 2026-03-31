from __future__ import annotations
"""
Batch pipeline entrypoint for running the process-safety extraction workflow.

This script supports two execution scopes:
1. Single-batch mode:
   Run the pipeline only for `BASE_DIR`.
2. Multi-batch mode:
   Discover sibling `batch_*` directories and run them all.

It also supports two upload strategies when multi-batch mode is enabled:
1. Per-batch submission:
   Submit one OpenAI Batch job per discovered batch directory.
2. Combined submission:
   Merge all discovered case folders into one large OpenAI Batch job per
   pipeline step, while still writing outputs back to the original case
   folders.

Recommended usage:
- Use `PROCESS_ALL_BATCHES = False` for targeted reruns or debugging.
- Use `PROCESS_ALL_BATCHES = True` for full production-style processing.
- Use `UPLOAD_ALL_FILES_IN_ONE_BATCH = True` only when you explicitly want
  to maximize request consolidation across multiple batch directories.
"""

from dataclasses import dataclass, replace
from pathlib import Path
import winsound

from dotenv import load_dotenv

from pipeline.batch_runner import run_batch_pipeline


load_dotenv(dotenv_path=Path(__file__).with_name(".env_openai"), override=True)

# ================================================================
# CONFIG
# ================================================================

BASE_DIR = Path(r"runs\batch_api_test_1\batch_13")  # Used when PROCESS_ALL_BATCHES = False.
PROCESS_ALL_BATCHES = False  # True: discover all sibling batch_* directories under BASE_DIR.parent.
UPLOAD_ALL_FILES_IN_ONE_BATCH = False  # Only meaningful when PROCESS_ALL_BATCHES = True; merge all discovered case folders into one large batch job per step.
MODEL_NAME = "gpt-5.4-2026-03-05"
REASONING_EFFORT = "high"
VERBOSITY = "medium"
FORCE_JSON_OUTPUT = True
SAVE_RAW_RESPONSE = True
MAX_OUTPUT_TOKENS = 128000
CALL_SLEEP_SECONDS = 0.0
HAZARDS_JSON_PATH = Path("prompt/hazards_consequence.json")
CONDITIONS_JSON_PATH = Path("prompt/conditions.json")


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
    target_folders: tuple[Path, ...] | None = None
    batch_workdir: Path | None = None


def iter_target_batch_dirs(base_dir: Path, process_all_batches: bool) -> list[Path]:
    """Return the batch directories to execute based on the current mode."""
    if not process_all_batches:
        return [base_dir]

    batch_dirs = sorted(
        path
        for path in base_dir.parent.iterdir()
        if path.is_dir() and path.name.startswith("batch_")
    )
    return batch_dirs or [base_dir]


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
    )

    target_batch_dirs = iter_target_batch_dirs(BASE_DIR, PROCESS_ALL_BATCHES)
    if UPLOAD_ALL_FILES_IN_ONE_BATCH and len(target_batch_dirs) > 1:
        target_folders = tuple(
            folder
            for batch_dir in target_batch_dirs
            for folder in sorted(batch_dir.iterdir())
            if folder.is_dir() and not folder.name.startswith("_")
        )
        combined_base_dir = BASE_DIR.parent
        combined_workdir = combined_base_dir / "_batch_pipeline_all"
        print(f"Running one combined batch pipeline for: {combined_base_dir}")
        print(f"Combined folders: {len(target_folders)}")
        run_batch_pipeline(
            replace(
                config,
                base_dir=combined_base_dir,
                target_folders=target_folders,
                batch_workdir=combined_workdir,
            )
        )
    else:
        for batch_dir in target_batch_dirs:
            print(f"Running batch pipeline for: {batch_dir}")
            run_batch_pipeline(replace(config, base_dir=batch_dir))

    print("Done.")
    winsound.Beep(1000, 500)
