#!/usr/bin/env python3
"""
Check whether revisions have been accepted or rejected for cases by comparing
same-folder outputs (causal_graph.html / updated_causal_graph.html and
updated_causal_graph_review_state.json).

Usage:
    python scripts/check_revision_acceptance.py <case_dir_or_root>
    python scripts/check_revision_acceptance.py runs/stability_test/rounds
    python scripts/check_revision_acceptance.py runs/stability_test/rounds/batch_1/1
"""

import argparse
import json
import re
from collections import Counter
from pathlib import Path


REVIEW_DECISIONS_RE = re.compile(
    r"const\s+initialRevisionDecisions\s*=\s*(\{.*?\});",
    re.DOTALL,
)

REVIEW_SUGGESTIONS_RE = re.compile(
    r"const\s+reviewSuggestions\s*=\s*(\{.*?\});",
    re.DOTALL,
)


def load_json(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    return json.loads(text)


def extract_js_object(text: str, regex: re.Pattern) -> dict | None:
    m = regex.search(text)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def parse_review_state_file(review_state_path: Path) -> dict:
    if not review_state_path.exists():
        return {}
    data = load_json(review_state_path)
    decisions = data.get("review_decisions", data)
    if isinstance(decisions, list):
        decisions = {key: value for key, value in decisions}
    return decisions if isinstance(decisions, dict) else {}


def parse_html_initial_decisions(html_path: Path) -> dict:
    text = html_path.read_text(encoding="utf-8")
    decisions = extract_js_object(text, REVIEW_DECISIONS_RE)
    if not isinstance(decisions, dict):
        return {}
    return decisions


def parse_html_review_suggestions(html_path: Path) -> dict:
    text = html_path.read_text(encoding="utf-8")
    suggestions = extract_js_object(text, REVIEW_SUGGESTIONS_RE)
    if not isinstance(suggestions, dict):
        return {}
    return suggestions


def summarize_decisions(decisions: dict) -> dict:
    counts = Counter()
    for value in decisions.values():
        status = value.get("status") if isinstance(value, dict) else value
        status = (status or "").strip().lower()
        if status == "accepted":
            counts["accepted"] += 1
        elif status == "rejected":
            counts["rejected"] += 1
        else:
            counts["unknown"] += 1
    counts["total"] = sum(counts.values())
    return counts


def find_case_dirs(root: Path):
    if root.is_file():
        return [root.parent]
    if (root / "causal_graph.html").exists() and (root / "updated_causal_graph.html").exists():
        return [root]
    return sorted({p.parent for p in root.rglob("causal_graph.html") if p.is_file()})


def check_case_dir(case_dir: Path) -> dict:
    original_html = case_dir / "causal_graph.html"
    updated_html = case_dir / "updated_causal_graph.html"
    review_state = case_dir / "updated_causal_graph_review_state.json"

    result = {
        "case_dir": str(case_dir),
        "has_original_html": original_html.exists(),
        "has_updated_html": updated_html.exists(),
        "has_review_state": review_state.exists(),
        "decisions_source": None,
        "accepted": 0,
        "rejected": 0,
        "unknown": 0,
        "review_suggestions": {},
    }

    if result["has_review_state"]:
        decisions = parse_review_state_file(review_state)
        counts = summarize_decisions(decisions)
        result.update({
            "decisions_source": "json",
            "accepted": counts["accepted"],
            "rejected": counts["rejected"],
            "unknown": counts["unknown"],
            "total_decisions": counts["total"],
        })
    elif result["has_updated_html"]:
        decisions = parse_html_initial_decisions(updated_html)
        counts = summarize_decisions(decisions)
        result.update({
            "decisions_source": "html",
            "accepted": counts["accepted"],
            "rejected": counts["rejected"],
            "unknown": counts["unknown"],
            "total_decisions": counts["total"],
        })
    else:
        result.update({
            "decisions_source": None,
            "total_decisions": 0,
        })

    if result["has_updated_html"]:
        suggestions = parse_html_review_suggestions(updated_html)
        if isinstance(suggestions, dict):
            result["review_suggestions"] = {k: len(v or []) for k, v in suggestions.items() if isinstance(v, list)}

    return result


def format_result(result: dict) -> str:
    lines = [f"Case: {result['case_dir']}"]
    lines.append(f"  causal_graph.html: {'yes' if result['has_original_html'] else 'no'}")
    lines.append(f"  updated_causal_graph.html: {'yes' if result['has_updated_html'] else 'no'}")
    lines.append(f"  updated_causal_graph_review_state.json: {'yes' if result['has_review_state'] else 'no'}")
    if result["decisions_source"]:
        lines.append(f"  decisions source: {result['decisions_source']}")
        lines.append(f"  accepted: {result['accepted']}, rejected: {result['rejected']}, unknown: {result['unknown']}")
        lines.append(f"  total decisions: {result.get('total_decisions', 0)}")
    else:
        lines.append("  decisions: none found")
    if result["review_suggestions"]:
        lines.append("  reviewSuggestions counts:")
        for key, count in sorted(result["review_suggestions"].items()):
            lines.append(f"    {key}: {count}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare same-folder causal graph outputs and infer revision acceptance.")
    parser.add_argument("paths", nargs="+", help="Case folder or run root to inspect.")
    args = parser.parse_args()

    all_results = []
    for path in args.paths:
        root = Path(path)
        if not root.exists():
            print(f"ERROR: path not found: {root}")
            continue
        case_dirs = find_case_dirs(root)
        if not case_dirs:
            print(f"WARNING: no case dirs found under {root}")
            continue
        for case_dir in case_dirs:
            all_results.append(check_case_dir(case_dir))

    for result in all_results:
        print(format_result(result))
        print("-")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
