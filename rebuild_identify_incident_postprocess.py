from __future__ import annotations

"""
Rebuild identify-incident summaries and postprocess results from corrected outputs.

This script is intended for cases where earlier postprocessing decisions were made
from incorrectly saved `identify_incident_output.json` files.

Behavior:
1. Scan one batch folder or all sibling `batch_*` folders.
2. Rebuild `identify_incident_summary.csv` from the current active case folders.
3. Optionally delete the old `_postprocess_archive/<batch_name>` directory.
4. Re-run split/archive postprocessing using the corrected JSON outputs.
"""

import csv
import json
import re
import shutil
from pathlib import Path


BATCH_FOLDER = Path(r"runs\batched_reports\batch_1")  # Used when PROCESS_ALL_BATCHES = False.
PROCESS_ALL_BATCHES = True  # True: rebuild all sibling batch_* directories under BATCH_FOLDER.parent.
DELETE_OLD_ARCHIVE = True  # True: clear old classified archive subfolders before rebuilding, but keep archive record files.

ARCHIVE_CATEGORY_TEMPLATES = {
    "summary_only": (
        "summary_only",
        "recommendations",
        "{batch_name}_summary_only",
    ),
    "original_multi_incident": (
        "original_multi_incident",
        "{batch_name}_original_multi_incident",
    ),
    "non_full_documents": (
        "non_full_documents",
        "{batch_name}_non_full_documents",
    ),
}
ARCHIVE_RECORD_FILES = (
    "identify_incident_summary.csv",
    "identify_incident_split_mapping.csv",
    "metadata.csv",
)


SUMMARY_COLUMNS = [
    "case_id",
    "batch_id",
    "recommended_output_mode",
    "is_summary_style",
    "is_full_incident_report",
    "contains_multiple_independent_incidents",
    "requires_incident_split",
    "incident_count",
    "status",
]

SPLIT_MAPPING_COLUMNS = [
    "batch_id",
    "original_case_id",
    "split_case_id",
    "incident_id",
    "time_reference",
]


def iter_target_batch_folders(batch_folder: Path, process_all_batches: bool) -> list[Path]:
    if not process_all_batches:
        return [batch_folder]

    batch_folders = sorted(
        path
        for path in batch_folder.parent.iterdir()
        if path.is_dir() and path.name.startswith("batch_")
    )
    return batch_folders or [batch_folder]


def write_summary_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def write_split_mapping_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SPLIT_MAPPING_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def remove_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def iter_category_dirs(archive_dir: Path, batch_name: str, category: str) -> list[Path]:
    return [
        archive_dir / template.format(batch_name=batch_name)
        for template in ARCHIVE_CATEGORY_TEMPLATES[category]
    ]


def resolve_archive_dir(archive_dir: Path, batch_name: str, category: str) -> Path:
    """Reuse an existing legacy archive folder name when one is already present."""
    candidates = iter_category_dirs(archive_dir, batch_name, category)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def prepare_archive_root(archive_dir: Path) -> None:
    """Reset only classified archive subfolders while preserving archive root records."""
    archive_dir.mkdir(parents=True, exist_ok=True)
    if not DELETE_OLD_ARCHIVE:
        return

    for category in ARCHIVE_CATEGORY_TEMPLATES:
        for category_dir in iter_category_dirs(archive_dir, archive_dir.name, category):
            if category_dir.exists():
                remove_path(category_dir)


def sync_archive_record_files(batch_folder: Path) -> None:
    """Copy batch-level record files into the archive root for traceability."""
    archive_dir = batch_folder.parent / "_postprocess_archive" / batch_folder.name
    archive_dir.mkdir(parents=True, exist_ok=True)

    for filename in ARCHIVE_RECORD_FILES:
        source = batch_folder / filename
        if not source.exists():
            continue
        shutil.copy2(source, archive_dir / filename)


def copy_case_pdf(source_case_folder: Path, target_case_folder: Path) -> str:
    pdf_files = sorted(source_case_folder.glob("*.pdf"))
    if not pdf_files:
        return ""
    source_pdf = pdf_files[0]
    target_case_folder.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_pdf, target_case_folder / source_pdf.name)
    return source_pdf.name


def build_split_payload(original_data: dict, incident: dict) -> dict:
    classification = dict(original_data.get("document_classification", {}))
    classification["contains_multiple_independent_incidents"] = False
    classification["requires_incident_split"] = False
    classification["recommended_output_mode"] = "single_incident"

    return {
        "document_classification": classification,
        "incidents": [incident],
    }


