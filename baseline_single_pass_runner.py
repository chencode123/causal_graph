from __future__ import annotations

"""Run the schema-constrained single-pass LLM graph-extraction baseline.

Each independent run starts from the same frozen case inputs and makes exactly
one LLM call per report. Outputs are written to ``OUTPUT_ROOT/run_XX`` so the
source corpus is never modified.
"""

from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import shutil

from dotenv import load_dotenv

from pipeline.entrypoint import run_single_or_multi_batch
from pipeline.step_registry import STEP_REGISTRY
from utils.batch_pipeline_utils import (
    PipelineConfig,
    iter_target_batch_dirs,
    prepare_round_output_dirs,
)
from utils.causal_graph_interactive_pkg.causal_graph_interactive import (
    draw_causal_graph_interactive_from_json,
)


PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(dotenv_path=PROJECT_ROOT / ".env_openai", override=True)


# ============================================================================
# EXPERIMENT CONFIGURATION
# ============================================================================

# Use a frozen corpus containing identify_incident_output.json in each case.
# For the final paper, point this to the held-out test corpus only.
SOURCE_DIR = PROJECT_ROOT / "runs" / "stability_test" / "batched_reports"

# A fresh, separate directory is created for each independent run.
OUTPUT_ROOT = PROJECT_ROOT / "runs" / "single_pass_baseline_all_batches"

EXECUTION_MODE = "batch"  # "batch" or "responses"
RESPONSES_ASYNC_ENABLED = False
UPLOAD_ALL_FILES_IN_ONE_BATCH = True

# Folder names to include within each batch, or None for every case in SOURCE_DIR.
TARGET_CASES: tuple[str, ...] | None = None

# A single-pass method may still be repeated multiple times for stability.
INDEPENDENT_RUNS = 5
START_RUN = 1
RESUME = True
PARALLEL_INDEPENDENT_RUNS = True
# Preserve completed runs by default. Set True only when intentionally replacing
# the exact run number and after closing any open HTML/file handles.
OVERWRITE_EXISTING_RUN = False

MODEL_NAME = "gpt-5.4-2026-03-05"
REASONING_EFFORT = "medium"
VERBOSITY = "medium"
FORCE_JSON_OUTPUT = True
SAVE_RAW_RESPONSE = True
MAX_OUTPUT_TOKENS = 32000
CALL_SLEEP_SECONDS = 0.0

HAZARDS_JSON_PATH = PROJECT_ROOT / "prompt" / "hazards_consequence.json"
CONDITIONS_JSON_PATH = PROJECT_ROOT / "prompt" / "conditions.json"
ACCIDENT_SCENARIO_SCHEMA_PATH = (
    PROJECT_ROOT / "scheme" / "accident_scenario_schema.json"
)
STRUCTURED_OUTPUT_SCHEMA_PATH = (
    PROJECT_ROOT / "scheme" / "baseline_causal_graph_output_schema.json"
)
DIRECT_GRAPH_OUTPUT_SCHEMA = json.loads(
    STRUCTURED_OUTPUT_SCHEMA_PATH.read_text(encoding="utf-8")
)

ACTIVE_STEP_KEYS = ("direct_graph_extraction",)


def _has_complete_audit(run_dir: Path) -> bool:
    """Return True only when the saved audit confirms a fully completed run."""
    audit_path = run_dir / "single_pass_audit.json"
    if not audit_path.is_file():
        return False
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        expected = int(audit["expected_cases"])
        return (
            expected > 0
            and int(audit["valid_outputs"]) == expected
            and int(audit["valid_html_outputs"]) == expected
            and not audit.get("missing_outputs")
            and not audit.get("invalid_outputs")
            and not audit.get("missing_html_outputs")
        )
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return False


def _safe_reset_run_dir(run_dir: Path) -> None:
    """Remove only a direct child of OUTPUT_ROOT, never the corpus or workspace."""
    output_root = OUTPUT_ROOT.resolve()
    resolved = run_dir.resolve()
    if resolved.parent != output_root:
        raise ValueError(f"Refusing to reset unexpected run directory: {resolved}")
    if resolved.exists():
        if not OVERWRITE_EXISTING_RUN:
            raise FileExistsError(
                f"Run directory already exists: {resolved}. "
                "Choose a new START_RUN, set RESUME=True to skip it, or explicitly "
                "set OVERWRITE_EXISTING_RUN=True after closing open files."
            )
        try:
            shutil.rmtree(resolved)
        except PermissionError as exc:
            raise PermissionError(
                f"Cannot replace locked run directory: {resolved}. Close any open "
                "HTML files, Explorer previews, editors, or sync clients, then retry; "
                "alternatively choose a new START_RUN."
            ) from exc
    resolved.mkdir(parents=True, exist_ok=True)


