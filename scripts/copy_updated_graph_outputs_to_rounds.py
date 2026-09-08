#!/usr/bin/env python3
"""
Copy repaired updated graph outputs from one round to matching case folders in
other rounds.

Default behavior is dry-run. Edit the hyperparameters below, or pass command-line
arguments to override them.
"""

from __future__ import annotations

import argparse
import shutil
from dataclasses import dataclass
from pathlib import Path


# ============================================================
# Editable defaults for direct runs with no command-line args.
# Command-line args still take priority when provided.
# ============================================================
SOURCE_ROUND = r"runs\stability_test\rounds\round_1"
TARGET_ROUNDS = [
    # r"runs\stability_test\rounds\round_2",
    # r"runs\stability_test\rounds\round_3",
    r"runs\stability_test\rounds_with_few_shot\round_1",
    r"runs\stability_test\rounds_with_few_shot\round_2",
    r"runs\stability_test\rounds_with_few_shot\round_3",
]
FILE_NAMES = [
    "updated_causal_graph.html",
    "updated_causal_graph_review_state.json",
]
DRY_RUN = False
BACKUP = True
CREATE_MISSING_DIRS = False


@dataclass
class CopyItem:
    source: Path
    target: Path
    status: str
    message: str = ""


def find_source_case_dirs(source_round: Path) -> list[Path]:
    found = set()
    for file_name in FILE_NAMES:
        found.update(path.parent for path in source_round.rglob(file_name) if path.is_file())
    return sorted(found)


def backup_target(target: Path) -> Path:
    backup = target.with_suffix(target.suffix + ".bak")
    if not backup.exists():
        shutil.copy2(target, backup)
        return backup

    index = 1
    while True:
        candidate = target.with_suffix(target.suffix + f".bak{index}")
        if not candidate.exists():
            shutil.copy2(target, candidate)
            return candidate
        index += 1


def plan_copy(
    source_round: Path,
    target_rounds: list[Path],
    file_names: list[str],
    create_missing_dirs: bool,
) -> list[CopyItem]:
    items: list[CopyItem] = []
    case_dirs = find_source_case_dirs(source_round)

    for case_dir in case_dirs:
        relative_case_dir = case_dir.relative_to(source_round)
        for file_name in file_names:
            source = case_dir / file_name
            if not source.exists():
                continue
            for target_round in target_rounds:
                target_case_dir = target_round / relative_case_dir
                target = target_case_dir / file_name
                if not target_case_dir.exists() and not create_missing_dirs:
                    items.append(CopyItem(source, target, "skip", "target case dir missing"))
                elif target.exists():
                    items.append(CopyItem(source, target, "copy", "overwrite existing"))
                else:
                    items.append(CopyItem(source, target, "copy", "create file"))
    return items


def execute_copy(items: list[CopyItem], dry_run: bool, backup: bool, create_missing_dirs: bool) -> list[CopyItem]:
    results: list[CopyItem] = []
    for item in items:
        if item.status != "copy":
            results.append(item)
            continue

        if dry_run:
            results.append(CopyItem(item.source, item.target, "would-copy", item.message))
            continue

        try:
            if not item.target.parent.exists():
                if not create_missing_dirs:
                    results.append(CopyItem(item.source, item.target, "skip", "target case dir missing"))
                    continue
                item.target.parent.mkdir(parents=True, exist_ok=True)
            if backup and item.target.exists():
                backup_path = backup_target(item.target)
                message = f"{item.message}; backup={backup_path.name}"
            else:
                message = item.message
            shutil.copy2(item.source, item.target)
            results.append(CopyItem(item.source, item.target, "copied", message))
        except Exception as exc:
            results.append(CopyItem(item.source, item.target, "failed", str(exc)))

    return results


def format_item(item: CopyItem, source_round: Path) -> str:
    try:
        source_rel = item.source.relative_to(source_round)
    except ValueError:
        source_rel = item.source
    return f"{item.status:10} {source_rel} -> {item.target} | {item.message}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy updated graph HTML/review state from one round to other rounds.")
    parser.add_argument("--source-round", default=None, help="Source round directory.")
    parser.add_argument("--target-round", action="append", default=None, help="Target round directory. Can be repeated.")
    parser.add_argument("--file", action="append", default=None, help="File name to copy. Can be repeated.")
    parser.add_argument("--dry-run", action="store_true", help="Preview only.")
    parser.add_argument("--write", action="store_true", help="Actually copy files.")
    parser.add_argument("--backup", action="store_true", help="Create backups before overwriting.")
    parser.add_argument("--no-backup", action="store_true", help="Do not create backups before overwriting.")
    parser.add_argument("--create-missing-dirs", action="store_true", help="Create missing target case directories.")
    args = parser.parse_args()

    source_round = Path(args.source_round or SOURCE_ROUND)
    target_rounds = [Path(value) for value in (args.target_round or TARGET_ROUNDS)]
    file_names = args.file or FILE_NAMES

    if args.write:
        dry_run = False
    elif args.dry_run:
        dry_run = True
    else:
        dry_run = DRY_RUN

    if args.no_backup:
        backup = False
    elif args.backup:
        backup = True
    else:
        backup = BACKUP

    create_missing_dirs = args.create_missing_dirs or CREATE_MISSING_DIRS

    if not source_round.exists():
        print(f"ERROR: source round not found: {source_round}")
        return 2

    missing_targets = [target for target in target_rounds if not target.exists()]
    if missing_targets and not create_missing_dirs:
        for target in missing_targets:
            print(f"WARNING: target round not found, entries will be skipped: {target}")

    items = plan_copy(source_round, target_rounds, file_names, create_missing_dirs)
    if not items:
        print("No source files found.")
        return 1

    results = execute_copy(items, dry_run=dry_run, backup=backup, create_missing_dirs=create_missing_dirs)
    for item in results:
        print(format_item(item, source_round))

    counts = {}
    for item in results:
        counts[item.status] = counts.get(item.status, 0) + 1
    mode = "dry-run" if dry_run else "write"
    summary = ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))
    print(f"Summary ({mode}): {summary}")
    return 1 if counts.get("failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
