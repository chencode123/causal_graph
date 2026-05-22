from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_SOURCE_ROOT = Path(r"runs\stability_test\batch_4_5_6")
DEFAULT_OUTPUT_PATH = Path(
    r"runs/few-shot/review_feedback/review_feedback_analysis_aggregated.json"
)


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def dump_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)
        fp.write("\n")


def dump_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def iter_review_feedback_files(root: Path) -> list[Path]:
    return sorted(root.rglob("review_feedback_analysis_output.json"))


def _dedupe_patterns(items: list[dict[str, Any]], *, key_fields: tuple[str, ...]) -> list[dict[str, Any]]:
    seen: set[tuple[str, ...]] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        key = tuple(str(item.get(field) or "").strip() for field in key_fields)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def aggregate_review_feedback(files: list[Path], root: Path) -> dict[str, Any]:
    planning_patterns: list[dict[str, Any]] = []
    diagnosis_patterns: list[dict[str, Any]] = []
    coverage_notes: list[str] = []
    unresolved_decisions: list[dict[str, Any]] = []
    accepted_count = 0
    rejected_count = 0
    unresolved_count = 0
    planning_takeaway_counter: Counter[str] = Counter()
    diagnosis_takeaway_counter: Counter[str] = Counter()
    matched_rule_counter: Counter[str] = Counter()
    supporting_rule_counter: Counter[str] = Counter()

    for path in files:
        payload = load_json(path)
        relative_path = str(path.relative_to(root)).replace("\\", "/")

        case_summary = payload.get("case_summary", {})
        accepted_count += int(case_summary.get("accepted_count", 0) or 0)
        rejected_count += int(case_summary.get("rejected_count", 0) or 0)
        unresolved_count += int(case_summary.get("unresolved_count", 0) or 0)

        for item in payload.get("planning_patterns", []):
            if not isinstance(item, dict):
                continue
            enriched = dict(item)
            enriched["source_file"] = relative_path
            planning_patterns.append(enriched)
            takeaway = str(item.get("few_shot_takeaway") or "").strip()
            matched_rule = str(item.get("matched_rule") or "").strip()
            if takeaway:
                planning_takeaway_counter[takeaway] += 1
            if matched_rule:
                matched_rule_counter[matched_rule] += 1

        for item in payload.get("diagnosis_patterns", []):
            if not isinstance(item, dict):
                continue
            enriched = dict(item)
            enriched["source_file"] = relative_path
            diagnosis_patterns.append(enriched)
            takeaway = str(item.get("few_shot_takeaway") or "").strip()
            supporting_rule = str(item.get("supporting_rule") or "").strip()
            if takeaway:
                diagnosis_takeaway_counter[takeaway] += 1
            if supporting_rule:
                supporting_rule_counter[supporting_rule] += 1

        for note in payload.get("coverage_notes", []):
            note_text = str(note).strip()
            if note_text:
                coverage_notes.append(note_text)

        for item in payload.get("unresolved_decisions", []):
            if not isinstance(item, dict):
                continue
            enriched = dict(item)
            enriched["source_file"] = relative_path
            unresolved_decisions.append(enriched)

    deduped_planning_patterns = _dedupe_patterns(
        planning_patterns,
        key_fields=("decision", "matched_rule", "few_shot_takeaway", "proposed_change"),
    )
    deduped_diagnosis_patterns = _dedupe_patterns(
        diagnosis_patterns,
        key_fields=(
            "decision",
            "supporting_rule",
            "few_shot_takeaway",
            "observed_pattern",
            "diagnosis_interpretation",
        ),
    )
    deduped_coverage_notes = sorted(set(coverage_notes))

    return {
        "source_root": str(root).replace("\\", "/"),
        "source_files": [str(path.relative_to(root)).replace("\\", "/") for path in files],
        "summary": {
            "file_count": len(files),
            "accepted_count": accepted_count,
            "rejected_count": rejected_count,
            "unresolved_count": unresolved_count,
            "planning_pattern_count": len(planning_patterns),
            "diagnosis_pattern_count": len(diagnosis_patterns),
            "deduped_planning_pattern_count": len(deduped_planning_patterns),
            "deduped_diagnosis_pattern_count": len(deduped_diagnosis_patterns),
        },
        "planning_patterns": deduped_planning_patterns,
        "diagnosis_patterns": deduped_diagnosis_patterns,
        "coverage_notes": deduped_coverage_notes,
        "unresolved_decisions": unresolved_decisions,
        "deduped_takeaways": {
            "planning": [
                {"takeaway": text, "count": count}
                for text, count in planning_takeaway_counter.most_common()
            ],
            "diagnosis": [
                {"takeaway": text, "count": count}
                for text, count in diagnosis_takeaway_counter.most_common()
            ],
        },
        "rule_frequency": {
            "planning_matched_rules": [
                {"rule": text, "count": count}
                for text, count in matched_rule_counter.most_common()
            ],
            "diagnosis_supporting_rules": [
                {"rule": text, "count": count}
                for text, count in supporting_rule_counter.most_common()
            ],
        },
    }