def _prepare_run(run_index: int) -> tuple[Path, dict[Path, Path]] | None:
    run_dir = OUTPUT_ROOT / f"run_{run_index:02d}"
    if run_dir.exists() and RESUME:
        if _has_complete_audit(run_dir):
            print(
                f"Run {run_index:02d} has a complete audit; "
                "skipping the completed run."
            )
            return None
        raise FileExistsError(
            f"Run directory exists but is not audit-complete: {run_dir.resolve()}. "
            "It will not be skipped or overwritten automatically. Inspect the run, "
            "then choose a different START_RUN or explicitly enable overwrite."
        )

    _safe_reset_run_dir(run_dir)
    shutil.copy2(
        STRUCTURED_OUTPUT_SCHEMA_PATH,
        run_dir / "structured_output_schema.json",
    )
    source_batches = iter_target_batch_dirs(SOURCE_DIR)
    excluded_filenames = {
        STEP_REGISTRY[step_key]["output_file"] for step_key in ACTIVE_STEP_KEYS
    }

    source_folder_map: dict[Path, Path] = {}
    for source_batch in source_batches:
        target_batch = run_dir / source_batch.name
        source_folder_map.update(
            prepare_round_output_dirs(
                source_batch_dir=source_batch,
                target_batch_dir=target_batch,
                target_cases=TARGET_CASES,
                excluded_filenames=excluded_filenames,
            )
        )

    if not source_folder_map:
        raise RuntimeError(f"No runnable cases found under {SOURCE_DIR}")
    return run_dir, source_folder_map


