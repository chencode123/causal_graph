"""Read-only checks for the public five-run main-method entry points."""

from pathlib import Path
import json

from pipeline.io_utils import render_prompt
from pipeline.step_factory import build_pipeline
from pipeline.step_registry import STEP_REGISTRY
from utils.batch_pipeline_utils import (
    PipelineConfig, discover_case_folders, filter_case_folders, iter_target_batch_dirs,
)
from utils.prompt_manager import prompts


def preflight(config: PipelineConfig, *, output_root: Path, rounds: int,
              start_round: int, resume: bool,
              target_batches: tuple[str, ...] | None = None) -> int:
    """Validate prepared inputs and refuse incomplete or replaceable output rounds.

    This checks artifact availability and JSON syntax, not scientific validity or
    historical prompt equivalence. It neither writes files nor calls a model.
    """
    source = config.base_dir.resolve()
    output = output_root.resolve()
    if source == output or source in output.parents or output in source.parents:
        raise ValueError("Source and output trees must be separate.")
    if rounds < 1 or start_round < 1:
        raise ValueError("Round count and starting round must be positive.")
    batches = iter_target_batch_dirs(source)
    if target_batches:
        missing = set(target_batches) - {p.name for p in batches}
        if missing:
            raise ValueError(f"Unknown target batches: {sorted(missing)}")
        batches = [p for p in batches if p.name in target_batches]
    cases = tuple(p for batch in batches for p in
                  filter_case_folders(discover_case_folders(batch), config.target_cases))
    if not cases:
        raise ValueError(f"No prepared cases found under {source}")
    steps = build_pipeline(
        config.hazards_json_path, config.conditions_json_path,
        use_few_shot=config.use_few_shot,
        few_shot_pattern_files_by_step=config.few_shot_pattern_files_by_step,
        active_step_keys=config.active_step_keys,
    )
    for paths in (config.few_shot_pattern_files_by_step or {}).values():
        for path in paths:
            json.loads(path.read_text(encoding="utf-8"))
    for case in cases:
        for name in ("identify_incident_output.json", "identify_hazard_consequence_output.json"):
            path = case / name
            if not path.is_file():
                raise FileNotFoundError(
                    f"Missing prepared input: {path}. Supply the fixed incident and hazard "
                    "identification JSON files or select a prepared tree with --source-dir."
                )
            json.loads(path.read_text(encoding="utf-8"))
        first = steps[0]
        render_prompt(prompts[first.key].read_text(encoding="utf-8"), first.build_vars(case))
    required = [STEP_REGISTRY[key]["output_file"] for key in config.active_step_keys]
    required += ["causal_graph.json", "updated_causal_graph_accept_all.json"]
    for index in range(start_round, start_round + rounds):
        destination = output / f"round_{index}"
        if not destination.exists():
            continue
        if not resume:
            raise FileExistsError(f"Refusing to overwrite {destination}; use a new output root.")
        for case in cases:
            # Match the existing stability preparer's single-case/batch layout.
            relative = (Path() if len(cases) == 1 else
                        Path(case.name) if len(batches) == 1 and batches[0] == source else
                        Path(case.parent.name) / case.name)
            for name in required:
                path = destination / relative / name
                if not path.is_file():
                    raise ValueError(f"Existing round is incomplete: {path}. "
                                     "Use a separate output root or repair it explicitly.")
                json.loads(path.read_text(encoding="utf-8"))
    print(f"Preflight passed: {len(cases)} prepared cases, {rounds} rounds, "
          f"few_shot={config.use_few_shot}. Existing complete rounds will be skipped.")
    return len(cases)
