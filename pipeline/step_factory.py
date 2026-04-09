from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List

from pipeline.step_var_resolver import get_active_step_keys, get_step_var_builder
from pipeline.step_registry import STEP_REGISTRY


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _build_step(key: str, build_vars: Callable[[Path], Dict[str, Any]]) -> "Step":
    config = STEP_REGISTRY[key]
    defaults = config.get("default_params", {})
    return Step(
        key=key,
        output_filename=config["output_file"],
        build_vars=build_vars,
        enabled=defaults.get("enabled", True),
        reasoning_effort=defaults.get("reasoning_effort"),
        temperature=defaults.get("temperature"),
        verbosity=defaults.get("verbosity"),
    )


@dataclass
class Step:
    key: str
    output_filename: str
    build_vars: Callable[[Path], Dict[str, Any]]
    enabled: bool = True
    reasoning_effort: str | None = None
    temperature: float | None = None
    verbosity: str | None = None

    def output_path(self, folder: Path) -> Path:
        return folder / self.output_filename


def build_pipeline(
    hazards_json: Path,
    conditions_json: Path,
    *,
    use_few_shot: bool = False,
    few_shot_cases_by_step: dict[str, tuple[Path, ...]] | None = None,
    active_step_keys: tuple[str, ...] | None = None,
) -> List[Step]:
    steps: List[Step] = []
    if active_step_keys is None:
        raise ValueError("active_step_keys must be provided by the entrypoint config.")
    for key in get_active_step_keys(active_step_keys):
        steps.append(
            _build_step(
                key=key,
                build_vars=get_step_var_builder(
                    key=key,
                    hazards_json=hazards_json,
                    conditions_json=conditions_json,
                    project_root=PROJECT_ROOT,
                    use_few_shot=use_few_shot,
                    few_shot_cases=(few_shot_cases_by_step or {}).get(key, ()),
                ),
            )
        )

    return steps


def build_update_chain_vars(folder: Path) -> Dict[str, Any]:
    combined_text = "\n\n".join(
        (folder / filename).read_text(encoding="utf-8")
        for filename in [
            "chain_scenario_output.txt",
            "chain_hazards_output.txt",
            "chain_conditions_events_output.txt",
        ]
    )

    delete_report_path = folder / "delete_repetitive_events_output.txt"
    delete_report = (
        delete_report_path.read_text(encoding="utf-8")
        if delete_report_path.exists()
        else ""
    )

    print(f"[DEBUG] combined_text length = {len(combined_text)}")
    print(f"[DEBUG] delete_report length = {len(delete_report)}")

    return {
        "combined_text": combined_text,
        "delete_repetitive_events_output": delete_report,
    }