def build_multi_incident_payload_from_splits(split_payloads: list[dict]) -> dict:
    """Reconstruct a multi-incident payload from existing split case outputs."""
    incidents: list[dict] = []
    base_classification: dict = {}

    for payload in split_payloads:
        if not base_classification:
            base_classification = dict(payload.get("document_classification", {}))
        incident_list = payload.get("incidents", [])
        if isinstance(incident_list, list):
            for incident in incident_list:
                if isinstance(incident, dict):
                    incidents.append(incident)

    classification = dict(base_classification)
    classification["contains_multiple_independent_incidents"] = len(incidents) > 1
    classification["requires_incident_split"] = len(incidents) > 1
    classification["recommended_output_mode"] = "split_incidents" if len(incidents) > 1 else "single_incident"

    return {
        "document_classification": classification,
        "incidents": incidents,
    }


def archive_case_folder(source_case_folder: Path, archive_root: Path) -> Path:
    archive_root.mkdir(parents=True, exist_ok=True)
    destination = archive_root / source_case_folder.name
    if destination.exists():
        remove_path(destination)
    shutil.move(str(source_case_folder), str(destination))
    return destination


def load_original_payload_from_raw(batch_folder: Path, original_case_id: str) -> dict | None:
    """Recover the original identify_incident payload from batch raw output when available."""
    raw_output_path = batch_folder / "_identify_incident_batch" / "identify_incident_output_raw.jsonl"
    if not raw_output_path.exists():
        return None

    for line in raw_output_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if str(obj.get("custom_id", "")) != original_case_id:
            continue
        response = obj.get("response") or {}
        body = response.get("body") or {}
        output = body.get("output")
        if not isinstance(output, list):
            continue
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for chunk in content:
                text = chunk.get("text") if isinstance(chunk, dict) else None
                if isinstance(text, str):
                    try:
                        return json.loads(text)
                    except Exception:
                        return None
    return None


def restore_missing_original_cases_from_splits(batch_folder: Path) -> None:
    """
    Recreate missing original case folders from existing split folders.

    This lets postprocess rebuild the archive in the original style even when a
    prior run left only `*_split_*` folders behind.
    """
    split_pattern = re.compile(r"^(?P<original>.+)_split_(?P<index>\d+)$")
    grouped_splits: dict[str, list[Path]] = {}

    for child in sorted(batch_folder.iterdir(), key=lambda p: p.name):
        if not child.is_dir():
            continue
        match = split_pattern.match(child.name)
        if not match:
            continue
        grouped_splits.setdefault(match.group("original"), []).append(child)

    for original_case_id, split_dirs in grouped_splits.items():
        original_case_folder = batch_folder / original_case_id
        if original_case_folder.exists():
            continue

        original_payload = load_original_payload_from_raw(batch_folder, original_case_id)
        if original_payload is None:
            split_payloads: list[dict] = []
            for split_dir in split_dirs:
                output_path = split_dir / "identify_incident_output.json"
                if not output_path.exists():
                    continue
                try:
                    split_payloads.append(json.loads(output_path.read_text(encoding="utf-8")))
                except Exception:
                    continue
            if not split_payloads:
                continue
            original_payload = build_multi_incident_payload_from_splits(split_payloads)

        original_case_folder.mkdir(parents=True, exist_ok=True)
        copy_case_pdf(split_dirs[0], original_case_folder)
        write_json(original_case_folder / "identify_incident_output.json", original_payload)

        for split_dir in split_dirs:
            remove_path(split_dir)


def build_summary_row(case_folder: Path, result_text: str, status: str) -> dict[str, str]:
    row = {
        "case_id": case_folder.name,
        "batch_id": case_folder.parent.name,
        "recommended_output_mode": "",
        "is_summary_style": "",
        "is_full_incident_report": "",
        "contains_multiple_independent_incidents": "",
        "requires_incident_split": "",
        "incident_count": "",
        "status": status,
    }

    try:
        data = json.loads(result_text)
        classification = data.get("document_classification", {})
        incidents = data.get("incidents", [])
        row.update(
            {
                "recommended_output_mode": str(classification.get("recommended_output_mode", "")),
                "is_summary_style": str(classification.get("is_summary_style", "")),
                "is_full_incident_report": str(classification.get("is_full_incident_report", "")),
                "contains_multiple_independent_incidents": str(
                    classification.get("contains_multiple_independent_incidents", "")
                ),
                "requires_incident_split": str(classification.get("requires_incident_split", "")),
                "incident_count": str(len(incidents) if isinstance(incidents, list) else ""),
            }
        )
    except Exception:
        row["status"] = "invalid_json"

    return row


