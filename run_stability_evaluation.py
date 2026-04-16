from __future__ import annotations

import argparse
from pathlib import Path

from utils.stability_evaluation import run_stability_evaluation


PROJECT_ROOT = Path(__file__).resolve().parent
STRUCTURE_EVAL_PATH = PROJECT_ROOT / "scripts" / "evaluation_structure_similarity.py"
PLOT_EVAL_PATH = PROJECT_ROOT / "scripts" / "plot_evaluation_results.py"
DEFAULT_FOLDER = Path(r"runs/stability_test/stability_test_batch_1_9_reruns")  # Default base folder for evaluation; can be overridden by --folder argument.
DEFAULT_GRAPH_FILE = "causal_graph.json"
EXACT_GED = False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run stability evaluation by comparing graph JSON files across rerun folders."
    )
    parser.add_argument(
        "--folder",
        type=Path,
        default=DEFAULT_FOLDER,
        help="Base rerun folder to scan. Usually the stability output root.",
    )
    parser.add_argument(
        "--graph-file",
        type=str,
        default=DEFAULT_GRAPH_FILE,
        help="Graph JSON filename to compare across rounds.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Optional output directory. Defaults to <folder>/stability_results.",
    )
    parser.add_argument(
        "--exact-ged",
        dest="exact_ged",
        action="store_true",
        help="Exhaust GED candidates and take the minimum value.",
    )
    parser.add_argument(
        "--fast-ged",
        dest="exact_ged",
        action="store_false",
        help="Use only the first GED candidate for faster but less reliable results.",
    )
    parser.set_defaults(exact_ged=EXACT_GED)
    return parser.parse_args()


def main() -> Path:
    args = parse_args()
    return run_stability_evaluation(
        stability_root=args.folder,
        graph_file=args.graph_file,
        output_dir=args.output_dir,
        exact_ged=args.exact_ged,
    )


if __name__ == "__main__":
    main()
