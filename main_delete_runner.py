from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import winsound

from dotenv import load_dotenv

from pipeline import run_batch_pipeline


load_dotenv(dotenv_path=Path(__file__).with_name(".env_openai"), override=True)


BASE_DIR = Path(r"runs\batch_api_test\batch_1")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEME_DIR = PROJECT_ROOT / "scheme"
MODEL_NAME = "gpt-5.4-2026-03-05"
REASONING_EFFORT = "high"
VERBOSITY = "medium"
FORCE_JSON_OUTPUT = True
SAVE_RAW_RESPONSE = True
MAX_OUTPUT_TOKENS = 128000
CALL_SLEEP_SECONDS = 0.0
HAZARDS_JSON_PATH = Path("prompt/hazards_consequence.json")
CONDITIONS_JSON_PATH = Path("prompt/conditions.json")
# TEMPERATURE = 0 # only for extract event

@dataclass(frozen=True)
class PipelineConfig:
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
    run_batch_pipeline(config)
    print("Done.")
    winsound.Beep(1000, 500)
