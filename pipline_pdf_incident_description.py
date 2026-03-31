"""
Batch identify-incident entrypoint for PDF-based incident extraction.

This script prepares and submits identify-incident requests using the OpenAI
Batch API, then writes structured outputs back into each case folder as
`identify_incident_output.json`.

Main responsibilities:
1. Discover target case folders under one or more `batch_*` directories.
2. Optionally skip cases that already have generated outputs.
3. Submit missing cases as a single OpenAI Batch job per batch directory.
4. Save batch results back into the original case folders.
5. Generate summary CSVs and run local postprocessing such as split handling
   and archiving of summary-only or non-full-report documents.

Execution modes:
1. Single-batch mode:
   Process only `batch_folder`.
2. Multi-batch mode:
   Discover sibling `batch_*` directories under `batch_folder.parent`.
3. Postprocess-only mode:
   Skip new API submission and only operate on existing outputs.

Recommended usage:
- Use `PROCESS_ALL_BATCHES = False` for targeted reruns.
- Use `SKIP_EXISTING_OUTPUTS = True` for resume-safe production runs.
- Use `POSTPROCESS_ONLY = True` only when outputs already exist and only the
  summary/archive/split stage needs to be refreshed.
"""

import sys
import csv
import json
import shutil
from pathlib import Path
from openai import OpenAI
import time
from dotenv import load_dotenv
from tqdm import tqdm


load_dotenv()

# Initialize client
client = OpenAI()

# ================================================================
# CONFIG
# ================================================================
batch_folder = Path(r"runs\batched_reports\batch_13")  # Used when PROCESS_ALL_BATCHES = False.
PROCESS_ALL_BATCHES = False  # True: scan all sibling batch_* directories under batch_folder.parent.
model_name = "gpt-5.4-2026-03-05"
POSTPROCESS_ONLY = False  # True: skip new submissions and only reuse existing identify_incident_output.json files.
SKIP_EXISTING_OUTPUTS = True  # True: do not resubmit cases that already have identify_incident_output.json.
ENDPOINT = "/v1/responses"  # Batch API endpoint used for identify-incident requests.
COMPLETION_WINDOW = "24h"  # OpenAI Batch API completion window.
POLL_SECONDS = 15  # Polling interval for refreshing batch job status.

# load only the prompt needed by this script
identify_incident_prompt = Path("prompt/identify_incident.txt").read_text(encoding="utf-8")

