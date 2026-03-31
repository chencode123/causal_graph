from __future__ import annotations

"""
Check batch case folders for the expected file layout.

Expected per-case layout:
- exactly one PDF file
- exactly one `identify_incident_output.json`

The script scans one batch folder or all sibling `batch_*` folders and reports
case folders that do not match the expected structure.
"""

import json
from pathlib import Path


BATCH_FOLDER = Path(r"runs\batched_reports\batch_1")  # Used when PROCESS_ALL_BATCHES = False.
PROCESS_ALL_BATCHES = True  # True: scan all sibling batch_* directories under BATCH_FOLDER.parent.
OUTPUT_REPORT_PATH = Path("runs/batched_reports/layout_check_report.json")


def iter_target_batch_folders(batch_folder: Path, process_all_batches: bool) -> list[Path]:
    if not process_all_batches:
        return [batch_folder]

    batch_folders = sorted(
        path
        for path in batch_folder.parent.iterdir()
        if path.is_dir() and path.name.startswith("batch_")
    )
    return batch_folders or [batch_folder]


def inspect_case_folder(case_folder: Path) -> dict[str, object] | None:
    pdf_files = sorted(case_folder.glob("*.pdf"))
    json_files = sorted(case_folder.glob("identify_incident_output.json"))

    if len(pdf_files) == 1 and len(json_files) == 1:
        return None

    return {
        "batch_id": case_folder.parent.name,
        "case_id": case_folder.name,
        "pdf_count": len(pdf_files),
        "json_count": len(json_files),
        "pdf_files": [path.name for path in pdf_files],
        "json_files": [path.name for path in json_files],
        "all_files": sorted(path.name for path in case_folder.iterdir() if path.is_file()),
    }


def write_report(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    target_batch_folders = iter_target_batch_folders(BATCH_FOLDER, PROCESS_ALL_BATCHES)
    invalid_rows: list[dict[str, object]] = []
    checked_cases = 0

    for batch_folder in target_batch_folders:
        case_folders = [
            child
            for child in sorted(batch_folder.iterdir(), key=lambda p: p.name)
            if child.is_dir() and not child.name.startswith("_")
        ]
        for case_folder in case_folders:
            checked_cases += 1
            row = inspect_case_folder(case_folder)
            if row is not None:
                invalid_rows.append(row)

    write_report(OUTPUT_REPORT_PATH, invalid_rows)

    print(f"Checked case folders: {checked_cases}")
    print(f"Invalid case folders: {len(invalid_rows)}")
    print(f"Report saved to: {OUTPUT_REPORT_PATH}")

    for row in invalid_rows:
        print(
            f"[{row['batch_id']}/{row['case_id']}] "
            f"pdf_count={row['pdf_count']}, json_count={row['json_count']}"
        )


if __name__ == "__main__":
    main()
