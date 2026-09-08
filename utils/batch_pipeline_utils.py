from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
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
    few_shot_pattern_files_by_step: dict[str, tuple[Path, ...]] | None = None
    target_folders: tuple[Path, ...] | None = None
    target_cases: tuple[str, ...] | None = None
    batch_workdir: Path | None = None
    active_step_keys: tuple[str, ...] | None = None
    source_folder_map: dict[Path, Path] | None = None
    remove_shortcut_edges: bool = True
    responses_async_enabled: bool = False
    responses_max_concurrency: int = 10
    stop_on_step_failure: bool = False
    enable_local_postprocess: bool = True
    structured_output_schemas: dict[str, dict[str, object]] | None = None


def build_few_shot_cases_by_step(
    few_shot_cases: tuple[Path, ...],
) -> dict[str, tuple[Path, ...]]:
    if not few_shot_cases:
        return {}
    return {
        step_key: tuple(few_shot_cases)
        for step_key in (
            "identify_hazard_consequence",
            "scenario_candidate_extraction",
            "scenario_structure_validation",
            "identify_accident_scenario",
            "edge_candidate_extraction",
            "edge_structure_validation",
            "causal_edge_linking",
            "graph_diagnosis",
            "graph_revision_planning",
        )
    }


def iter_target_batch_dirs(base_dir: Path) -> list[Path]:
    """Return target run dirs based on the current BASE_DIR contents.

    Preference order:
    1. child ``batch*`` directories
    2. child ``round_<n>`` directories
    3. the base directory itself
    """
    child_batch_dirs = sorted(
        path
        for path in base_dir.iterdir()
        if path.is_dir()
        and path.name.startswith("batch")
        and not path.name.endswith("_reruns")
        and path.name != "results"
    )
    if child_batch_dirs:
        return child_batch_dirs

    child_round_dirs = sorted(
        path
        for path in base_dir.iterdir()
        if path.is_dir()
        and re.fullmatch(r"round_\d+", path.name.lower())
    )
    return child_round_dirs or [base_dir]


def filter_case_folders(
    folders: tuple[Path, ...],
    target_cases: tuple[str, ...] | None,
) -> tuple[Path, ...]:
    if not target_cases:
        return folders
    allowed = {case_name.strip() for case_name in target_cases if case_name.strip()}
    filtered = []
    for folder in folders:
        folder_name = folder.name
        normalized_name = folder_name
        if "_output_round_" in folder_name:
            normalized_name = folder_name.split("_output_round_", 1)[0]
        if folder_name in allowed or normalized_name in allowed:
            filtered.append(folder)
    return tuple(filtered)


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
    """Discover case folders under one batch directory.

    Supports up to two levels of nesting so that BASE_DIR can point at a
    parent directory (e.g. rounds/) containing round_N/batch_N/case trees.
    """
    if is_case_folder(batch_dir):
        return (batch_dir,)

    children = sorted(
        f for f in batch_dir.iterdir()
        if f.is_dir() and not f.name.startswith("_")
    )

    # If any immediate child is a case folder return them directly
    case_children = tuple(c for c in children if is_case_folder(c))
    if case_children:
        return case_children

    # No case folders at first level — try one level deeper
    deeper = tuple(
        grandchild
        for child in children
        for grandchild in sorted(
            f for f in child.iterdir()
            if f.is_dir() and not f.name.startswith("_")
        )
        if is_case_folder(grandchild)
    )
    return deeper if deeper else tuple(children)


def prepare_round_output_dirs(
    *,
    source_batch_dir: Path,
    target_batch_dir: Path,
    target_cases: tuple[str, ...] | None,
    excluded_filenames: set[str] | None = None,
) -> dict[Path, Path]:
    """Prepare empty round output folders and return output->source case folder mapping."""
    if target_batch_dir.exists():
        shutil.rmtree(target_batch_dir)
    target_batch_dir.mkdir(parents=True, exist_ok=True)

    folder_map: dict[Path, Path] = {}
    source_case_dirs = filter_case_folders(discover_case_folders(source_batch_dir), target_cases)

    if is_case_folder(source_batch_dir):
        copy_case_seed_files(
            source_case_dir=source_batch_dir,
            target_case_dir=target_batch_dir,
            excluded_filenames=excluded_filenames,
        )
        folder_map[target_batch_dir] = source_batch_dir
        return folder_map

    for source_case_dir in source_case_dirs:
        output_case_dir = target_batch_dir / source_case_dir.name
        copy_case_seed_files(
            source_case_dir=source_case_dir,
            target_case_dir=output_case_dir,
            excluded_filenames=excluded_filenames,
        )
        folder_map[output_case_dir] = source_case_dir
    return folder_map


def copy_case_seed_files(
    *,
    source_case_dir: Path,
    target_case_dir: Path,
    excluded_filenames: set[str] | None = None,
) -> None:
    """Copy stable seed files needed to rerun a case into a fresh output folder."""
    excluded = set(excluded_filenames or ())
    excluded.update(
        {
            "updated_causal_graph_accept_all.json",
            "updated_causal_graph_accept_all.html",
            "updated_causal_graph_review_state_accept_all.json",
        }
    )
    target_case_dir.mkdir(parents=True, exist_ok=True)

    for path in source_case_dir.iterdir():
        if path.is_dir():
            continue
        if path.name in excluded:
            continue
        if path.name.endswith("_error.txt"):
            continue
        # DOCX report attachments are not prompt inputs and may be cloud-only
        # placeholders on synced Windows drives. Copying them can fail with
        # OSError 22 and abort round preparation unnecessarily.
        if path.suffix.lower() not in {".json", ".txt", ".md", ".html"}:
            continue
        shutil.copy2(path, target_case_dir / path.name)
