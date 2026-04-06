from pathlib import Path
from batch_main_runner import HAZARDS_JSON_PATH, CONDITIONS_JSON_PATH, MAX_OUTPUT_TOKENS
from utils.prompt_opt_runner import PromptOptimizationConfig, run_prompt_optimization


SOURCE_RUNS = Path(r"runs\temproal_result_4_without_few_shot")
TARGET_BATCH = "batch_4"
TARGET_CASE = "1"


TARGET_STEPS = ("identify_accident_scenario", "causal_edge_linking")

DSPY_MODEL = "gpt-5.4-2026-03-05"
REASONING_EFFORT = "high"
VERBOSITY = "medium"

PROMPT_OUTPUT_DIR = Path("runs") / "optimization_runs"
EXPERIMENT_NAME = "batch4_case1_opt"
MAX_ROUNDS = 15
TOP_K = 3
ANALYSIS_WINDOW_SIZE = 3
ANALYSIS_ROUNDS = (1, 2, 3)
RESUME_FROM_EXISTING = True


if __name__ == "__main__":
    config = PromptOptimizationConfig(
        source_runs=SOURCE_RUNS,
        target_batch=TARGET_BATCH,
        target_case=TARGET_CASE,
        target_steps=TARGET_STEPS,
        dspy_model=DSPY_MODEL,
        reasoning_effort=REASONING_EFFORT,
        verbosity=VERBOSITY,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        hazards_json_path=HAZARDS_JSON_PATH,
        conditions_json_path=CONDITIONS_JSON_PATH,
        prompt_output_dir=PROMPT_OUTPUT_DIR,
        experiment_name=EXPERIMENT_NAME,
        max_rounds=MAX_ROUNDS,
        top_k=TOP_K,
        analysis_window_size=ANALYSIS_WINDOW_SIZE,
        analysis_rounds=ANALYSIS_ROUNDS,
        resume_from_existing=RESUME_FROM_EXISTING,
    )
    run_prompt_optimization(config)