def _audit_run_outputs(run_dir: Path, expected_folders: tuple[Path, ...]) -> None:
    required_top_level_fields = {
        "hazard_consequence_node",
        "entity_nodes",
        "condition_nodes",
        "event_nodes",
        "edges",
    }
    missing: list[str] = []
    invalid: list[str] = []
    missing_html: list[str] = []
    html_outputs_present = 0
    valid_html_outputs = 0
    cyclic_graphs: list[str] = []
    cycle_evaluable_graphs = 0

    for folder in expected_folders:
        graph_path = folder / "causal_graph.json"
        relative = str(folder.relative_to(run_dir))
        if not graph_path.exists():
            missing.append(relative)
            continue
        duplicate_json_keys: dict[str, int] = {}

        def track_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
            parsed: dict[str, object] = {}
            for key, value in pairs:
                if key in parsed:
                    duplicate_json_keys[key] = duplicate_json_keys.get(key, 0) + 1
                parsed[key] = value
            return parsed

        try:
            payload = json.loads(
                graph_path.read_text(encoding="utf-8"),
                object_pairs_hook=track_duplicate_keys,
            )
        except (OSError, json.JSONDecodeError) as exc:
            invalid.append(f"{relative}: invalid JSON ({exc})")
            continue
        if not isinstance(payload, dict):
            invalid.append(f"{relative}: top-level JSON must be an object")
            continue
        absent = sorted(required_top_level_fields - set(payload))
        if absent:
            invalid.append(f"{relative}: missing fields {absent}")
            continue

        graph_errors: list[str] = []
        if duplicate_json_keys:
            details = ", ".join(
                f"{key!r} ({count} duplicate occurrence(s))"
                for key, count in sorted(duplicate_json_keys.items())
            )
            graph_errors.append(f"duplicate JSON keys detected: {details}")
        node_groups: dict[str, list[dict]] = {}
        for key in (
            "hazard_consequence_node",
            "entity_nodes",
            "condition_nodes",
            "event_nodes",
        ):
            group = payload.get(key)
            if not isinstance(group, list) or not all(isinstance(node, dict) for node in group):
                graph_errors.append(f"{key} must be a list of objects")
                node_groups[key] = []
            else:
                node_groups[key] = group

        hazards = node_groups["hazard_consequence_node"]
        if len(hazards) != 1:
            graph_errors.append("hazard_consequence_node must contain exactly one node")
        elif hazards[0].get("node_id") != "H1":
            graph_errors.append('the hazard consequence node must use node_id "H1"')

        all_nodes = [node for group in node_groups.values() for node in group]
        node_ids = [str(node.get("node_id") or "").strip() for node in all_nodes]
        node_types = {
            str(node.get("node_id") or "").strip(): str(node.get("node_type") or "").strip()
            for node in all_nodes
            if str(node.get("node_id") or "").strip()
        }
        if any(not node_id for node_id in node_ids):
            graph_errors.append("every node must have a non-empty node_id")
        if len(node_ids) != len(set(node_ids)):
            graph_errors.append("node_id values must be unique")

        edges = payload.get("edges")
        if not isinstance(edges, list) or not all(isinstance(edge, dict) for edge in edges):
            graph_errors.append("edges must be a list of objects")
            edges = []

        valid_node_ids = set(node_ids)
        edge_keys: list[tuple[str, str, str]] = []
        incoming = {node_id: 0 for node_id in valid_node_ids}
        outgoing = {node_id: 0 for node_id in valid_node_ids}
        adjacency = {node_id: set() for node_id in valid_node_ids}
        for edge in edges:
            source = str(edge.get("source") or "").strip()
            target = str(edge.get("target") or "").strip()
            relation = str(edge.get("relation") or "").strip()
            edge_keys.append((source, target, relation))
            if relation not in {"has", "enables"}:
                graph_errors.append(f"unsupported relation: {relation!r}")
            if source not in valid_node_ids or target not in valid_node_ids:
                graph_errors.append(f"edge has unknown endpoint: {source}->{target}")
                continue
            if source == target:
                graph_errors.append(f"self-loop: {source}")
            endpoint_types = (node_types.get(source), node_types.get(target))
            allowed_types = {
                "has": {("Entity", "Entity"), ("Entity", "Condition")},
                "enables": {
                    ("Event", "Event"),
                    ("Event", "HazardConsequence"),
                    ("Entity", "Event"),
                    ("Condition", "Event"),
                    ("Condition", "HazardConsequence"),
                },
            }
            if relation in allowed_types and endpoint_types not in allowed_types[relation]:
                graph_errors.append(
                    f"invalid {relation} endpoint types: {source}({endpoint_types[0]})"
                    f"->{target}({endpoint_types[1]})"
                )
            outgoing[source] += 1
            incoming[target] += 1
            adjacency[source].add(target)
        if len(edge_keys) != len(set(edge_keys)):
            graph_errors.append("duplicate edges are not allowed")

        if "H1" in valid_node_ids:
            if incoming["H1"] < 1:
                graph_errors.append("H1 must have at least one incoming edge")
            if outgoing["H1"] != 0:
                graph_errors.append("H1 must not have outgoing edges")
        for node_id in valid_node_ids - {"H1"}:
            if outgoing[node_id] < 1:
                graph_errors.append(f"non-hazard node has no outgoing edge: {node_id}")
        for condition in node_groups["condition_nodes"]:
            node_id = str(condition.get("node_id") or "").strip()
            if node_id and (incoming[node_id] < 1 or outgoing[node_id] < 1):
                graph_errors.append(
                    f"Condition must have incoming and outgoing edges: {node_id}"
                )

        visiting: set[str] = set()
        visited: set[str] = set()

        def has_cycle(node_id: str) -> bool:
            if node_id in visiting:
                return True
            if node_id in visited:
                return False
            visiting.add(node_id)
            if any(has_cycle(target) for target in adjacency.get(node_id, ())):
                return True
            visiting.remove(node_id)
            visited.add(node_id)
            return False

        cycle_evaluable_graphs += 1
        if any(has_cycle(node_id) for node_id in valid_node_ids if node_id not in visited):
            cyclic_graphs.append(relative)
        if graph_errors:
            invalid.append(f"{relative}: " + "; ".join(graph_errors))
        html_exists = (folder / "causal_graph.html").exists()
        if html_exists:
            html_outputs_present += 1
            if not graph_errors:
                valid_html_outputs += 1
        else:
            missing_html.append(relative)

    summary = {
        "run_dir": str(run_dir),
        "expected_cases": len(expected_folders),
        "valid_outputs": len(expected_folders) - len(missing) - len(invalid),
        "missing_outputs": missing,
        "invalid_outputs": invalid,
        "html_outputs_present": html_outputs_present,
        "valid_html_outputs": valid_html_outputs,
        "missing_html_outputs": missing_html,
        "cyclic_graphs": cyclic_graphs,
        "cycle_evaluable_graphs": cycle_evaluable_graphs,
        "cycle_rate": (
            len(cyclic_graphs) / cycle_evaluable_graphs
            if cycle_evaluable_graphs
            else None
        ),
        "model": MODEL_NAME,
        "reasoning_effort": REASONING_EFFORT,
        "verbosity": VERBOSITY,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "force_json_output": FORCE_JSON_OUTPUT,
        "output_format": "json_schema",
        "strict_structured_output": True,
        "structured_output_schema": str(STRUCTURED_OUTPUT_SCHEMA_PATH),
        "structured_output_schema_sha256": hashlib.sha256(
            STRUCTURED_OUTPUT_SCHEMA_PATH.read_bytes()
        ).hexdigest(),
        "active_step_keys": list(ACTIVE_STEP_KEYS),
    }
    audit_path = run_dir / "single_pass_audit.json"
    audit_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"Audit for {run_dir.name}: valid={summary['valid_outputs']}/"
        f"{summary['expected_cases']}, html={summary['valid_html_outputs']}/"
        f"{summary['expected_cases']}, missing={len(missing)}, invalid={len(invalid)}"
    )


