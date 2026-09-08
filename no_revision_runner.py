from __future__ import annotations

"""Run the two-stage No Revision condition without modifying the frozen pipeline.

The existing ``edge_candidate_extraction`` prompt is reused unchanged.  Within
the isolated output tree, ``scenario_candidate_extraction_output.json`` is
copied byte-for-byte to the legacy prompt-input filename
``identify_accident_scenario_output.json``.  Candidate nodes and newly
generated candidate edges are then assembled deterministically without node or
edge validation, normalization, linking, shortcut removal, diagnosis, or
revision.

The default mode is ``dry-run`` and never calls the OpenAI API.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, Iterable

from dotenv import load_dotenv

from pipeline.entrypoint import run_pipeline_for_mode
from pipeline.io_utils import render_prompt
from pipeline.step_factory import build_pipeline
import utils.prompt_manager as prompt_manager
from utils.batch_pipeline_utils import PipelineConfig


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_SOURCE_ROOT = PROJECT_ROOT / "runs" / "stability_test" / "rounds"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "runs" / "stability_test" / "no_revision"
DEFAULT_EXCLUSION_FILE = PROJECT_ROOT / "evaluation_excluded_few_shot_cases.json"

MODEL_NAME = "gpt-5.4-2026-03-05"
REASONING_EFFORT = "medium"
VERBOSITY = "medium"
MAX_OUTPUT_TOKENS = 32000
EXPECTED_HELD_OUT_CASES = 112

EDGE_STEP_KEY = "edge_candidate_extraction"
EDGE_OUTPUT_NAME = "edge_candidate_extraction_output.json"
NAMED_EDGE_OUTPUT = "no_revision_edge_candidate_extraction_output.json"
GRAPH_OUTPUT_NAME = "no_revision_causal_graph.json"
CASE_AUDIT_NAME = "no_revision_case_audit.json"
PROMPT_OUTPUT_NAME = "no_revision_prompt.txt"

REQUIRED_SOURCE_FILES = (
    "identify_incident_output.json",
    "causal_narrative_extraction_output.json",
    "scenario_candidate_extraction_output.json",
)

NODE_GROUP_MAP = {
    "hazard_consequence_node": "hazard_consequence_node",
    "candidate_entity_nodes": "entity_nodes",
    "candidate_condition_nodes": "condition_nodes",
    "candidate_event_nodes": "event_nodes",
}

ALLOWED_ENDPOINT_TYPES = {
    "has": {("Entity", "Entity"), ("Entity", "Condition")},
    "enables": {
        ("Event", "Event"),
        ("Event", "HazardConsequence"),
        ("Entity", "Event"),
        ("Condition", "Event"),
        ("Condition", "HazardConsequence"),
    },
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return payload


def parse_rounds(value: str) -> tuple[int, ...]:
    try:
        rounds = tuple(sorted({int(item.strip()) for item in value.split(",") if item.strip()}))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("rounds must be comma-separated integers") from exc
    if not rounds or any(item < 1 for item in rounds):
        raise argparse.ArgumentTypeError("rounds must contain positive integers")
    return rounds


def load_exclusions(path: Path) -> set[str]:
    payload = load_json_object(path)
    values = payload.get("excluded_cases")
    if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
        raise ValueError(f"Invalid excluded_cases list in {path}")
    return {item.replace("\\", "/").strip("/") for item in values}


def discover_source_cases(
    source_root: Path,
    rounds: Iterable[int],
    exclusions: set[str],
    target_cases: set[str],
) -> list[tuple[int, str, Path]]:
    discovered: list[tuple[int, str, Path]] = []
    for round_index in rounds:
        round_dir = source_root / f"round_{round_index}"
        if not round_dir.is_dir():
            raise FileNotFoundError(f"Missing source round: {round_dir}")
        round_cases: list[tuple[int, str, Path]] = []
        for batch_dir in sorted(round_dir.glob("batch_*")):
            if not batch_dir.is_dir():
                continue
            for case_dir in sorted(
                path
                for path in batch_dir.iterdir()
                if path.is_dir() and not path.name.startswith("_")
            ):
                if not any((case_dir / marker).is_file() for marker in REQUIRED_SOURCE_FILES):
                    continue
                case_key = f"{batch_dir.name}/{case_dir.name}"
                if case_key in exclusions:
                    continue
                if target_cases and case_key not in target_cases:
                    continue
                missing = [name for name in REQUIRED_SOURCE_FILES if not (case_dir / name).is_file()]
                if missing:
                    raise FileNotFoundError(
                        f"Source case {case_key} in round_{round_index} lacks {missing}"
                    )
                round_cases.append((round_index, case_key, case_dir))
        if not round_cases:
            raise RuntimeError(f"No eligible cases found in {round_dir}")
        discovered.extend(round_cases)
    return discovered


def copy_exact(source: Path, target: Path, *, allow_replace: bool) -> None:
    data = source.read_bytes()
    if target.exists():
        if target.read_bytes() == data:
            return
        if not allow_replace:
            raise FileExistsError(
                f"Existing isolated input differs from its source: {target}. "
                "Use --refresh-inputs only after verifying the source change."
            )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def build_edge_step():
    steps = build_pipeline(
        hazards_json=PROJECT_ROOT / "prompt" / "hazards_consequence.json",
        conditions_json=PROJECT_ROOT / "prompt" / "conditions.json",
        use_few_shot=False,
        active_step_keys=(EDGE_STEP_KEY,),
    )
    if len(steps) != 1 or steps[0].key != EDGE_STEP_KEY:
        raise RuntimeError("Could not construct the existing edge candidate step")
    return steps[0]


def prepare_case(
    *,
    source_case: Path,
    target_case: Path,
    case_key: str,
    round_index: int,
    edge_step: Any,
    prompt_template: str,
    refresh_inputs: bool,
) -> dict[str, Any]:
    target_case.mkdir(parents=True, exist_ok=True)
    for name in REQUIRED_SOURCE_FILES:
        copy_exact(source_case / name, target_case / name, allow_replace=refresh_inputs)

    # The prompt and registry remain unchanged.  Only this isolated filename
    # alias changes the upstream node source for the ablation.
    candidate_nodes_path = target_case / "scenario_candidate_extraction_output.json"
    alias_path = target_case / "identify_accident_scenario_output.json"
    copy_exact(candidate_nodes_path, alias_path, allow_replace=refresh_inputs)

    vars_dict = edge_step.build_vars(target_case)
    rendered_prompt = render_prompt(prompt_template, vars_dict)
    (target_case / PROMPT_OUTPUT_NAME).write_text(rendered_prompt, encoding="utf-8")
    metadata = {
        "round": round_index,
        "case_key": case_key,
        "source_case": str(source_case.resolve()),
        "target_case": str(target_case.resolve()),
        "scenario_candidate_sha256": sha256_file(candidate_nodes_path),
        "node_input_alias_sha256": sha256_file(alias_path),
        "prompt_sha256": sha256_bytes(rendered_prompt.encode("utf-8")),
        "prompt_template_sha256": sha256_bytes(prompt_template.encode("utf-8")),
        "prompt_reused_unchanged": True,
        "few_shot_enabled": False,
    }
    write_json(target_case / "no_revision_input_audit.json", metadata)
    return metadata


def normalize_group(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError("Candidate node group must be an object or list of objects")
    return value


def build_candidate_graph(candidate_nodes: dict[str, Any], edge_output: dict[str, Any]) -> dict[str, Any]:
    candidate_edges = edge_output.get("candidate_edges")
    if not isinstance(candidate_edges, list) or not all(
        isinstance(item, dict) for item in candidate_edges
    ):
        raise ValueError("edge_candidate_extraction output must contain candidate_edges")
    graph: dict[str, Any] = {target: [] for target in NODE_GROUP_MAP.values()}
    for source_key, target_key in NODE_GROUP_MAP.items():
        graph[target_key] = normalize_group(candidate_nodes.get(source_key, []))
    graph["edges"] = candidate_edges
    return graph


def graph_has_cycle(adjacency: dict[str, set[str]]) -> bool:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> bool:
        if node_id in visiting:
            return True
        if node_id in visited:
            return False
        visiting.add(node_id)
        if any(visit(target) for target in adjacency.get(node_id, ())):
            return True
        visiting.remove(node_id)
        visited.add(node_id)
        return False

    return any(visit(node_id) for node_id in adjacency if node_id not in visited)


def audit_graph(graph: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    groups: dict[str, list[dict[str, Any]]] = {}
    for key in ("hazard_consequence_node", "entity_nodes", "condition_nodes", "event_nodes"):
        value = graph.get(key)
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            errors.append(f"{key} must be a list of objects")
            groups[key] = []
        else:
            groups[key] = value

    hazards = groups["hazard_consequence_node"]
    if len(hazards) != 1 or hazards[0].get("node_id") != "H1":
        errors.append("exactly one hazard consequence node with node_id H1 is required")

    nodes = [node for group in groups.values() for node in group]
    node_ids = [str(node.get("node_id") or "").strip() for node in nodes]
    if any(not node_id for node_id in node_ids):
        errors.append("all nodes must have non-empty node_id values")
    if len(node_ids) != len(set(node_ids)):
        errors.append("node_id values must be unique")
    node_types = {
        str(node.get("node_id") or "").strip(): str(node.get("node_type") or "").strip()
        for node in nodes
        if str(node.get("node_id") or "").strip()
    }
    valid_ids = set(node_ids)
    incoming = {node_id: 0 for node_id in valid_ids}
    outgoing = {node_id: 0 for node_id in valid_ids}
    adjacency = {node_id: set() for node_id in valid_ids}

    edges = graph.get("edges")
    if not isinstance(edges, list) or not all(isinstance(item, dict) for item in edges):
        errors.append("edges must be a list of objects")
        edges = []
    edge_keys: list[tuple[str, str, str]] = []
    for edge in edges:
        source = str(edge.get("source") or "").strip()
        target = str(edge.get("target") or "").strip()
        relation = str(edge.get("relation") or "").strip()
        edge_keys.append((source, target, relation))
        if relation not in ALLOWED_ENDPOINT_TYPES:
            errors.append(f"unsupported relation {relation!r}")
        if source not in valid_ids or target not in valid_ids:
            errors.append(f"unknown edge endpoint {source}->{target}")
            continue
        if source == target:
            errors.append(f"self-loop {source}->{target}")
        endpoint_types = (node_types.get(source), node_types.get(target))
        if relation in ALLOWED_ENDPOINT_TYPES and endpoint_types not in ALLOWED_ENDPOINT_TYPES[relation]:
            errors.append(
                f"invalid {relation} endpoint types {source}({endpoint_types[0]})"
                f"->{target}({endpoint_types[1]})"
            )
        incoming[target] += 1
        outgoing[source] += 1
        adjacency[source].add(target)
    if len(edge_keys) != len(set(edge_keys)):
        errors.append("duplicate edges are present")

    isolated = sorted(
        node_id for node_id in valid_ids if incoming[node_id] == 0 and outgoing[node_id] == 0
    )
    if isolated:
        warnings.append(f"isolated candidate nodes retained: {', '.join(isolated)}")
    if "H1" in valid_ids and incoming["H1"] == 0:
        warnings.append("H1 has no incoming candidate edge")
    cyclic = graph_has_cycle(adjacency)
    if cyclic:
        warnings.append("directed cycle detected and retained")

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "isolated_node_count": len(isolated),
        "isolated_node_ids": isolated,
        "has_directed_cycle": cyclic,
    }


def materialize_completed_case(target_case: Path) -> dict[str, Any] | None:
    edge_path = target_case / EDGE_OUTPUT_NAME
    if not edge_path.is_file():
        return None
    edge_output = load_json_object(edge_path)
    candidate_nodes = load_json_object(target_case / "scenario_candidate_extraction_output.json")
    graph = build_candidate_graph(candidate_nodes, edge_output)
    named_edge_path = target_case / NAMED_EDGE_OUTPUT
    shutil.copy2(edge_path, named_edge_path)
    graph_path = target_case / GRAPH_OUTPUT_NAME
    write_json(graph_path, graph)
    audit = audit_graph(graph)
    audit.update(
        {
            "edge_output_sha256": sha256_file(edge_path),
            "named_edge_output_sha256": sha256_file(named_edge_path),
            "graph_sha256": sha256_file(graph_path),
        }
    )
    write_json(target_case / CASE_AUDIT_NAME, audit)
    return audit


def write_summary_audits(
    *,
    output_root: Path,
    prepared: list[tuple[int, str, Path]],
    mode: str,
    exclusions: set[str],
    prompt_template: str,
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for round_index, case_key, target_case in prepared:
        record: dict[str, Any] = {
            "round": round_index,
            "case_key": case_key,
            "case_dir": str(target_case.resolve()),
            "prompt_present": (target_case / PROMPT_OUTPUT_NAME).is_file(),
            "edge_output_present": (target_case / EDGE_OUTPUT_NAME).is_file(),
            "graph_output_present": (target_case / GRAPH_OUTPUT_NAME).is_file(),
        }
        case_audit_path = target_case / CASE_AUDIT_NAME
        if case_audit_path.is_file():
            record["graph_audit"] = load_json_object(case_audit_path)
        records.append(record)

    per_round: dict[str, Any] = {}
    for round_index in sorted({item[0] for item in prepared}):
        round_records = [record for record in records if record["round"] == round_index]
        evaluable = [record for record in round_records if "graph_audit" in record]
        valid = [record for record in evaluable if record["graph_audit"]["valid"]]
        cyclic = [record for record in evaluable if record["graph_audit"]["has_directed_cycle"]]
        summary = {
            "round": round_index,
            "expected_cases": len(round_records),
            "edge_outputs_present": sum(record["edge_output_present"] for record in round_records),
            "graphs_present": len(evaluable),
            "valid_graphs": len(valid),
            "invalid_cases": [
                record["case_key"] for record in evaluable if not record["graph_audit"]["valid"]
            ],
            "cyclic_graphs": [record["case_key"] for record in cyclic],
            "cycle_rate": len(cyclic) / len(evaluable) if evaluable else None,
        }
        per_round[f"round_{round_index}"] = summary
        write_json(output_root / f"round_{round_index}" / "no_revision_audit.json", summary)

    summary = {
        "analysis": "No Revision two-stage candidate extraction",
        "mode": mode,
        "source_node_output": "scenario_candidate_extraction_output.json",
        "reused_prompt": str((PROJECT_ROOT / "prompt" / "edge_candidate_extraction.txt").resolve()),
        "prompt_template_sha256": sha256_bytes(prompt_template.encode("utf-8")),
        "new_prompt_created": False,
        "few_shot_enabled": False,
        "excluded_development_cases": sorted(exclusions),
        "prepared_case_run_count": len(records),
        "model": MODEL_NAME,
        "reasoning_effort": REASONING_EFFORT,
        "verbosity": VERBOSITY,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "postprocessing": "field renaming and graph assembly only; no validation or repair",
        "rounds": per_round,
        "cases": records,
    }
    write_json(output_root / "no_revision_audit.json", summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the two-stage No Revision condition from candidate nodes to candidate edges."
    )
    parser.add_argument(
        "--mode",
        choices=("dry-run", "responses", "batch"),
        default="dry-run",
        help="dry-run prepares prompts only and is the safe default.",
    )
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--rounds", type=parse_rounds, default=parse_rounds("1,2,3,4,5"))
    parser.add_argument(
        "--target-case",
        action="append",
        default=[],
        help="Optional normalized batch/case key. Repeat to select multiple cases.",
    )
    parser.add_argument("--exclude-file", type=Path, default=DEFAULT_EXCLUSION_FILE)
    parser.add_argument(
        "--include-development-cases",
        action="store_true",
        help="Include the 12 development cases. Intended only for explicit development runs.",
    )
    parser.add_argument(
        "--refresh-inputs",
        action="store_true",
        help="Replace differing isolated input copies. Generated edge outputs are preserved.",
    )
    parser.add_argument(
        "--allow-unexpected-case-count",
        action="store_true",
        help="Allow a non-targeted held-out run to contain other than 112 cases per round.",
    )
    parser.add_argument("--responses-max-concurrency", type=int, default=10)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    source_root = args.source_root.resolve()
    output_root = args.output_root.resolve()
    target_cases = {item.replace("\\", "/").strip("/") for item in args.target_case}
    exclusions = set() if args.include_development_cases else load_exclusions(args.exclude_file.resolve())
    source_cases = discover_source_cases(
        source_root,
        args.rounds,
        exclusions,
        target_cases,
    )

    if not target_cases and not args.include_development_cases and not args.allow_unexpected_case_count:
        for round_index in args.rounds:
            count = sum(1 for item in source_cases if item[0] == round_index)
            if count != EXPECTED_HELD_OUT_CASES:
                raise RuntimeError(
                    f"round_{round_index} contains {count} held-out cases; "
                    f"expected {EXPECTED_HELD_OUT_CASES}."
                )

    output_root.mkdir(parents=True, exist_ok=True)
    edge_step = build_edge_step()
    prompt_template = (PROJECT_ROOT / "prompt" / "edge_candidate_extraction.txt").read_text(
        encoding="utf-8"
    )
    prepared: list[tuple[int, str, Path]] = []
    for round_index, case_key, source_case in source_cases:
        batch_id, case_id = case_key.split("/", 1)
        target_case = output_root / f"round_{round_index}" / batch_id / case_id
        prepare_case(
            source_case=source_case,
            target_case=target_case,
            case_key=case_key,
            round_index=round_index,
            edge_step=edge_step,
            prompt_template=prompt_template,
            refresh_inputs=args.refresh_inputs,
        )
        prepared.append((round_index, case_key, target_case))

    pending = [
        target_case
        for _, _, target_case in prepared
        if not (target_case / EDGE_OUTPUT_NAME).is_file()
    ]
    print(f"Prepared case-runs: {len(prepared)}")
    print(f"Pending edge requests: {len(pending)}")
    print(f"Output root: {output_root}")

    if args.mode != "dry-run" and pending:
        load_dotenv(PROJECT_ROOT / ".env_openai", override=True)
        config = PipelineConfig(
            base_dir=output_root,
            model_name=MODEL_NAME,
            reasoning_effort=REASONING_EFFORT,
            verbosity=VERBOSITY,
            force_json_output=True,
            save_raw_response=True,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            call_sleep_seconds=0.0,
            hazards_json_path=PROJECT_ROOT / "prompt" / "hazards_consequence.json",
            conditions_json_path=PROJECT_ROOT / "prompt" / "conditions.json",
            use_few_shot=False,
            target_folders=tuple(pending),
            batch_workdir=output_root / "_batch_pipeline",
            active_step_keys=(EDGE_STEP_KEY,),
            responses_async_enabled=args.mode == "responses",
            responses_max_concurrency=args.responses_max_concurrency,
            stop_on_step_failure=True,
            enable_local_postprocess=False,
        )
        run_pipeline_for_mode(config=config, execution_mode=args.mode)

    build_failures: list[str] = []
    for _, case_key, target_case in prepared:
        try:
            materialize_completed_case(target_case)
        except Exception as exc:
            build_failures.append(f"{case_key}: {type(exc).__name__}: {exc}")
            write_json(
                target_case / CASE_AUDIT_NAME,
                {"valid": False, "errors": [str(exc)], "warnings": []},
            )

    summary = write_summary_audits(
        output_root=output_root,
        prepared=prepared,
        mode=args.mode,
        exclusions=exclusions,
        prompt_template=prompt_template,
    )
    if build_failures:
        print(f"Graph build failures: {len(build_failures)}")
        for failure in build_failures[:10]:
            print(f"  {failure}")
        return 1

    graph_count = sum(item["graphs_present"] for item in summary["rounds"].values())
    valid_count = sum(item["valid_graphs"] for item in summary["rounds"].values())
    print(f"No Revision graphs: {valid_count}/{graph_count} valid")
    if args.mode == "dry-run":
        print("Dry run complete. No API requests were made.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