def _append_section(lines: list[str], title: str, content: str) -> None:
    text = str(content or "").strip()
    if not text:
        return
    lines.extend([f"{title}", "", text, ""])


def render_markdown(data: dict[str, Any]) -> str:
    summary = data.get("summary", {})
    planning_patterns = data.get("planning_patterns", [])
    diagnosis_patterns = data.get("diagnosis_patterns", [])
    coverage_notes = data.get("coverage_notes", [])
    unresolved = data.get("unresolved_decisions", [])
    takeaway_groups = data.get("deduped_takeaways", {})
    rule_frequency = data.get("rule_frequency", {})

    lines: list[str] = [
        "# Review Feedback Analysis Aggregated",
        "",
        f"- Source root: `{data.get('source_root', '')}`",
        f"- Source files: `{summary.get('file_count', 0)}`",
        f"- Accepted decisions: `{summary.get('accepted_count', 0)}`",
        f"- Rejected decisions: `{summary.get('rejected_count', 0)}`",
        f"- Unresolved decisions: `{summary.get('unresolved_count', 0)}`",
        f"- Planning patterns: `{summary.get('deduped_planning_pattern_count', 0)}` deduped from `{summary.get('planning_pattern_count', 0)}`",
        f"- Diagnosis patterns: `{summary.get('deduped_diagnosis_pattern_count', 0)}` deduped from `{summary.get('diagnosis_pattern_count', 0)}`",
        "",
    ]

    lines.extend(["## Source Files", ""])
    for item in data.get("source_files", []):
        lines.append(f"- `{item}`")
    lines.append("")

    lines.extend(["## Planning Patterns", ""])
    if isinstance(planning_patterns, list) and planning_patterns:
        for index, item in enumerate(planning_patterns, start=1):
            if not isinstance(item, dict):
                continue
            lines.extend(
                [
                    f"### {index}. `{item.get('decision_key', '')}`",
                    "",
                    f"- Decision: `{item.get('decision', '')}`",
                    f"- Source: `{item.get('source_file', '')}`",
                    "",
                ]
            )
            _append_section(lines, "Proposed change", str(item.get("proposed_change") or ""))
            _append_section(lines, "Reviewer reason", str(item.get("reviewer_reason") or ""))
            _append_section(lines, "Matched rule", str(item.get("matched_rule") or ""))
            _append_section(lines, "Few-shot takeaway", str(item.get("few_shot_takeaway") or ""))
    else:
        lines.extend(["_No planning patterns._", ""])

    lines.extend(["## Diagnosis Patterns", ""])
    if isinstance(diagnosis_patterns, list) and diagnosis_patterns:
        for index, item in enumerate(diagnosis_patterns, start=1):
            if not isinstance(item, dict):
                continue
            lines.extend(
                [
                    f"### {index}. `{item.get('derived_from_decision_key', '')}`",
                    "",
                    f"- Decision: `{item.get('decision', '')}`",
                    f"- Source: `{item.get('source_file', '')}`",
                    "",
                ]
            )
            _append_section(lines, "Observed pattern", str(item.get("observed_pattern") or ""))
            _append_section(
                lines,
                "Diagnosis interpretation",
                str(item.get("diagnosis_interpretation") or ""),
            )
            _append_section(lines, "Supporting rule", str(item.get("supporting_rule") or ""))
            _append_section(lines, "Few-shot takeaway", str(item.get("few_shot_takeaway") or ""))
    else:
        lines.extend(["_No diagnosis patterns._", ""])

    lines.extend(["## Deduped Takeaways", ""])
    planning_takeaways = takeaway_groups.get("planning", [])
    diagnosis_takeaways = takeaway_groups.get("diagnosis", [])
    lines.extend(["### Planning", ""])
    if isinstance(planning_takeaways, list) and planning_takeaways:
        for item in planning_takeaways:
            if not isinstance(item, dict):
                continue
            lines.append(f"- ({item.get('count', 0)}) {str(item.get('takeaway') or '').strip()}")
        lines.append("")
    else:
        lines.extend(["_No planning takeaways._", ""])

    lines.extend(["### Diagnosis", ""])
    if isinstance(diagnosis_takeaways, list) and diagnosis_takeaways:
        for item in diagnosis_takeaways:
            if not isinstance(item, dict):
                continue
            lines.append(f"- ({item.get('count', 0)}) {str(item.get('takeaway') or '').strip()}")
        lines.append("")
    else:
        lines.extend(["_No diagnosis takeaways._", ""])

    lines.extend(["## Rule Frequency", ""])
    lines.extend(["### Planning Matched Rules", ""])
    planning_rules = rule_frequency.get("planning_matched_rules", [])
    if isinstance(planning_rules, list) and planning_rules:
        for item in planning_rules:
            if not isinstance(item, dict):
                continue
            lines.append(f"- ({item.get('count', 0)}) {str(item.get('rule') or '').strip()}")
        lines.append("")
    else:
        lines.extend(["_No planning rules._", ""])

    lines.extend(["### Diagnosis Supporting Rules", ""])
    diagnosis_rules = rule_frequency.get("diagnosis_supporting_rules", [])
    if isinstance(diagnosis_rules, list) and diagnosis_rules:
        for item in diagnosis_rules:
            if not isinstance(item, dict):
                continue
            lines.append(f"- ({item.get('count', 0)}) {str(item.get('rule') or '').strip()}")
        lines.append("")
    else:
        lines.extend(["_No diagnosis rules._", ""])

    lines.extend(["## Coverage Notes", ""])
    if isinstance(coverage_notes, list) and coverage_notes:
        for note in coverage_notes:
            lines.append(f"- {str(note).strip()}")
        lines.append("")
    else:
        lines.extend(["_No coverage notes._", ""])

    lines.extend(["## Unresolved Decisions", ""])
    if isinstance(unresolved, list) and unresolved:
        for item in unresolved:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- `{item.get('decision_key', '')}` [{item.get('status', '')}] "
                f"{str(item.get('note') or '').strip()} ({item.get('source_file', '')})".rstrip()
            )
        lines.append("")
    else:
        lines.extend(["_No unresolved decisions._", ""])

    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Aggregate review_feedback_analysis_output.json files into one reusable "
            "few-shot pattern pool."
        )
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=DEFAULT_SOURCE_ROOT,
        help="Root folder to scan for review_feedback_analysis_output.json files.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Output JSON path for the aggregated pattern file.",
    )
    return parser.parse_args()


def main() -> Path:
    args = parse_args()
    source_root = args.source_root.resolve()
    if not source_root.exists():
        raise FileNotFoundError(f"Source root does not exist: {source_root}")

    files = iter_review_feedback_files(source_root)
    if not files:
        raise FileNotFoundError(
            f"No review_feedback_analysis_output.json files found under {source_root}"
        )

    aggregated = aggregate_review_feedback(files, source_root)
    output_path = args.output.resolve()
    dump_json(output_path, aggregated)
    markdown_path = output_path.with_suffix(".md")
    dump_text(markdown_path, render_markdown(aggregated))
    print(f"Aggregated {len(files)} files into: {output_path}")
    print(f"Wrote Markdown summary to: {markdown_path}")
    return output_path


if __name__ == "__main__":
    main()