def _generate_baseline_html(expected_folders: tuple[Path, ...]) -> None:
    """Render the direct graph without invoking multi-stage graph rebuilding."""
    ok = 0
    skipped = 0
    failed = 0
    for folder in expected_folders:
        graph_path = folder / "causal_graph.json"
        if not graph_path.exists():
            skipped += 1
            continue
        error_path = folder / "direct_graph_extraction_postprocess_error.txt"
        try:
            draw_causal_graph_interactive_from_json(
                identify_accident_scenario=graph_path,
                causal_edge_linking=graph_path,
                save_path=folder / "causal_graph.html",
                accident_scenario_schema=ACCIDENT_SCENARIO_SCHEMA_PATH,
                review_causal_graph=None,
                revision_decisions=None,
                case_id=folder.name,
            )
            if error_path.exists():
                error_path.unlink()
            ok += 1
        except Exception as exc:
            error_path.write_text(
                f"HTML generation failed: {exc}\n",
                encoding="utf-8",
            )
            failed += 1
    print(f"Baseline HTML postprocess: ok={ok}, skipped={skipped}, fail={failed}")


def _execute_prepared_run(
    *,
    base_config: PipelineConfig,
    run_index: int,
    run_dir: Path,
    source_folder_map: dict[Path, Path],
) -> None:
    print(f"\n=== Single-pass baseline run {run_index:02d} ===")
    print(f"Cases: {len(source_folder_map)}")
    print(f"Output: {run_dir}")

    run_config = replace(
        base_config,
        base_dir=run_dir,
        source_folder_map=source_folder_map,
    )
    run_single_or_multi_batch(
        config=run_config,
        run_base_dir=run_dir,
        execution_mode=EXECUTION_MODE,
        upload_all_files_in_one_batch=UPLOAD_ALL_FILES_IN_ONE_BATCH,
    )
    expected_folders = tuple(source_folder_map)
    _generate_baseline_html(expected_folders)
    _audit_run_outputs(run_dir, expected_folders)


def main() -> None:
    if not SOURCE_DIR.exists():
        raise FileNotFoundError(f"SOURCE_DIR does not exist: {SOURCE_DIR}")
    if INDEPENDENT_RUNS < 1:
        raise ValueError("INDEPENDENT_RUNS must be at least 1")

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    base_config = PipelineConfig(
        base_dir=OUTPUT_ROOT,
        model_name=MODEL_NAME,
        reasoning_effort=REASONING_EFFORT,
        verbosity=VERBOSITY,
        force_json_output=FORCE_JSON_OUTPUT,
        save_raw_response=SAVE_RAW_RESPONSE,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        call_sleep_seconds=CALL_SLEEP_SECONDS,
        remove_shortcut_edges=False,
        hazards_json_path=HAZARDS_JSON_PATH,
        conditions_json_path=CONDITIONS_JSON_PATH,
        use_few_shot=False,
        active_step_keys=ACTIVE_STEP_KEYS,
        responses_async_enabled=RESPONSES_ASYNC_ENABLED,
        enable_local_postprocess=False,
        structured_output_schemas={
            "direct_graph_extraction": DIRECT_GRAPH_OUTPUT_SCHEMA,
        },
    )

    prepared_runs: list[tuple[int, Path, dict[Path, Path]]] = []
    for offset in range(INDEPENDENT_RUNS):
        run_index = START_RUN + offset
        prepared = _prepare_run(run_index)
        if prepared is None:
            continue
        run_dir, source_folder_map = prepared
        prepared_runs.append((run_index, run_dir, source_folder_map))

    if PARALLEL_INDEPENDENT_RUNS and len(prepared_runs) > 1:
        print(f"Submitting {len(prepared_runs)} independent runs in parallel.")
        with ThreadPoolExecutor(max_workers=len(prepared_runs)) as executor:
            futures = {
                executor.submit(
                    _execute_prepared_run,
                    base_config=base_config,
                    run_index=run_index,
                    run_dir=run_dir,
                    source_folder_map=source_folder_map,
                ): run_index
                for run_index, run_dir, source_folder_map in prepared_runs
            }
            for future in as_completed(futures):
                run_index = futures[future]
                future.result()
                print(f"Single-pass baseline run {run_index:02d} completed.")
    else:
        for run_index, run_dir, source_folder_map in prepared_runs:
            _execute_prepared_run(
                base_config=base_config,
                run_index=run_index,
                run_dir=run_dir,
                source_folder_map=source_folder_map,
            )

    print("Done.")


if __name__ == "__main__":
    main()
