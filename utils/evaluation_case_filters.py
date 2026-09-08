from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EXCLUDED_CASES_PATH = (
    PROJECT_ROOT / "evaluation_excluded_few_shot_cases.json"
)


def normalize_case_key(value: str) -> str:
    """Normalize a batch/case key for stable comparison across platforms."""
    normalized = str(value or "").strip().replace("\\", "/").strip("/")
    parts = [part.strip() for part in normalized.split("/") if part.strip()]
    if len(parts) != 2:
        raise ValueError(f"Excluded case key must use batch/case format: {value!r}")
    batch_id = re.sub(r"_output_round_\d+$", "", parts[0], flags=re.IGNORECASE)
    return f"{batch_id.lower()}/{parts[1].lower()}"


def load_excluded_case_keys(path: Path | None) -> set[str]:
    """Load normalized excluded case keys from a JSON list or object."""
    if path is None:
        return set()
    resolved_path = path.resolve()
    if not resolved_path.exists():
        raise FileNotFoundError(f"Excluded-case list does not exist: {resolved_path}")
    payload: Any = json.loads(resolved_path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        raw_cases = payload.get("excluded_cases")
    else:
        raw_cases = payload
    if not isinstance(raw_cases, list):
        raise ValueError(
            f"Excluded-case list must be a JSON list or contain 'excluded_cases': {resolved_path}"
        )
    normalized = {normalize_case_key(str(value)) for value in raw_cases}
    if len(normalized) != len(raw_cases):
        raise ValueError(f"Excluded-case list contains duplicate entries: {resolved_path}")
    return normalized


def infer_case_key(case_folder: Path, parent_dir: Path) -> str:
    """Infer a normalized batch/case key from a discovered case folder."""
    try:
        relative_parts = case_folder.resolve().relative_to(parent_dir.resolve()).parts
    except ValueError:
        relative_parts = case_folder.parts
    batch_part = next(
        (part for part in reversed(relative_parts[:-1]) if part.lower().startswith("batch_")),
        None,
    )
    if batch_part is None and case_folder.parent.name.lower().startswith("batch_"):
        batch_part = case_folder.parent.name
    if batch_part is None:
        raise ValueError(f"Cannot infer batch ID for case folder: {case_folder}")
    return normalize_case_key(f"{batch_part}/{case_folder.name}")


def filter_excluded_case_folders(
    case_folders: Iterable[Path],
    parent_dir: Path,
    excluded_case_keys: set[str],
) -> tuple[list[Path], list[tuple[str, Path]]]:
    """Return retained folders and excluded key/folder pairs."""
    retained: list[Path] = []
    excluded: list[tuple[str, Path]] = []
    for case_folder in case_folders:
        case_key = infer_case_key(case_folder, parent_dir)
        if case_key in excluded_case_keys:
            excluded.append((case_key, case_folder))
        else:
            retained.append(case_folder)
    return retained, excluded


def write_exclusion_audit(
    output_dir: Path,
    exclusion_path: Path | None,
    excluded_case_keys: set[str],
    excluded_folders: Iterable[tuple[str, Path]],
) -> Path:
    """Write the configured and matched exclusions beside evaluation outputs."""
    matched = [
        {"case_key": case_key, "case_folder": str(case_folder.resolve())}
        for case_key, case_folder in excluded_folders
    ]
    payload = {
        "exclusion_enabled": exclusion_path is not None,
        "exclusion_list_path": str(exclusion_path.resolve()) if exclusion_path else None,
        "configured_case_count": len(excluded_case_keys),
        "configured_cases": sorted(excluded_case_keys),
        "excluded_folder_count": len(matched),
        "excluded_folders": matched,
    }
    audit_path = output_dir / "evaluation_case_exclusions.json"
    audit_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return audit_path