def apply_case_postprocess(batch_folder: Path) -> None:
    archive_root = batch_folder.parent / "_postprocess_archive" / batch_folder.name
    summary_archive_root = resolve_archive_dir(archive_root, batch_folder.name, "summary_only")
    multi_archive_root = resolve_archive_dir(archive_root, batch_folder.name, "original_multi_incident")
    non_full_archive_root = resolve_archive_dir(archive_root, batch_folder.name, "non_full_documents")
    split_mapping_rows: list[dict[str, str]] = []

    case_folders = [
        child
        for child in sorted(batch_folder.iterdir(), key=lambda p: p.name)
        if child.is_dir() and "_split_" not in child.name and not child.name.startswith("_")
    ]

    for case_folder in case_folders:
        output_path = case_folder / "identify_incident_output.json"
        if not output_path.exists():
            continue

        try:
            data = json.loads(output_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        classification = data.get("document_classification", {})
        incidents = data.get("incidents", [])
        is_summary_style = bool(classification.get("is_summary_style"))
        is_full_incident_report = bool(classification.get("is_full_incident_report"))
        should_split = (
            not is_summary_style
            and classification.get("recommended_output_mode") == "split_incidents"
            and bool(classification.get("requires_incident_split"))
            and isinstance(incidents, list)
            and len(incidents) > 1
        )

        if is_summary_style:
            archive_case_folder(case_folder, summary_archive_root)
            continue

        if not is_full_incident_report and not should_split:
            archive_case_folder(case_folder, non_full_archive_root)
            continue

        if not should_split:
            continue

        split_targets = [
            batch_folder / f"{case_folder.name}_split_{index}"
            for index in range(1, len(incidents) + 1)
        ]
        for split_target in split_targets:
            if split_target.exists():
                remove_path(split_target)

        pdf_name = ""
        for index, incident in enumerate(incidents, start=1):
            incident_dict = incident if isinstance(incident, dict) else {}
            split_case_id = f"{case_folder.name}_split_{index}"
            split_folder = batch_folder / split_case_id
            split_folder.mkdir(parents=True, exist_ok=True)
            if not pdf_name:
                pdf_name = copy_case_pdf(case_folder, split_folder)
            else:
                source_pdf = next(iter(sorted(case_folder.glob("*.pdf"))), None)
                if source_pdf:
                    shutil.copy2(source_pdf, split_folder / source_pdf.name)

            split_payload = build_split_payload(data, incident_dict)
            write_json(split_folder / "identify_incident_output.json", split_payload)

            split_mapping_rows.append(
                {
                    "batch_id": batch_folder.name,
                    "original_case_id": case_folder.name,
                    "split_case_id": split_case_id,
                    "incident_id": str(incident_dict.get("incident_id", "")),
                    "time_reference": str(incident_dict.get("time_reference", "")),
                }
            )

        archive_case_folder(case_folder, multi_archive_root)

    write_split_mapping_csv(batch_folder / "identify_incident_split_mapping.csv", split_mapping_rows)


def rebuild_batch_folder(batch_folder: Path) -> None:
    restore_missing_original_cases_from_splits(batch_folder)

    case_folders = [
        child
        for child in sorted(batch_folder.iterdir(), key=lambda p: p.name)
        if child.is_dir() and not child.name.startswith("_")
    ]

    summary_rows: list[dict[str, str]] = []
    for case_folder in case_folders:
        output_path = case_folder / "identify_incident_output.json"
        if not output_path.exists():
            summary_rows.append(build_summary_row(case_folder, "{}", "missing_output"))
            continue

        result_text = output_path.read_text(encoding="utf-8")
        summary_rows.append(build_summary_row(case_folder, result_text, "ok"))

    batch_summary_path = batch_folder / "identify_incident_summary.csv"
    all_summary_path = batch_folder.parent / "identify_incident_summary_all.csv"
    write_summary_csv(batch_summary_path, summary_rows)

    all_rows: list[dict[str, str]] = []
    if all_summary_path.exists():
        try:
            existing = all_summary_path.read_text(encoding="utf-8-sig")
            reader = csv.DictReader(existing.splitlines())
            for row in reader:
                if row.get("batch_id") != batch_folder.name:
                    all_rows.append({column: str(row.get(column, "")) for column in SUMMARY_COLUMNS})
        except Exception:
            all_rows = []
    all_rows.extend(summary_rows)
    all_rows.sort(key=lambda row: (row.get("batch_id", ""), row.get("case_id", "")))
    write_summary_csv(all_summary_path, all_rows)

    archive_dir = batch_folder.parent / "_postprocess_archive" / batch_folder.name
    prepare_archive_root(archive_dir)
    sync_archive_record_files(batch_folder)

    apply_case_postprocess(batch_folder)
    sync_archive_record_files(batch_folder)
    print(f"[DONE] Rebuilt summary and postprocess for {batch_folder.name}")


def main() -> None:
    for batch_folder in iter_target_batch_folders(BATCH_FOLDER, PROCESS_ALL_BATCHES):
        rebuild_batch_folder(batch_folder)


if __name__ == "__main__":
    main()
