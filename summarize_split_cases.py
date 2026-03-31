from __future__ import annotations

"""
Summarize identify-incident split cases across batched reports.

This script scans `identify_incident_split_mapping.csv` files and reports:
- which batch folders contain split results
- which original case ids were split
- how many split outputs were created per original case
"""

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(r"runs\batched_reports")
OUTPUT_REPORT_PATH = ROOT / "split_case_summary.json"


def main() -> None:
    summary: list[dict[str, object]] = []
    split_dirs_by_batch: dict[str, dict[str, list[str]]] = {}

    for batch_dir in sorted(ROOT.glob("batch_*")):
        if not batch_dir.is_dir():
            continue
        grouped: dict[str, list[str]] = defaultdict(list)
        for split_dir in sorted(batch_dir.glob("*_split_*")):
            if not split_dir.is_dir():
                continue
            original_case_id = split_dir.name.split("_split_", 1)[0]
            grouped[original_case_id].append(split_dir.name)
        if grouped:
            split_dirs_by_batch[batch_dir.name] = dict(grouped)

    for csv_path in sorted(ROOT.glob("batch_*/identify_incident_split_mapping.csv")):
        with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        batch_id = csv_path.parent.name

        counter = Counter(row["original_case_id"] for row in rows)
        time_refs: dict[str, list[str]] = defaultdict(list)
        for row in rows:
            time_refs[row["original_case_id"]].append(row.get("time_reference", ""))

        split_dir_info = split_dirs_by_batch.pop(batch_id, {})
        if not rows and not split_dir_info:
            continue

        original_case_ids = sorted(set(counter) | set(split_dir_info))
        batch_entry = {
            "batch_id": batch_id,
            "split_row_count": len(rows),
            "original_cases": [
                {
                    "original_case_id": case_id,
                    "split_count": int(counter.get(case_id, 0)),
                    "time_references": time_refs[case_id],
                    "split_directories": split_dir_info.get(case_id, []),
                    "mapping_missing": case_id not in counter and case_id in split_dir_info,
                }
                for case_id in original_case_ids
            ],
        }
        summary.append(batch_entry)

    for batch_id, split_dir_info in sorted(split_dirs_by_batch.items()):
        summary.append(
            {
                "batch_id": batch_id,
                "split_row_count": 0,
                "original_cases": [
                    {
                        "original_case_id": case_id,
                        "split_count": 0,
                        "time_references": [],
                        "split_directories": split_dirs,
                        "mapping_missing": True,
                    }
                    for case_id, split_dirs in sorted(split_dir_info.items(), key=lambda item: item[0])
                ],
            }
        )

    summary.sort(key=lambda entry: entry["batch_id"])

    OUTPUT_REPORT_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    if not summary:
        print("No split cases found.")
        print(f"Report saved to: {OUTPUT_REPORT_PATH}")
        return

    total_original_cases = sum(len(entry["original_cases"]) for entry in summary)
    print(f"Found split results in {len(summary)} batch(es).")
    print(f"Original split source cases: {total_original_cases}")
    print(f"Report saved to: {OUTPUT_REPORT_PATH}")

    for entry in summary:
        parts = ", ".join(
            (
                f"{item['original_case_id']}->{item['split_count']}"
                if not item["mapping_missing"]
                else f"{item['original_case_id']}->dirs:{len(item['split_directories'])}(mapping_missing)"
            )
            for item in entry["original_cases"]
        )
        print(f"{entry['batch_id']}: {parts}")


if __name__ == "__main__":
    main()
