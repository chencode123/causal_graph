"""Restore visible node-revision highlights in causal-graph HTML files.

Some generated interactive graph files retain accepted revision decisions but
render ``node.added-highlight`` with a transparent, zero-width border.  This
utility restores the original visible style without changing the embedded
graph, review suggestions, revision decisions, or any JSON graph file.

An input may be an HTML file, its sibling JSON file, or a directory.  When a
JSON file is supplied, the HTML file with the same stem is selected.

Examples
--------
Preview one accept-all graph::

    python scripts/restore_causal_graph_html_highlights.py \
        runs/stability_test/rounds/round_1/batch_1/1/updated_causal_graph_accept_all.json

Apply the repair and retain a backup::

    python scripts/restore_causal_graph_html_highlights.py \
        runs/stability_test/rounds/round_1/batch_1/1/updated_causal_graph_accept_all.json \
        --write --backup-suffix .before_highlight_restore.bak
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Iterable


OFFICIAL_GRAPH_HTML_NAMES = {
    "causal_graph.html",
    "updated_causal_graph.html",
    "updated_causal_graph_accept_all.html",
}

NODE_HIGHLIGHT_BLOCK = re.compile(
    r'(?P<prefix>selector:\s*"node\.added-highlight"\s*,\s*'
    r'style:\s*\{)'
    r'(?P<body>.*?)'
    r'(?P<suffix>\}\s*\}\s*,)',
    re.DOTALL,
)
SELECTED_HIGHLIGHT_BLOCK = re.compile(
    r'(?P<prefix>selector:\s*"\.added-highlight:selected"\s*,\s*'
    r'style:\s*\{)'
    r'(?P<body>.*?)'
    r'(?P<suffix>\}\s*\}\s*,?)',
    re.DOTALL,
)
INITIAL_DECISIONS_PATTERN = re.compile(
    r"const\s+initialRevisionDecisions\s*=\s*(?P<payload>.*?)\s*;",
    re.DOTALL,
)

VISIBLE_STYLE_BODY = """
            "border-width": 3,
            "border-color": "#ff4d4f",
            "border-style": "solid"
          """

VISIBLE_SELECTED_STYLE_BODY = """
            "border-width": 3,
            "border-color": "#ff4d4f",
            "line-color": "#dc2626",
            "target-arrow-color": "#dc2626"
          """


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _discover_html_files(
    paths: Iterable[Path], *, only_accept_all: bool = False
) -> list[Path]:
    discovered: set[Path] = set()
    for path in paths:
        resolved = path.resolve()
        if resolved.is_file():
            suffix = resolved.suffix.lower()
            if suffix in {".html", ".htm"}:
                discovered.add(resolved)
            elif suffix == ".json":
                html_path = resolved.with_suffix(".html")
                if not html_path.is_file():
                    raise FileNotFoundError(
                        f"Sibling HTML file does not exist for JSON input: {html_path}"
                    )
                discovered.add(html_path)
            else:
                raise ValueError(f"Unsupported input file type: {resolved}")
            continue

        if not resolved.is_dir():
            raise FileNotFoundError(f"Path does not exist: {resolved}")
        for candidate in resolved.rglob("*.html"):
            candidate_name = candidate.name.lower()
            if only_accept_all:
                if candidate_name == "updated_causal_graph_accept_all.html":
                    discovered.add(candidate.resolve())
            elif candidate_name in OFFICIAL_GRAPH_HTML_NAMES:
                discovered.add(candidate.resolve())

    return sorted(discovered, key=lambda item: str(item).lower())


def _read_revision_decisions(html: str) -> tuple[int, int]:
    match = INITIAL_DECISIONS_PATTERN.search(html)
    if match is None:
        return 0, 0
    try:
        payload = json.loads(match.group("payload"))
    except json.JSONDecodeError:
        return 0, 0
    if not isinstance(payload, dict):
        return 0, 0

    accepted = 0
    for value in payload.values():
        if isinstance(value, str) and value.lower() == "accepted":
            accepted += 1
        elif isinstance(value, dict) and str(value.get("status", "")).lower() == "accepted":
            accepted += 1
    return len(payload), accepted


def restore_html_text(html: str) -> tuple[str, dict[str, Any]]:
    decision_count, accepted_count = _read_revision_decisions(html)
    repaired = html
    style_changes: list[dict[str, str]] = []

    style_specs = (
        ("node.added-highlight", NODE_HIGHLIGHT_BLOCK, VISIBLE_STYLE_BODY),
        (
            ".added-highlight:selected",
            SELECTED_HIGHLIGHT_BLOCK,
            VISIBLE_SELECTED_STYLE_BODY,
        ),
    )
    for style_name, pattern, replacement_body in style_specs:
        matches = list(pattern.finditer(repaired))
        if not matches:
            return html, {
                "status": "skipped",
                "reason": f"{style_name} style block not found",
                "revision_decisions": decision_count,
                "accepted_revision_decisions": accepted_count,
            }
        if len(matches) != 1:
            return html, {
                "status": "invalid",
                "reason": f"expected one {style_name} block, found {len(matches)}",
                "revision_decisions": decision_count,
                "accepted_revision_decisions": accepted_count,
            }

        match = matches[0]
        body = match.group("body")
        visible_width = re.search(r'"border-width"\s*:\s*[1-9][0-9]*', body)
        visible_color = re.search(
            r'"border-color"\s*:\s*"(?!transparent)[^"]+"',
            body,
            re.IGNORECASE,
        )
        if visible_width and visible_color:
            continue

        repaired = (
            repaired[: match.start()]
            + match.group("prefix")
            + replacement_body
            + match.group("suffix")
            + repaired[match.end() :]
        )
        style_changes.append(
            {
                "selector": style_name,
                "old_style": body.strip(),
                "new_style": replacement_body.strip(),
            }
        )

    return repaired, {
        "status": "changed" if style_changes else "unchanged",
        "reason": (
            "visible highlight styles restored"
            if style_changes
            else "node highlight styles are already visible"
        ),
        "style_changes": style_changes,
        "revision_decisions": decision_count,
        "accepted_revision_decisions": accepted_count,
    }


def _atomic_write(path: Path, content: str) -> None:
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(
            file_descriptor, "w", encoding="utf-8", newline=""
        ) as handle:
            handle.write(content)
        os.replace(temporary_name, path)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Restore visible red node-revision highlights in graph HTML files."
    )
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="HTML file, sibling JSON graph file, or directory to inspect.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Apply changes. Without this flag, only a dry run is performed.",
    )
    parser.add_argument(
        "--only-accept-all",
        action="store_true",
        help=(
            "When scanning directories, include only "
            "updated_causal_graph_accept_all.html files."
        ),
    )
    parser.add_argument(
        "--backup-suffix",
        default="",
        help="Optional backup suffix. Existing backups are never overwritten.",
    )
    parser.add_argument("--audit", type=Path, help="Optional JSON audit output path.")
    args = parser.parse_args()

    files = _discover_html_files(
        args.paths, only_accept_all=args.only_accept_all
    )
    records: list[dict[str, Any]] = []

    for path in files:
        record: dict[str, Any] = {"path": str(path)}
        try:
            original = path.read_text(encoding="utf-8")
            repaired, details = restore_html_text(original)
            record.update(details)
            record["before_sha256"] = _sha256_text(original)
            record["after_sha256"] = _sha256_text(repaired)
            record["written"] = False

            if args.write and details["status"] == "changed":
                if args.backup_suffix:
                    backup_path = path.with_name(path.name + args.backup_suffix)
                    if backup_path.exists():
                        raise FileExistsError(f"Backup already exists: {backup_path}")
                    shutil.copy2(path, backup_path)
                    record["backup_path"] = str(backup_path)
                _atomic_write(path, repaired)
                record["written"] = True
        except Exception as exc:
            record.update({"status": "error", "reason": str(exc), "written": False})
        records.append(record)

    counts: dict[str, int] = {}
    for record in records:
        status = str(record.get("status", "unknown"))
        counts[status] = counts.get(status, 0) + 1

    audit = {
        "mode": "write" if args.write else "dry-run",
        "only_accept_all": args.only_accept_all,
        "visible_node_highlight_style": {
            "border_width": 3,
            "border_color": "#ff4d4f",
            "border_style": "solid",
        },
        "visible_selected_highlight_style": {
            "border_width": 3,
            "border_color": "#ff4d4f",
            "line_color": "#dc2626",
            "target_arrow_color": "#dc2626",
        },
        "files_discovered": len(files),
        "counts": counts,
        "records": records,
    }

    if args.audit:
        audit_path = args.audit.resolve()
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.write_text(
            json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 1 if counts.get("error", 0) or counts.get("invalid", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
