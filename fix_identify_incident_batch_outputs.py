from __future__ import annotations

"""
Repair identify-incident outputs from previously saved Batch API raw result files.

This script is intended for cases where `identify_incident_output.json` was written
with the outer Responses API envelope instead of the model's actual JSON output.

Behavior:
1. Read `_identify_incident_batch/identify_incident_output_raw.jsonl`.
2. Extract the inner model output text for each `custom_id`.
3. Rewrite each case folder's `identify_incident_output.json` to match the old
   sync-mode save format.

Recommended usage:
- Use `PROCESS_ALL_BATCHES = False` to repair one batch folder.
- Use `PROCESS_ALL_BATCHES = True` to repair all sibling `batch_*` folders.
"""

import json
from pathlib import Path


BATCH_FOLDER = Path(r"runs\batched_reports\batch_9")  # Used when PROCESS_ALL_BATCHES = False.
PROCESS_ALL_BATCHES = True  # True: repair all sibling batch_* directories under BATCH_FOLDER.parent.
OVERWRITE_EXISTING_OUTPUTS = True  # True: replace existing identify_incident_output.json files.


def iter_target_batch_folders(batch_folder: Path, process_all_batches: bool) -> list[Path]:
    if not process_all_batches:
        return [batch_folder]

    batch_folders = sorted(
        path
        for path in batch_folder.parent.iterdir()
        if path.is_dir() and path.name.startswith("batch_")
    )
    return batch_folders or [batch_folder]


def extract_output_text_from_batch_response(body: dict) -> str:
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


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def repair_batch_folder(batch_folder: Path) -> None:
    raw_output_path = batch_folder / "_identify_incident_batch" / "identify_incident_output_raw.jsonl"
    if not raw_output_path.exists():
        print(f"[SKIP] Missing raw output file: {raw_output_path}")
        return

    repaired = 0
    skipped = 0
    failed = 0

    for line in raw_output_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue

        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            failed += 1
            print(f"[FAIL] Invalid JSONL line in {raw_output_path}: {exc}")
            continue

        custom_id = str(obj.get("custom_id", "")).strip()
        response = obj.get("response") or {}
        body = response.get("body") or {}
        status_code = response.get("status_code")
        if not custom_id or status_code != 200:
            failed += 1
            print(f"[FAIL] Skipping malformed or failed response for custom_id={custom_id!r}")
            continue

        case_folder = batch_folder / custom_id
        output_path = case_folder / "identify_incident_output.json"
        if output_path.exists() and not OVERWRITE_EXISTING_OUTPUTS:
            skipped += 1
            continue

        result_text = extract_output_text_from_batch_response(body)
        write_text(output_path, result_text)
        repaired += 1

    print(f"[DONE] {batch_folder.name}: repaired={repaired}, skipped={skipped}, failed={failed}")


def main() -> None:
    for batch_folder in iter_target_batch_folders(BATCH_FOLDER, PROCESS_ALL_BATCHES):
        repair_batch_folder(batch_folder)


if __name__ == "__main__":
    main()
