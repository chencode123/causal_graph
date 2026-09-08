from __future__ import annotations

"""
Root-level entrypoint for evaluation utilities.

Adjustable parameters:
- ``--folder`` controls the base evaluation folder.
- ``--parent-dir`` optionally narrows scanning to a subfolder under the base.
- ``--output-dir`` optionally overrides the default result location.

By default:
- evaluation scans ``--folder``
- results are written to ``<folder>/results``   

``--parent-dir`` is flexible and may point to:
- the base folder itself,
- a single batch directory,
- or one specific case folder.
"""

import argparse
import importlib.util
import os
import sys
from pathlib import Path

from utils.evaluation_case_filters import DEFAULT_EXCLUDED_CASES_PATH


PROJECT_ROOT = Path(__file__).resolve().parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
STRUCTURE_EVAL_PATH = PROJECT_ROOT / "scripts" / "evaluation_structure_similarity.py"
PLOT_EVAL_PATH = PROJECT_ROOT / "scripts" / "plot_evaluation_results.py"
DEFAULT_FOLDER = Path("runs/stability_test/rounds_with_few_shot")  # Default base folder for evaluation; can be overridden by --folder argument.
SHOW_PROGRESS = True  # Default progress-bar visibility; can still be overridden by --show-progress/--hide-progress.
COMPUTE_GED = True  # Whether to compute GED-based metrics by default.
COMPUTE_GED_OPERATION_COUNTS = False  # Whether to run the expensive node/edge edit-operation counting step by default.
DEFAULT_WORKERS = 8  # Safer default on Windows to avoid process-pool crashes from heavy native imports.
DEFAULT_GED_ALGORITHM = "bipartite"  # Options: exact, fast, bipartite.
GED_TIMEOUT_SECONDS = None  # Optional per-GED timeout in seconds. None keeps NetworkX default behavior.

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

def parse_args() -> argparse.Namespace:
    """Parse arguments for the root evaluation runner."""
    parser = argparse.ArgumentParser(
        description=(
            "Run evaluation tasks from the project root. "
            "The base folder is adjustable, and the default output location "
            "keeps the same relative structure under that folder."
        ),
    )
    parser.add_argument(
        "--folder",
        type=Path,
        default=DEFAULT_FOLDER,
        help=(
            "Base evaluation folder. Examples: runs/batch_api_test_1, "
            "runs/batch_api_test_2, or another evaluation root."
        ),
    )
    parser.add_argument(
        "--parent-dir",
        type=Path,
        default=None,
        help=(
            "Folder to scan for evaluation cases. If omitted, the value of "
            "--folder is used. This can be a base directory, a single batch "
            "directory, or a specific case folder."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=(
            "Directory where evaluation result files will be written. "
            "If omitted, results are written to <folder>/results."
        ),
    )
    parser.add_argument(
        "--reference-root",
        type=Path,
        default=None,
        help=(
            "Optional fixed expert-reference root organized as "
            "<batch>/<case>/updated_causal_graph.json. Required for result "
            "folders, such as the single-pass baseline, that do not carry a "
            "local reference graph."
        ),
    )
    parser.add_argument(
        "--generated-graph-name",
        default="causal_graph.json",
        help=(
            "Filename of the generated graph inside each case directory. "
            "Defaults to causal_graph.json; the two-stage No Revision condition "
            "uses no_revision_causal_graph.json."
        ),
    )
    parser.add_argument(
        "--run-labels",
        nargs="+",
        default=None,
        help=(
            "Only evaluate these immediate child runs/rounds, such as "
            "round_4 round_5 or run_01 run_02 run_03 run_04 run_05."
        ),
    )
    parser.add_argument(
        "--exclude-case-list",
        type=Path,
        default=DEFAULT_EXCLUDED_CASES_PATH,
        help=(
            "JSON list of batch/case keys to exclude. Defaults to the cases that "
            "contributed few-shot review patterns."
        ),
    )
    parser.add_argument(
        "--include-few-shot-cases",
        dest="exclude_case_list",
        action="store_const",
        const=None,
        help="Disable the default few-shot case exclusion for a non-held-out analysis.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=(
            "Number of worker processes for parallel case evaluation. "
            "If omitted, the evaluation script chooses a sensible default."
        ),
    )
    parser.add_argument(
        "--compute-ged",
        dest="compute_ged",
        action="store_true",
        help="Compute GED-based metrics such as graph_edit_distance and normalized_graph_edit_distance.",
    )
    parser.add_argument(
        "--skip-ged",
        dest="compute_ged",
        action="store_false",
        help="Skip GED-based metrics and leave GED-related CSV fields blank.",
    )
    parser.add_argument(
        "--compute-ged-operation-counts",
        dest="compute_ged_operation_counts",
        action="store_true",
        help="Compute per-case node/edge insertion, deletion, and substitution counts.",
    )
    parser.add_argument(
        "--skip-ged-operation-counts",
        dest="compute_ged_operation_counts",
        action="store_false",
        help="Skip the expensive GED operation-count calculation.",
    )
    parser.add_argument(
        "--show-progress",
        dest="show_progress",
        action="store_true",
        help="Show the live tqdm progress bar during evaluation.",
    )
    parser.add_argument(
        "--hide-progress",
        dest="show_progress",
        action="store_false",
        help="Hide the live tqdm progress bar and only print summary output.",
    )
    parser.add_argument(
        "--ged-algorithm",
        choices=("exact", "fast", "bipartite"),
        default=DEFAULT_GED_ALGORITHM,
        help=(
            "GED algorithm to use: "
            "'exact' exhausts candidates, "
            "'fast' uses the first NetworkX candidate, "
            "and 'bipartite' uses a directed Riesen-Bunke assignment approximation "
            "with unit node/edge edit costs."
        ),
    )
    parser.add_argument(
        "--exact-ged",
        dest="ged_algorithm",
        action="store_const",
        const="exact",
        help="Legacy alias for --ged-algorithm exact.",
    )
    parser.add_argument(
        "--fast-ged",
        dest="ged_algorithm",
        action="store_const",
        const="fast",
        help="Legacy alias for --ged-algorithm fast.",
    )
    parser.add_argument(
        "--bipartite-ged",
        dest="ged_algorithm",
        action="store_const",
        const="bipartite",
        help="Legacy alias for --ged-algorithm bipartite.",
    )
    parser.add_argument(
        "--ged-timeout",
        type=float,
        default=GED_TIMEOUT_SECONDS,
        help=(
            "Maximum seconds for each exact GED calculation. "
            "If omitted, NetworkX runs without a per-GED timeout."
        ),
    )
    parser.set_defaults(compute_ged=COMPUTE_GED)
    parser.set_defaults(compute_ged_operation_counts=COMPUTE_GED_OPERATION_COUNTS)
    parser.set_defaults(show_progress=SHOW_PROGRESS)
    return parser.parse_args()


