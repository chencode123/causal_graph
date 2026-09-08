"""Repair embedded node-label options in interactive causal-graph HTML files.

The accident-scenario schema stores some alternatives as pipe-delimited text.
Older HTML generation treated an entire value such as
``InitiatingEvent | MechanicalFailure | ...`` as one label option. This tool
replaces only the embedded ``schemaForm`` JSON object. It preserves the graph
snapshot, review suggestions, revision decisions, and every other HTML byte.

Examples
--------
Preview the current Round 4 repair without writing files::

    python scripts/repair_causal_graph_html_schema_options.py \
        runs/stability_test/rounds_with_few_shot/round_4

Apply the repair and write an audit JSON file::

    python scripts/repair_causal_graph_html_schema_options.py \
        runs/stability_test/rounds_with_few_shot/round_4 \
        --write --audit outputs/round_4_html_schema_repair_audit.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCHEMA = PROJECT_ROOT / "scheme" / "accident_scenario_schema.json"
OFFICIAL_GRAPH_HTML_NAMES = {
    "causal_graph.html",
    "updated_causal_graph.html",
    "updated_causal_graph_accept_all.html",
}
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SCHEMA_FORM_PATTERN = re.compile(
    r"(?P<prefix>const\s+schemaForm\s*=\s*)"
    r"(?P<payload>.*?)"
    r"(?P<suffix>;\s*const\s+reviewSuggestions\s*=)",
    re.DOTALL,
)
ELEMENTS_PATTERN = re.compile(
    r"const\s+elements\s*=\s*(?P<payload>.*?);\s*const\s+schemaForm\s*=",
    re.DOTALL,
)


def _load_schema_options(schema_path: Path) -> dict[str, Any]:
    from utils.causal_graph_interactive_pkg.causal_graph_interactive import (
        _build_schema_form_options,
    )

    payload = json.loads(schema_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"Schema must contain a JSON object: {schema_path}")
    options = _build_schema_form_options(payload)
    combined = [label for label in options.get("labels", []) if "|" in label]
    if combined:
        raise ValueError(f"Pipe-delimited labels remain after expansion: {combined}")
    return options


def _discover_html_files(paths: Iterable[Path]) -> list[Path]:
    discovered: set[Path] = set()
    for path in paths:
        resolved = path.resolve()
        if resolved.is_file():
            if resolved.suffix.lower() in {".html", ".htm"}:
                discovered.add(resolved)
            continue
        if not resolved.is_dir():
            raise FileNotFoundError(f"Path does not exist: {path}")
        for candidate in resolved.rglob("*.html"):
            if candidate.name.lower() in OFFICIAL_GRAPH_HTML_NAMES:
                discovered.add(candidate.resolve())
    return sorted(discovered, key=lambda item: str(item).lower())


def repair_html_text(
    html: str,
    schema_options: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    match = SCHEMA_FORM_PATTERN.search(html)
    if match is None:
        return html, {
            "status": "skipped",
            "reason": "embedded schemaForm marker not found",
        }

    try:
        old_options = json.loads(match.group("payload"))
    except json.JSONDecodeError as exc:
        return html, {
            "status": "invalid",
            "reason": f"embedded schemaForm is not valid JSON: {exc}",
        }

    new_payload = json.dumps(schema_options, ensure_ascii=False, separators=(",", ":"))
    repaired = (
        html[: match.start()]
        + match.group("prefix")
        + new_payload
        + match.group("suffix")
        + html[match.end() :]
    )

    missing_node_labels: list[str] = []
    elements_match = ELEMENTS_PATTERN.search(repaired)
    if elements_match is not None:
        try:
            elements = json.loads(elements_match.group("payload"))
            allowed_labels = set(schema_options.get("labels", []))
            missing_node_labels = sorted(
                {
                    str(node.get("data", {}).get("label", "")).strip()
                    for node in elements.get("nodes", [])
                    if isinstance(node, dict)
                    and str(node.get("data", {}).get("label", "")).strip()
                    and str(node.get("data", {}).get("label", "")).strip()
                    not in allowed_labels
                }
            )
        except (json.JSONDecodeError, AttributeError):
            missing_node_labels = ["<unable to audit embedded elements>"]

    changed = old_options != schema_options
    return repaired, {
        "status": "changed" if changed else "unchanged",
        "old_labels": old_options.get("labels", []) if isinstance(old_options, dict) else [],
        "new_labels": schema_options.get("labels", []),
        "missing_node_labels_after_repair": missing_node_labels,
    }


def _atomic_write(path: Path, content: str) -> None:
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        os.replace(temp_name, path)
    except Exception:
        try:
            Path(temp_name).unlink(missing_ok=True)
        finally:
            raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Repair pipe-delimited node-label options in causal-graph HTML files."
    )
    parser.add_argument("paths", nargs="+", type=Path, help="HTML file or root directory.")
    parser.add_argument(
        "--schema",
        type=Path,
        default=DEFAULT_SCHEMA,
        help="Accident-scenario schema used to rebuild the form options.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Apply changes. Without this flag, only a dry-run audit is performed.",
    )
    parser.add_argument(
        "--backup-suffix",
        default="",
        help="Optional backup suffix, for example .bak. Existing backups are not overwritten.",
    )
    parser.add_argument("--audit", type=Path, help="Optional JSON audit output path.")
    args = parser.parse_args()

    schema_path = args.schema.resolve()
    schema_options = _load_schema_options(schema_path)
    files = _discover_html_files(args.paths)
    records: list[dict[str, Any]] = []

    for path in files:
        record: dict[str, Any] = {"path": str(path)}
        try:
            original = path.read_text(encoding="utf-8")
            repaired, details = repair_html_text(original, schema_options)
            record.update(details)
            if args.write and details["status"] == "changed":
                if args.backup_suffix:
                    backup_path = path.with_name(path.name + args.backup_suffix)
                    if backup_path.exists():
                        raise FileExistsError(f"Backup already exists: {backup_path}")
                    shutil.copy2(path, backup_path)
                    record["backup_path"] = str(backup_path)
                _atomic_write(path, repaired)
                record["written"] = True
            else:
                record["written"] = False
        except Exception as exc:
            record.update({"status": "error", "reason": str(exc), "written": False})
        records.append(record)

    counts: dict[str, int] = {}
    for record in records:
        status = str(record.get("status", "unknown"))
        counts[status] = counts.get(status, 0) + 1

    audit = {
        "mode": "write" if args.write else "dry-run",
        "schema_path": str(schema_path),
        "schema_sha256": hashlib.sha256(schema_path.read_bytes()).hexdigest(),
        "schema_form_options": schema_options,
        "files_discovered": len(files),
        "status_counts": counts,
        "records": records,
    }
    print(json.dumps({key: audit[key] for key in audit if key != "records"}, indent=2))

    if args.audit:
        audit_path = args.audit.resolve()
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Audit written to {audit_path}")

    return 1 if counts.get("error", 0) or counts.get("invalid", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