# ================================================================
# Pretty Colors (optional)
# ================================================================
class C:
    HEADER = "\033[95m"
    BLUE = "\033[94m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    END = "\033[0m"


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


def write_summary_csv(path: Path, rows: list[dict[str, str]]) -> None:
    """Write summary rows to CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def read_summary_csv(path: Path) -> list[dict[str, str]]:
    """Read an existing summary CSV if present."""
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows: list[dict[str, str]] = []
        for row in reader:
            normalized = {column: str(row.get(column, "")) for column in SUMMARY_COLUMNS}
            rows.append(normalized)
        return rows


def merge_summary_rows(
    existing_rows: list[dict[str, str]],
    new_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Update existing rows by case_id+batch_id, append when missing."""
    merged: dict[tuple[str, str], dict[str, str]] = {}

    for row in existing_rows:
        key = (row.get("batch_id", ""), row.get("case_id", ""))
        merged[key] = {column: str(row.get(column, "")) for column in SUMMARY_COLUMNS}

    for row in new_rows:
        key = (row.get("batch_id", ""), row.get("case_id", ""))
        merged[key] = {column: str(row.get(column, "")) for column in SUMMARY_COLUMNS}

    return sorted(
        merged.values(),
        key=lambda row: (row.get("batch_id", ""), row.get("case_id", "")),
    )


def build_summary_row(case_folder: Path, result_text: str, status: str) -> dict[str, str]:
    """Build a summary row from identify_incident JSON output."""
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


def write_json(path: Path, data: dict) -> None:
    """Write JSON data with UTF-8 encoding."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def remove_path(path: Path) -> None:
    """Remove an existing file or directory."""
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def iter_category_dirs(archive_dir: Path, batch_name: str, category: str) -> list[Path]:
    """Return all legacy/current directory names used for one archive category."""
    return [
        archive_dir / template.format(batch_name=batch_name)
        for template in ARCHIVE_CATEGORY_TEMPLATES[category]
    ]


def resolve_archive_dir(archive_dir: Path, batch_name: str, category: str) -> Path:
    """Prefer an already-existing legacy archive directory name for continuity."""
    candidates = iter_category_dirs(archive_dir, batch_name, category)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def copy_case_pdf(source_case_folder: Path, target_case_folder: Path) -> str:
    """Copy the first PDF from the source case folder to the target case folder."""
    pdf_files = sorted(source_case_folder.glob("*.pdf"))
    if not pdf_files:
        return ""
    source_pdf = pdf_files[0]
    target_case_folder.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_pdf, target_case_folder / source_pdf.name)
    return source_pdf.name


def build_split_payload(original_data: dict, incident: dict) -> dict:
    """Create a single-incident identify_incident JSON payload."""
    classification = dict(original_data.get("document_classification", {}))
    classification["contains_multiple_independent_incidents"] = False
    classification["requires_incident_split"] = False
    classification["recommended_output_mode"] = "single_incident"

    return {
        "document_classification": classification,
        "incidents": [incident],
    }


def archive_case_folder(source_case_folder: Path, archive_root: Path) -> Path:
    """Move a case folder into an archive root, replacing any previous archived copy."""
    archive_root.mkdir(parents=True, exist_ok=True)
    destination = archive_root / source_case_folder.name
    if destination.exists():
        remove_path(destination)
    shutil.move(str(source_case_folder), str(destination))
    return destination


def write_split_mapping_csv(path: Path, rows: list[dict[str, str]]) -> None:
    """Write split mapping rows to CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SPLIT_MAPPING_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def apply_case_postprocess(batch_folder: Path) -> None:
    """Split multi-incident cases and archive summary-style/original multi-incident folders."""
    archive_root = batch_folder.parent / "_postprocess_archive" / batch_folder.name
    summary_archive_root = resolve_archive_dir(archive_root, batch_folder.name, "summary_only")
    multi_archive_root = resolve_archive_dir(archive_root, batch_folder.name, "original_multi_incident")
    non_full_archive_root = resolve_archive_dir(archive_root, batch_folder.name, "non_full_documents")
    split_mapping_rows: list[dict[str, str]] = []

    case_folders = [
        child for child in sorted(batch_folder.iterdir(), key=lambda p: p.name)
        if child.is_dir() and "_split_" not in child.name
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
            archived = archive_case_folder(case_folder, summary_archive_root)
            print(f"{C.YELLOW}↺ Moved summary-style case to archive: {archived.name}{C.END}")
            continue

        if not is_full_incident_report and not should_split:
            archived = archive_case_folder(case_folder, non_full_archive_root)
            print(f"{C.YELLOW}↺ Moved non-full document to archive: {archived.name}{C.END}")
            continue

        if not should_split:
            continue

        split_targets = [batch_folder / f"{case_folder.name}_split_{index}" for index in range(1, len(incidents) + 1)]
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

        archived = archive_case_folder(case_folder, multi_archive_root)
        print(f"{C.GREEN}✔ Split case {archived.name} into {len(incidents)} folder(s).{C.END}")

    write_split_mapping_csv(batch_folder / "identify_incident_split_mapping.csv", split_mapping_rows)


def iter_target_batch_folders(target_batch_folder: Path, process_all_batches: bool) -> list[Path]:
    """Return the batch folders to process based on the current scope setting."""
    if not process_all_batches:
        return [target_batch_folder]

    batch_folders = sorted(
        path
        for path in target_batch_folder.parent.iterdir()
        if path.is_dir() and path.name.startswith("batch_")
    )
    return batch_folders or [target_batch_folder]


def write_text(path: Path, content: str) -> None:
    """Write text content to disk, creating parent directories when needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def poll_batch_until_done(
    batch_id: str,
    *,
    poll_seconds: int = POLL_SECONDS,
    progress_bar: tqdm | None = None,
) -> dict:
    """Poll a Batch API job until it reaches a terminal state."""
    while True:
        batch = client.batches.retrieve(batch_id)
        status = batch.status
        if progress_bar is not None:
            batch_dict = batch.model_dump() if hasattr(batch, "model_dump") else dict(batch)
            request_counts = batch_dict.get("request_counts") or {}
            completed = int(request_counts.get("completed", 0) or 0)
            failed = int(request_counts.get("failed", 0) or 0)
            total_done = completed + failed
            if total_done > progress_bar.n:
                progress_bar.update(total_done - progress_bar.n)
            progress_bar.set_description(
                f"{progress_bar.desc.split(' | ')[0]} | {status}"
            )
        if status in ("completed", "failed", "expired", "cancelled"):
            return batch.model_dump() if hasattr(batch, "model_dump") else dict(batch)
        time.sleep(poll_seconds)


def download_file_text(file_id: str) -> str:
    """Download a Batch API output or error file as text."""
    response = client.files.content(file_id)
    return response.text if hasattr(response, "text") else str(response)


def extract_output_text_from_batch_response(body: dict) -> str:
    """Extract the model output text from a Batch API response body."""
    output_text = body.get("output_text")
    if isinstance(output_text, str):
        return output_text

    output = body.get("output")
    if isinstance(output, list):
        parts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for chunk in content:
                if isinstance(chunk, dict) and isinstance(chunk.get("text"), str):
                    parts.append(chunk["text"])
        if parts:
            return "\n".join(parts)

    return json.dumps(body, ensure_ascii=False, indent=2)


def run_identify_incident_batch(
    current_batch_folder: Path,
    pending_folders: list[Path],
) -> list[dict[str, str]]:
    """Submit one Batch API job for all pending cases in a batch folder."""
    batch_workdir = current_batch_folder / "_identify_incident_batch"
    batch_workdir.mkdir(parents=True, exist_ok=True)

    request_lines: list[str] = []
    id_to_folder: dict[str, Path] = {}
    immediate_rows: list[dict[str, str]] = []

    upload_progress = tqdm(
        pending_folders,
        desc=f"{current_batch_folder.name} prepare",
        unit="case",
        leave=False,
    )
    for case_folder in upload_progress:
        upload_progress.set_description(f"{current_batch_folder.name} upload")
        pdf_files = sorted(case_folder.glob("*.pdf"))
        if not pdf_files:
            tqdm.write(f"{C.RED}⚠️ No PDF found in {case_folder}{C.END}")
            immediate_rows.append(build_summary_row(case_folder, "{}", "missing_pdf"))
            continue

        pdf_path = pdf_files[0]
        with pdf_path.open("rb") as fp:
            uploaded_pdf = client.files.create(file=fp, purpose="user_data")

        input_messages = [
            {"role": "system", "content": [{"type": "input_text", "text": identify_incident_prompt}]},
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "The document is uploaded. Please perform the identify_incident task.",
                    },
                    {"type": "input_file", "file_id": uploaded_pdf.id},
                ],
            },
        ]

        custom_id = case_folder.name
        id_to_folder[custom_id] = case_folder
        request_lines.append(
            json.dumps(
                {
                    "custom_id": custom_id,
                    "method": "POST",
                    "url": ENDPOINT,
                    "body": {
                        "model": model_name,
                        "input": input_messages,
                        "text": {"format": {"type": "json_object"}},
                    },
                },
                ensure_ascii=False,
            )
        )

    if not request_lines:
        tqdm.write(f"{C.YELLOW}↺ No new requests to submit for {current_batch_folder.name}{C.END}")
        return immediate_rows

    batch_input_path = batch_workdir / "identify_incident_batchinput.jsonl"
    write_text(batch_input_path, "\n".join(request_lines) + "\n")

    tqdm.write(
        f"{C.BLUE}[{current_batch_folder.name}] prepared={len(pending_folders)} submitted={len(request_lines)}{C.END}"
    )
    with batch_input_path.open("rb") as fp:
        uploaded_batch = client.files.create(file=fp, purpose="batch")

    batch = client.batches.create(
        input_file_id=uploaded_batch.id,
        endpoint=ENDPOINT,
        completion_window=COMPLETION_WINDOW,
        metadata={"step": "identify_incident", "batch_folder": current_batch_folder.name},
    )
    tqdm.write(f"{C.BLUE}[{current_batch_folder.name}] batch submitted: {batch.id}{C.END}")

    batch_job_progress = tqdm(
        total=len(request_lines),
        desc=f"{current_batch_folder.name} batch",
        unit="req",
        leave=False,
    )
    final = poll_batch_until_done(
        batch.id,
        poll_seconds=POLL_SECONDS,
        progress_bar=batch_job_progress,
    )
    if batch_job_progress.n < batch_job_progress.total:
        batch_job_progress.update(batch_job_progress.total - batch_job_progress.n)
    batch_job_progress.close()
    write_text(
        batch_workdir / "identify_incident_batch_object.json",
        json.dumps(final, ensure_ascii=False, indent=2),
    )
    tqdm.write(f"{C.BLUE}[{current_batch_folder.name}] status: {final.get('status')}{C.END}")

    error_file_id = final.get("error_file_id")
    if error_file_id:
        err_text = download_file_text(error_file_id)
        write_text(batch_workdir / "identify_incident_errors.jsonl", err_text)

    output_file_id = final.get("output_file_id")
    if not output_file_id:
        tqdm.write(f"{C.RED}[{current_batch_folder.name}] No successful outputs returned.{C.END}")
        for case_folder in pending_folders:
            if case_folder.name in id_to_folder:
                immediate_rows.append(build_summary_row(case_folder, "{}", "error"))
        return immediate_rows

    out_text = download_file_text(output_file_id)
    write_text(batch_workdir / "identify_incident_output_raw.jsonl", out_text)

    ok = 0
    fail = 0
    seen_ids: set[str] = set()
    for line in out_text.splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        custom_id = obj.get("custom_id")
        case_folder = id_to_folder.get(custom_id)
        if case_folder is None:
            continue
        seen_ids.add(custom_id)

        error = obj.get("error")
        response = obj.get("response")
        if error:
            fail += 1
            write_text(case_folder / "identify_incident_error.json", json.dumps(error, ensure_ascii=False, indent=2))
            immediate_rows.append(build_summary_row(case_folder, "{}", "error"))
            continue

        if not response or response.get("status_code") != 200:
            fail += 1
            write_text(case_folder / "identify_incident_error.json", json.dumps(obj, ensure_ascii=False, indent=2))
            immediate_rows.append(build_summary_row(case_folder, "{}", "error"))
            continue

        body = response.get("body", {})
        result_text = extract_output_text_from_batch_response(body)

        write_text(case_folder / "identify_incident_output.json", result_text)
        immediate_rows.append(build_summary_row(case_folder, result_text, "ok"))
        ok += 1

    for custom_id, case_folder in id_to_folder.items():
        if custom_id in seen_ids:
            continue
        fail += 1
        immediate_rows.append(build_summary_row(case_folder, "{}", "missing_output"))

    tqdm.write(
        f"{C.GREEN}[{current_batch_folder.name}] results: ok={ok} fail={fail}{C.END}"
    )
    return immediate_rows


def load_existing_output(case_folder: Path) -> dict[str, str] | None:
    """Load an existing identify_incident output if it is already present."""
    output_path = case_folder / "identify_incident_output.json"
    if not output_path.exists():
        return None

    result_text = output_path.read_text(encoding="utf-8")
    return build_summary_row(case_folder, result_text, "ok")


# ================================================================
# MAIN
# ================================================================
def main():
    target_batch_folders = iter_target_batch_folders(batch_folder, PROCESS_ALL_BATCHES)

    batch_progress = tqdm(target_batch_folders, desc="Batches", unit="batch")
    for current_batch_folder in batch_progress:
        batch_progress.set_description(f"Batches ({current_batch_folder.name})")
        tqdm.write(f"{C.HEADER}Scanning batch folder: {current_batch_folder}{C.END}")

        case_folders = [
            child
            for child in current_batch_folder.iterdir()
            if child.is_dir() and not child.name.startswith("_")
        ]
        total = len(case_folders)

        if total == 0:
            tqdm.write(f"{C.RED}No case folders found.{C.END}")
            continue

        tqdm.write(f"{C.GREEN}Found {total} case folders. Starting processing...{C.END}")

        summary_rows: list[dict[str, str]] = []
        pending_folders: list[Path] = []
        skipped_count = 0
        for folder in case_folders:
            if SKIP_EXISTING_OUTPUTS:
                existing_row = load_existing_output(folder)
                if existing_row is not None:
                    summary_rows.append(existing_row)
                    skipped_count += 1
                    continue

            pending_folders.append(folder)

        tqdm.write(
            f"{C.BLUE}[{current_batch_folder.name}] prepared={total} pending={len(pending_folders)} skipped={skipped_count}{C.END}"
        )

        if POSTPROCESS_ONLY:
            for folder in pending_folders:
                output_path = folder / "identify_incident_output.json"
                if output_path.exists():
                    result_text = output_path.read_text(encoding="utf-8")
                    summary_rows.append(build_summary_row(folder, result_text, "ok"))
                else:
                    tqdm.write(f"{C.RED}⚠️ Missing identify_incident_output.json in {folder}{C.END}")
                    summary_rows.append(build_summary_row(folder, "{}", "missing_output"))
        else:
            summary_rows.extend(run_identify_incident_batch(current_batch_folder, pending_folders))

        batch_summary_path = current_batch_folder / "identify_incident_summary.csv"
        all_summary_path = current_batch_folder.parent / "identify_incident_summary_all.csv"

        merged_batch_rows = merge_summary_rows(read_summary_csv(batch_summary_path), summary_rows)
        merged_all_rows = merge_summary_rows(read_summary_csv(all_summary_path), summary_rows)

        write_summary_csv(batch_summary_path, merged_batch_rows)
        write_summary_csv(all_summary_path, merged_all_rows)
        apply_case_postprocess(current_batch_folder)

        tqdm.write(
            f"\n{C.HEADER}=== ALL DONE: {total} cases processed in {current_batch_folder.name} ==={C.END}"
        )


if __name__ == "__main__":
    main()