def load_structure_eval_module():
    """Load the structure-evaluation script as a module."""
    spec = importlib.util.spec_from_file_location(
        "evaluation_structure_similarity",
        STRUCTURE_EVAL_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load evaluation module from {STRUCTURE_EVAL_PATH}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_plot_eval_module():
    """Load the evaluation-plotting script as a module."""
    spec = importlib.util.spec_from_file_location(
        "plot_evaluation_results",
        PLOT_EVAL_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load plotting module from {PLOT_EVAL_PATH}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    """Delegate execution to the structure evaluation script."""
    # Keep native BLAS thread pools small to avoid memory pressure on Windows.
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")

    args = parse_args()
    eval_module = load_structure_eval_module()
    plot_module = load_plot_eval_module()
    parent_dir = args.parent_dir or args.folder
    output_dir = args.output_dir or (args.folder / "results")

    original_argv = sys.argv[:]
    try:
        sys.argv = [
            str(STRUCTURE_EVAL_PATH),
            "--parent-dir",
            str(parent_dir),
            "--output-dir",
            str(output_dir),
        ]
        if args.exclude_case_list is None:
            sys.argv.append("--include-few-shot-cases")
        else:
            sys.argv.extend(["--exclude-case-list", str(args.exclude_case_list)])
        if args.reference_root is not None:
            sys.argv.extend(["--reference-root", str(args.reference_root)])
        sys.argv.extend(["--generated-graph-name", args.generated_graph_name])
        if args.run_labels:
            sys.argv.extend(["--run-labels", *args.run_labels])
        if args.workers is not None:
            sys.argv.extend(["--workers", str(args.workers)])
        if not args.compute_ged:
            sys.argv.append("--skip-ged")
        if not args.compute_ged_operation_counts:
            sys.argv.append("--skip-ged-operation-counts")
        if not args.show_progress:
            sys.argv.append("--hide-progress")
        # Always forward the GED algorithm explicitly because the downstream
        # script has its own defaults, which may differ from this wrapper.
        sys.argv.extend(["--ged-algorithm", args.ged_algorithm])
        if args.ged_timeout is not None:
            sys.argv.extend(["--ged-timeout", str(args.ged_timeout)])
        results_dir = eval_module.main()
        figures_dir = plot_module.generate_all_figures(results_dir)
        print(f"Saved evaluation figures to {figures_dir}.")
    finally:
        sys.argv = original_argv


if __name__ == "__main__":
    main()
