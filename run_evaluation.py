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
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
STRUCTURE_EVAL_PATH = PROJECT_ROOT / "scripts" / "evaluation_structure_similarity.py"
PLOT_EVAL_PATH = PROJECT_ROOT / "scripts" / "plot_evaluation_results.py"
DEFAULT_FOLDER = Path("runs/temproal_result")

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
    spec.loader.exec_module(module)
    return module


def main() -> None:
    """Delegate execution to the structure evaluation script."""
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
        results_dir = eval_module.main()
        figures_dir = plot_module.generate_all_figures(results_dir)
        print(f"Saved evaluation figures to {figures_dir}.")
    finally:
        sys.argv = original_argv


if __name__ == "__main__":
    main()
