import argparse
import json
from pathlib import Path


NODE_KEYS = [
    "hazard_consequence_node",
    "entity_nodes",
    "condition_nodes",
    "event_nodes",
]


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def dump_json(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def sync_case(case_dir: Path, dry_run: bool) -> tuple[bool, str]:
    updated_path = case_dir / "updated_causal_graph.json"
    identify_path = case_dir / "identify_accident_scenario_output.json"
    edge_path = case_dir / "causal_edge_linking_output.json"

    missing = [p.name for p in [updated_path, identify_path, edge_path] if not p.exists()]
    if missing:
        return False, f"skip {case_dir}: missing {', '.join(missing)}"

    updated_data = load_json(updated_path)
    identify_data = load_json(identify_path)
    edge_data = load_json(edge_path)

    for key in NODE_KEYS:
        if key not in updated_data:
            return False, f"skip {case_dir}: {updated_path.name} missing key {key}"
        identify_data[key] = updated_data[key]

    if "edges" not in updated_data:
        return False, f"skip {case_dir}: {updated_path.name} missing key edges"
    edge_data["edges"] = updated_data["edges"]

    if not dry_run:
        dump_json(identify_path, identify_data)
        dump_json(edge_path, edge_data)

    return True, f"sync {case_dir}"


def iter_case_dirs(root: Path):
    for updated_path in root.rglob("updated_causal_graph.json"):
        yield updated_path.parent


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Sync node content from updated_causal_graph.json into "
            "identify_accident_scenario_output.json, and sync edges into "
            "causal_edge_linking_output.json."
        )
    )
    parser.add_argument(
        "--root",
        default="prompt/few-shot",
        help="Root directory containing few-shot case folders.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show which case folders would be updated without writing files.",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.exists():
        raise FileNotFoundError(f"Root path does not exist: {root}")

    case_dirs = sorted(set(iter_case_dirs(root)))
    if not case_dirs:
        print(f"No updated_causal_graph.json found under {root}")
        return

    synced = 0
    skipped = 0

    for case_dir in case_dirs:
        ok, message = sync_case(case_dir, dry_run=args.dry_run)
        print(message)
        if ok:
            synced += 1
        else:
            skipped += 1

    mode = "Dry run complete" if args.dry_run else "Sync complete"
    print(f"{mode}: synced={synced}, skipped={skipped}")


if __name__ == "__main__":
    main()
