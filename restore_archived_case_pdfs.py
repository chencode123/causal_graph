from __future__ import annotations

"""
Restore archived case files back into active batch folders when postprocessing moved
the original case directory to `_postprocess_archive`, but later repair scripts recreated
an active case folder containing only `identify_incident_output.json`.

Behavior:
1. Scan one batch folder or all sibling `batch_*` folders.
2. Look for matching archived case folders under `_postprocess_archive/<batch_name>/...`.
3. Copy archived files back into the active case folder when missing.

This is intended to restore the old per-case layout:
- one PDF
- one identify_incident_output.json
"""

import shutil
from pathlib import Path


BATCH_FOLDER = Path(r"runs\batched_reports\batch_8")  # Used when PROCESS_ALL_BATCHES = False.
PROCESS_ALL_BATCHES = True  # True: scan all sibling batch_* directories under BATCH_FOLDER.parent.
COPY_JSON_BACK = False  # True: also copy archived JSON back when the active folder is missing it.


def iter_target_batch_folders(batch_folder: Path, process_all_batches: bool) -> list[Path]:
    if not process_all_batches:
        return [batch_folder]

    batch_folders = sorted(
        path
        for path in batch_folder.parent.iterdir()
        if path.is_dir() and path.name.startswith("batch_")
    )
    return batch_folders or [batch_folder]


def find_archived_case_folder(batch_folder: Path, case_name: str) -> Path | None:
    archive_root = batch_folder.parent / "_postprocess_archive" / batch_folder.name
    if not archive_root.exists():
        return None

    matches = [
        path
        for path in archive_root.rglob(case_name)
        if path.is_dir() and path.name == case_name
    ]
    if not matches:
        return None
    if len(matches) > 1:
        # Prefer the shortest path depth when multiple archives exist.
        matches.sort(key=lambda path: len(path.parts))
    return matches[0]


def restore_case_folder(batch_folder: Path, case_folder: Path) -> tuple[int, int]:
    archived_case_folder = find_archived_case_folder(batch_folder, case_folder.name)
    if archived_case_folder is None:
        return (0, 0)

    copied = 0
    skipped = 0
    case_folder.mkdir(parents=True, exist_ok=True)

    for archived_file in archived_case_folder.iterdir():
        if not archived_file.is_file():
            continue
        if archived_file.name == "identify_incident_output.json" and not COPY_JSON_BACK:
            skipped += 1
            continue

        target_file = case_folder / archived_file.name
        if target_file.exists():
            skipped += 1
            continue

        shutil.copy2(archived_file, target_file)
        copied += 1

    return (copied, skipped)


def main() -> None:
    total_copied = 0
    total_skipped = 0
    total_cases = 0

    for batch_folder in iter_target_batch_folders(BATCH_FOLDER, PROCESS_ALL_BATCHES):
        case_folders = [
            child
            for child in sorted(batch_folder.iterdir(), key=lambda p: p.name)
            if child.is_dir() and not child.name.startswith("_")
        ]
        batch_copied = 0
        batch_skipped = 0
        batch_cases = 0

        for case_folder in case_folders:
            copied, skipped = restore_case_folder(batch_folder, case_folder)
            if copied or skipped:
                total_cases += 1
                batch_cases += 1
                batch_copied += copied
                batch_skipped += skipped

        print(
            f"[{batch_folder.name}] restored_cases={batch_cases} copied_files={batch_copied} skipped_files={batch_skipped}"
        )
        total_copied += batch_copied
        total_skipped += batch_skipped

    print(f"Done. restored_cases={total_cases}, copied_files={total_copied}, skipped_files={total_skipped}")


if __name__ == "__main__":
    main()
