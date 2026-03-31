from __future__ import annotations

import argparse
import csv
import shutil
from pathlib import Path
from typing import Iterable, List


KEEP_FILE_NAME = "identify_name.txt"
TEMP_PREFIX = "__tmp_case__"
METADATA_COLUMNS = [
    "new_id",
    "original_folder_name",
    "batch_id",
    "pdf_file_name",
]


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for cleanup and metadata generation."""
    parser = argparse.ArgumentParser(
        description=(
            "Keep only PDFs and identify_name.txt in each case folder under "
            "runs/batched_reports/batch_*, rename case folders to numbers within "
            "each batch, and generate metadata CSV files."
        )
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("runs/batched_reports"),
        help="Root directory containing batch_* folders. Defaults to runs/batched_reports.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply deletions and renames. Without this flag, the script only prints a preview.",
    )
    return parser.parse_args()


def batch_sort_key(path: Path) -> tuple[int, str]:
    """Sort batch folders by numeric suffix when available."""
    try:
        return (int(path.name.split("_")[-1]), path.name)
    except ValueError:
        return (10**9, path.name)


def is_kept_file(path: Path) -> bool:
    """Return True when a file should be retained."""
    return path.suffix.lower() == ".pdf" or path.name == KEEP_FILE_NAME


def find_batch_dirs(root: Path) -> List[Path]:
    """Collect batch directories directly under the root."""
    return sorted(
        [path for path in root.iterdir() if path.is_dir() and path.name.startswith("batch_")],
        key=batch_sort_key,
    )


def find_case_dirs(batch_dir: Path) -> List[Path]:
    """Collect case directories directly under a batch directory."""
    return sorted([path for path in batch_dir.iterdir() if path.is_dir()])


def collect_files_to_delete(case_dir: Path) -> List[Path]:
    """Collect all files that are not PDFs or identify_name.txt."""
    files_to_delete: List[Path] = []
    for path in case_dir.rglob("*"):
        if path.is_file() and not is_kept_file(path):
            files_to_delete.append(path)
    return sorted(files_to_delete)


def collect_empty_dirs(case_dir: Path) -> List[Path]:
    """Collect empty directories bottom-up after file cleanup."""
    empty_dirs: List[Path] = []
    for path in sorted([p for p in case_dir.rglob("*") if p.is_dir()], key=lambda p: len(p.parts), reverse=True):
        try:
            if not any(path.iterdir()):
                empty_dirs.append(path)
        except FileNotFoundError:
            continue
    return empty_dirs


def collect_pdf_names(case_dir: Path) -> str:
    """Collect relative PDF file names for metadata."""
    pdf_paths = sorted(path for path in case_dir.rglob("*.pdf") if path.is_file())
    return " | ".join(str(path.relative_to(case_dir)) for path in pdf_paths)


def write_csv(path: Path, rows: Iterable[dict[str, str]]) -> None:
    """Write metadata rows to CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=METADATA_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def remove_path(path: Path) -> None:
    """Remove a file or directory."""
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def main() -> None:
    """Preview or apply cleanup, renaming, and metadata generation."""
    args = parse_args()
    root = args.root.resolve()
    batch_dirs = find_batch_dirs(root)

    all_rows: List[dict[str, str]] = []

    if not batch_dirs:
        print(f"No batch_* folders found under {root}")
        return

    for batch_dir in batch_dirs:
        case_dirs = find_case_dirs(batch_dir)
        batch_rows: List[dict[str, str]] = []

        print(f"\n[{batch_dir.name}] Found {len(case_dirs)} case folder(s).")

        rename_plan: List[tuple[Path, Path, Path]] = []
        delete_files_plan: List[Path] = []
        delete_dirs_plan: List[Path] = []

        for index, case_dir in enumerate(case_dirs, start=1):
            new_id = str(index)
            temp_dir = batch_dir / f"{TEMP_PREFIX}{new_id}"
            final_dir = batch_dir / new_id

            files_to_delete = collect_files_to_delete(case_dir)
            delete_files_plan.extend(files_to_delete)

            pdf_file_name = collect_pdf_names(case_dir)
            batch_rows.append(
                {
                    "new_id": new_id,
                    "original_folder_name": case_dir.name,
                    "batch_id": batch_dir.name,
                    "pdf_file_name": pdf_file_name,
                }
            )
            rename_plan.append((case_dir, temp_dir, final_dir))

            print(f"  {case_dir.name} -> {new_id}")
            if files_to_delete:
                print(f"    delete files: {len(files_to_delete)}")

        if args.apply:
            for file_path in delete_files_plan:
                remove_path(file_path)

            for original_dir, _, _ in rename_plan:
                delete_dirs_plan.extend(collect_empty_dirs(original_dir))

            for empty_dir in delete_dirs_plan:
                remove_path(empty_dir)

            for original_dir, temp_dir, _ in rename_plan:
                if temp_dir.exists():
                    raise FileExistsError(f"Temporary path already exists: {temp_dir}")
                original_dir.rename(temp_dir)

            for _, temp_dir, final_dir in rename_plan:
                if final_dir.exists():
                    raise FileExistsError(f"Final path already exists: {final_dir}")
                temp_dir.rename(final_dir)

            write_csv(batch_dir / "metadata.csv", batch_rows)

        all_rows.extend(batch_rows)

    if args.apply:
        write_csv(root / "metadata_all.csv", all_rows)
        print(f"\nApplied changes under {root}")
        print(f"Saved per-batch metadata.csv files and {root / 'metadata_all.csv'}")
    else:
        print("\nDry run only. Re-run with --apply to make changes.")


if __name__ == "__main__":
    main()
