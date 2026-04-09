from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict


DEFAULT_CASE_DIR = Path(r"runs\few-shot\test_confined_explosion\batch_1_9_ignition")
DEFAULT_GRAPH_FILE_CANDIDATES = (
    "updated_causal_graph.json",
    "updated_causal_graph_accept_all.json",
)
UPSTREAM_FILES_TO_COPY = (
    "identify_incident_output.json",
    "identify_hazard_consequence_output.json",
    "causal_narrative_extraction_output.json",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate few-shot step outputs from a manually updated causal graph. "
            "This creates identify_accident_scenario_output.json and "
            "causal_edge_linking_output.json under a few_shot_outputs folder."
        )
    )
    parser.add_argument(
        "--case-dir",
        type=Path,
        default=DEFAULT_CASE_DIR,
        help="Case directory containing updated_causal_graph.json.",
    )
    parser.add_argument(
        "--graph-file",
        type=str,
        default="",
        help=(
            "Optional graph filename inside the case directory. "
            "If omitted, the script tries updated_causal_graph.json first, "
            "then updated_causal_graph_accept_all.json."
        ),
    )
    parser.add_argument(
        "--output-subdir",
        type=str,
        default="few_shot_outputs",
        help="Subdirectory name to write generated few-shot files into.",
    )
    return parser.parse_args()


def resolve_graph_path(case_dir: Path, graph_file: str) -> Path:
    if graph_file:
        path = case_dir / graph_file
        if not path.exists():
            raise FileNotFoundError(f"Graph file not found: {path}")
        return path

    for candidate in DEFAULT_GRAPH_FILE_CANDIDATES:
        path = case_dir / candidate
        if path.exists():
            return path

    raise FileNotFoundError(
        "No updated graph file found. Tried: "
        + ", ".join(str(case_dir / name) for name in DEFAULT_GRAPH_FILE_CANDIDATES)
    )


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as fp:
        data = json.load(fp)
    if not isinstance(data, dict):
        raise TypeError(f"Expected JSON object in {path}")
    return data


def dump_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def copy_upstream_files(case_dir: Path, output_dir: Path) -> None:
    for filename in UPSTREAM_FILES_TO_COPY:
        source_path = case_dir / filename
        if not source_path.exists():
            continue
        output_path = output_dir / filename
        output_path.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")


def build_identify_accident_scenario_output(graph: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "hazard_consequence_node": graph.get("hazard_consequence_node", []),
        "entity_nodes": graph.get("entity_nodes", []),
        "condition_nodes": graph.get("condition_nodes", []),
        "event_nodes": graph.get("event_nodes", []),
    }


def build_causal_edge_linking_output(graph: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "edges": graph.get("edges", []),
    }


def main() -> None:
    args = parse_args()
    case_dir = args.case_dir.resolve()
    if not case_dir.exists():
        raise FileNotFoundError(f"Case directory not found: {case_dir}")

    graph_path = resolve_graph_path(case_dir, args.graph_file)
    graph = load_json(graph_path)

    output_dir = case_dir / args.output_subdir
    output_dir.mkdir(parents=True, exist_ok=True)

    scenario_output = build_identify_accident_scenario_output(graph)
    edge_output = build_causal_edge_linking_output(graph)

    copy_upstream_files(case_dir, output_dir)
    dump_json(output_dir / "identify_accident_scenario_output.json", scenario_output)
    dump_json(output_dir / "causal_edge_linking_output.json", edge_output)
    dump_json(output_dir / "causal_graph.json", graph)

    print(f"Input graph: {graph_path}")
    print(f"Saved few-shot outputs to: {output_dir}")
    for filename in UPSTREAM_FILES_TO_COPY:
        copied = output_dir / filename
        if copied.exists():
            print(f"- {copied}")
    print(f"- {output_dir / 'identify_accident_scenario_output.json'}")
    print(f"- {output_dir / 'causal_edge_linking_output.json'}")
    print(f"- {output_dir / 'causal_graph.json'}")


if __name__ == "__main__":
    main()
