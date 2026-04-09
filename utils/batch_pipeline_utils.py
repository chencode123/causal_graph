from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil


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
    active_step_keys: tuple[str, ...] | None = None


def build_few_shot_cases_by_step(
    few_shot_cases: tuple[Path, ...],
) -> dict[str, tuple[Path, ...]]:
    if not few_shot_cases:
        return {}
    return {
        step_key: tuple(few_shot_cases)
        for step_key in (
            "identify_hazard_consequence",
            "causal_narrative_extraction",
            "identify_accident_scenario",
            "causal_edge_linking",
            "graph_diagnosis",
            "graph_revision_planning",
        )
    }


def iter_target_batch_dirs(base_dir: Path) -> list[Path]:
    """Return target batch dirs based on the current BASE_DIR contents."""
    child_batch_dirs = sorted(
        path for path in base_dir.iterdir() if path.is_dir() and path.name.startswith("batch_")
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
    """Treat a directory as a case folder when core case artifacts exist."""
    marker_files = (
        "identify_incident_output.json",
        "identify_hazard_consequence_output.json",
        "identify_accident_scenario_output.json",
        "causal_edge_linking_output.json",
        "causal_graph.json",
        "review_causal_graph_output.json",
        "graph_diagnosis_output.json",
        "graph_revision_planning_output.json",
    )
    return any((folder / marker).exists() for marker in marker_files)


def discover_case_folders(batch_dir: Path) -> tuple[Path, ...]:
    """Discover case folders under one batch directory."""
    if is_case_folder(batch_dir):
        return (batch_dir,)
    return tuple(
        folder
        for folder in sorted(batch_dir.iterdir())
        if folder.is_dir() and not folder.name.startswith("_")
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
