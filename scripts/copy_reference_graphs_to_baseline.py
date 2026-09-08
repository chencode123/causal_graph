#!/usr/bin/env python3
"""Copy fixed expert-reference graph artifacts into baseline case folders.

The source and destination are matched strictly by ``batch_id/case_id``.  The
default mode is a dry run; pass ``--write`` to copy files.  Existing files are
never replaced unless ``--overwrite`` is also supplied.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from tqdm import tqdm


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_ROOT = (
    PROJECT_ROOT / "runs" / "stability_test" / "rounds" / "round_1"
)
DEFAULT_TARGET_ROOT = (
    PROJECT_ROOT
    / "runs"
    / "stability_test"
    / "single_pass_baseline_all_batches"
)
DEFAULT_AUDIT_PATH = PROJECT_ROOT / "outputs" / "baseline_reference_copy_audit.json"
REFERENCE_FILE_NAMES = (
    "updated_causal_graph.json",
    "updated_causal_graph.html",
)
GENERATED_FILE_NAME = "causal_graph.json"
NODE_COLLECTION_FIELDS = (
    "hazard_consequence_node",
    "entity_nodes",
    "condition_nodes",
    "event_nodes",
)


@dataclass(frozen=True)
class CopyRecord:
    run_id: str
    report_id: str
    file_name: str
    source: str
    destination: str
    status: str
    source_sha256: str | None = None
    destination_sha256: str | None = None
    message: str = ""


IO_RETRY_ATTEMPTS = 3
IO_RETRY_DELAY_SECONDS = 0.5


def _retry_io(operation):
    """Retry transient filesystem reads common in synchronized-drive folders."""
    for attempt in range(1, IO_RETRY_ATTEMPTS + 1):
        try:
            return operation()
        except OSError:
            if attempt == IO_RETRY_ATTEMPTS:
                raise
            time.sleep(IO_RETRY_DELAY_SECONDS * attempt)


def _sha256_once(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256(path: Path) -> str:
    return _retry_io(lambda: _sha256_once(path))


def _validate_graph(path: Path) -> None:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("top-level JSON value is not an object")
    invalid_node_fields = [
        field for field in NODE_COLLECTION_FIELDS if not isinstance(payload.get(field), list)
    ]
    if invalid_node_fields:
        raise ValueError(f"missing node-list fields: {', '.join(invalid_node_fields)}")
    if not isinstance(payload.get("edges"), list):
        raise ValueError("missing list field: edges")


def _validate_reference_file(path: Path) -> None:
    if path.name == "updated_causal_graph.json":
        _validate_graph(path)
        return
    if path.stat().st_size == 0:
        raise ValueError("HTML reference file is empty")
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        prefix = handle.read(4096).lower()
    if "<html" not in prefix and "<!doctype html" not in prefix:
        raise ValueError("file does not appear to be HTML")


def _source_index(source_root: Path) -> dict[str, Path]:
    index: dict[str, Path] = {}
    duplicates: list[str] = []
    for batch_dir in sorted(source_root.glob("batch_*")):
        if not batch_dir.is_dir():
            continue
        for case_dir in sorted(path for path in batch_dir.iterdir() if path.is_dir()):
            if not any((case_dir / name).is_file() for name in REFERENCE_FILE_NAMES):
                continue
            report_id = f"{batch_dir.name}/{case_dir.name}"
            if report_id in index:
                duplicates.append(report_id)
            index[report_id] = case_dir
    if duplicates:
        raise ValueError(f"duplicate source report IDs: {sorted(set(duplicates))}")
    return index


def _target_cases(target_root: Path, selected_runs: set[str] | None) -> list[tuple[str, str, Path]]:
    cases: list[tuple[str, str, Path]] = []
    for run_dir in sorted(target_root.glob("run_*")):
        if not run_dir.is_dir() or (selected_runs and run_dir.name not in selected_runs):
            continue
        for batch_dir in sorted(run_dir.glob("batch_*")):
            if not batch_dir.is_dir():
                continue
            for case_dir in sorted(path for path in batch_dir.iterdir() if path.is_dir()):
                if not (case_dir / GENERATED_FILE_NAME).is_file():
                    continue
                report_id = f"{batch_dir.name}/{case_dir.name}"
                cases.append((run_dir.name, report_id, case_dir))
    return cases


def _atomic_copy_once(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(file_descriptor)
    temporary_path = Path(temporary_name)
    try:
        shutil.copy2(source, temporary_path)
        temporary_path.replace(destination)
    finally:
        temporary_path.unlink(missing_ok=True)


def _atomic_copy(source: Path, destination: Path) -> None:
    _retry_io(lambda: _atomic_copy_once(source, destination))


def copy_references(
    source_root: Path,
    target_root: Path,
    *,
    write: bool,
    overwrite: bool,
    selected_runs: set[str] | None,
    show_progress: bool = True,
) -> tuple[list[CopyRecord], list[str]]:
    sources = _source_index(source_root)
    target_cases = _target_cases(target_root, selected_runs)
    records: list[CopyRecord] = []
    used_report_ids: set[str] = set()

    progress = tqdm(
        total=len(target_cases) * len(REFERENCE_FILE_NAMES),
        desc="Reference artifacts",
        unit="file",
        dynamic_ncols=True,
        disable=not show_progress,
    )
    try:
        for run_id, report_id, case_dir in target_cases:
            source_case_dir = sources.get(report_id)
            if source_case_dir is not None:
                used_report_ids.add(report_id)

            for file_name in REFERENCE_FILE_NAMES:
                try:
                    _process_reference_artifact(
                        records=records,
                        run_id=run_id,
                        report_id=report_id,
                        case_dir=case_dir,
                        source_case_dir=source_case_dir,
                        file_name=file_name,
                        write=write,
                        overwrite=overwrite,
                    )
                finally:
                    progress.update(1)
    finally:
        progress.close()

    unused_sources = sorted(set(sources) - used_report_ids)
    return records, unused_sources


def _process_reference_artifact(
    *,
    records: list[CopyRecord],
    run_id: str,
    report_id: str,
    case_dir: Path,
    source_case_dir: Path | None,
    file_name: str,
    write: bool,
    overwrite: bool,
) -> None:
    destination = case_dir / file_name
    if source_case_dir is None:
        records.append(
            CopyRecord(
                run_id=run_id,
                report_id=report_id,
                file_name=file_name,
                source="",
                destination=str(destination),
                status="missing-source",
                message="no exact batch_id/case_id reference match",
            )
        )
        return

    source = source_case_dir / file_name
    if not source.is_file():
        records.append(
            CopyRecord(
                run_id=run_id,
                report_id=report_id,
                file_name=file_name,
                source=str(source),
                destination=str(destination),
                status="missing-source",
                message="matched source case does not contain this artifact",
            )
        )
        return

    try:
        def validate_and_hash() -> str:
            _validate_reference_file(source)
            return _sha256_once(source)

        source_hash = _retry_io(validate_and_hash)
    except Exception as exc:
        records.append(
            CopyRecord(
                run_id=run_id,
                report_id=report_id,
                file_name=file_name,
                source=str(source),
                destination=str(destination),
                status="invalid-source",
                message=str(exc),
            )
        )
        return

    destination_hash = _sha256(destination) if destination.is_file() else None
    if destination_hash == source_hash:
        status = "unchanged"
        message = "destination already matches source"
    elif destination.exists() and not overwrite:
        status = "conflict"
        message = "destination exists with different content; use --overwrite"
    elif write:
        try:
            _atomic_copy(source, destination)
            copied_hash = _sha256(destination)
            if copied_hash != source_hash:
                raise OSError("post-copy SHA-256 verification failed")
            status = "copied"
            destination_hash = copied_hash
            message = "verified by SHA-256"
        except Exception as exc:
            status = "failed"
            message = str(exc)
    else:
        status = "would-copy"
        message = "new destination" if not destination.exists() else "would overwrite"

    records.append(
        CopyRecord(
            run_id=run_id,
            report_id=report_id,
            file_name=file_name,
            source=str(source),
            destination=str(destination),
            status=status,
            source_sha256=source_hash,
            destination_sha256=destination_hash,
            message=message,
        )
    )


def _write_audit(
    audit_path: Path,
    *,
    source_root: Path,
    target_root: Path,
    write: bool,
    overwrite: bool,
    selected_runs: set[str] | None,
    records: list[CopyRecord],
    unused_sources: list[str],
) -> None:
    counts = Counter(record.status for record in records)
    payload: dict[str, Any] = {
        "mode": "write" if write else "dry-run",
        "source_root": str(source_root),
        "target_root": str(target_root),
        "reference_file_names": list(REFERENCE_FILE_NAMES),
        "matching_key": "batch_id/case_id",
        "overwrite": overwrite,
        "selected_runs": sorted(selected_runs) if selected_runs else None,
        "target_artifacts": len(records),
        "status_counts": dict(sorted(counts.items())),
        "unused_source_report_ids": unused_sources,
        "records": [asdict(record) for record in records],
    }
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Copy fixed expert-reference graphs to matching baseline cases."
    )
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--target-root", type=Path, default=DEFAULT_TARGET_ROOT)
    parser.add_argument(
        "--run",
        action="append",
        dest="runs",
        help="Limit processing to one run name, e.g. run_01; repeat as needed.",
    )
    parser.add_argument("--write", action="store_true", help="Copy files; default is dry-run.")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow --write to replace a different existing reference file.",
    )
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT_PATH)
    parser.add_argument(
        "--hide-progress",
        action="store_true",
        help="Hide the per-artifact progress bar.",
    )
    args = parser.parse_args()

    source_root = args.source_root.resolve()
    target_root = args.target_root.resolve()
    audit_path = args.audit.resolve()
    if not source_root.is_dir():
        parser.error(f"source root not found: {source_root}")
    if not target_root.is_dir():
        parser.error(f"target root not found: {target_root}")
    if args.overwrite and not args.write:
        parser.error("--overwrite requires --write")

    selected_runs = set(args.runs) if args.runs else None
    records, unused_sources = copy_references(
        source_root,
        target_root,
        write=args.write,
        overwrite=args.overwrite,
        selected_runs=selected_runs,
        show_progress=not args.hide_progress,
    )
    _write_audit(
        audit_path,
        source_root=source_root,
        target_root=target_root,
        write=args.write,
        overwrite=args.overwrite,
        selected_runs=selected_runs,
        records=records,
        unused_sources=unused_sources,
    )

    counts = Counter(record.status for record in records)
    summary = ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))
    print(f"Mode: {'write' if args.write else 'dry-run'}")
    print(f"Target artifacts: {len(records)}")
    print(f"Status: {summary or 'none'}")
    print(f"Unused source report IDs: {len(unused_sources)}")
    for report_id in unused_sources:
        print(f"  unused source: {report_id}")
    for record in records:
        if record.status in {"missing-source", "invalid-source", "conflict", "failed"}:
            print(
                f"  {record.status}: {record.run_id}/{record.report_id}/"
                f"{record.file_name} ({record.message})"
            )
    print(f"Audit: {audit_path}")

    error_statuses = {"missing-source", "invalid-source", "conflict", "failed"}
    return 1 if any(record.status in error_statuses for record in records) else 0


if __name__ == "__main__":
    raise SystemExit(main())
