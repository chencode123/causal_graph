from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib.pyplot as plt
import numpy as np


WL_COLUMN = "structural_similarity"
NORM_GED_COLUMN = "normalized_graph_edit_distance"
SEMANTIC_PRIMARY_COLUMN = "semantic_similarity_generated_vs_updated"
SEMANTIC_FALLBACK_COLUMN = "semantic_similarity"
CAUSAL_NARRATIVE_COLUMN = "causal_narrative_similarity"
DEFAULT_STABILITY_ROOT = Path(r"runs\temproal_result_5_step_batch_4_stability_test_123")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate grouped boxplot and radar chart for rerun comparisons "
            "(WL kernel, 1-normalized GED, semantic similarity)."
        )
    )
    parser.add_argument(
        "--labels",
        nargs="+",
        required=False,
        help="Rerun labels, e.g., rerun_1 rerun_2 rerun_3.",
    )
    parser.add_argument(
        "--structure-results",
        nargs="+",
        required=False,
        help=(
            "Structure-evaluation result directories (each can be a timestamp dir "
            "containing case_scores.csv, or a parent dir where case_scores.csv "
            "is discovered recursively)."
        ),
    )
    parser.add_argument(
        "--semantic-results",
        nargs="+",
        required=False,
        help=(
            "Semantic-evaluation result directories (each can be a timestamp dir "
            "containing case_semantic_scores.csv, or a parent dir where it is "
            "discovered recursively)."
        ),
    )
    parser.add_argument(
        "--stability-root",
        type=Path,
        default=DEFAULT_STABILITY_ROOT,
        help=(
            "Root directory for rerun outputs, e.g. "
            "runs\\temproal_result_5_step_batch_4_stability_test_123. "
            "When set, script auto-discovers rerun folders and latest CSVs."
        ),
    )
    parser.add_argument(
        "--max-reruns",
        type=int,
        default=None,
        help="Optional cap for number of discovered reruns (after sorting).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for output figures. Default: <stability-root>/combined_figures",
    )
    return parser.parse_args()


def to_float(value: str) -> float | None:
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def find_latest_csv(base_dir: Path, filename: str) -> Path:
    if (base_dir / filename).exists():
        return base_dir / filename
    candidates = list(base_dir.rglob(filename))
    if not candidates:
        raise FileNotFoundError(f"Cannot find {filename} under {base_dir}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def read_csv_rows(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        return list(csv.DictReader(fp))


def collect_rerun_metrics(
    *,
    structure_csv_path: Path,
    semantic_csv_path: Path,
) -> Dict[str, List[float]]:
    structure_rows = [
        row
        for row in read_csv_rows(structure_csv_path)
        if str(row.get("status", "")).strip().lower() == "ok"
    ]
    semantic_rows = [
        row
        for row in read_csv_rows(semantic_csv_path)
        if str(row.get("status", "")).strip().lower() == "ok"
    ]

    wl_values: List[float] = []
    one_minus_norm_ged_values: List[float] = []
    for row in structure_rows:
        wl = to_float(row.get(WL_COLUMN, ""))
        norm_ged = to_float(row.get(NORM_GED_COLUMN, ""))
        if wl is not None:
            wl_values.append(wl)
        if norm_ged is not None:
            one_minus_norm_ged_values.append(1.0 - norm_ged)

    semantic_values: List[float] = []
    causal_narrative_values: List[float] = []
    for row in semantic_rows:
        semantic_value = to_float(row.get(SEMANTIC_PRIMARY_COLUMN, ""))
        if semantic_value is None:
            semantic_value = to_float(row.get(SEMANTIC_FALLBACK_COLUMN, ""))
        if semantic_value is not None:
            semantic_values.append(semantic_value)
        causal_narrative_value = to_float(row.get(CAUSAL_NARRATIVE_COLUMN, ""))
        if causal_narrative_value is not None:
            causal_narrative_values.append(causal_narrative_value)

    return {
        "wl_kernel_similarity": wl_values,
        "one_minus_normalized_ged": one_minus_norm_ged_values,
        "semantic_similarity": semantic_values,
        "causal_narrative_similarity": causal_narrative_values,
    }


def collect_metrics_from_rows(
    structure_rows: List[Dict[str, str]],
    semantic_rows: List[Dict[str, str]],
) -> Dict[str, List[float]]:
    wl_values: List[float] = []
    one_minus_norm_ged_values: List[float] = []
    for row in structure_rows:
        wl = to_float(row.get(WL_COLUMN, ""))
        norm_ged = to_float(row.get(NORM_GED_COLUMN, ""))
        if wl is not None:
            wl_values.append(wl)
        if norm_ged is not None:
            one_minus_norm_ged_values.append(1.0 - norm_ged)

    semantic_values: List[float] = []
    causal_narrative_values: List[float] = []
    for row in semantic_rows:
        semantic_value = to_float(row.get(SEMANTIC_PRIMARY_COLUMN, ""))
        if semantic_value is None:
            semantic_value = to_float(row.get(SEMANTIC_FALLBACK_COLUMN, ""))
        if semantic_value is not None:
            semantic_values.append(semantic_value)
        causal_narrative_value = to_float(row.get(CAUSAL_NARRATIVE_COLUMN, ""))
        if causal_narrative_value is not None:
            causal_narrative_values.append(causal_narrative_value)

    return {
        "wl_kernel_similarity": wl_values,
        "one_minus_normalized_ged": one_minus_norm_ged_values,
        "semantic_similarity": semantic_values,
        "causal_narrative_similarity": causal_narrative_values,
    }


def ensure_output_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def style_axes(ax: plt.Axes) -> None:
    ax.grid(False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_linewidth(0.8)
    ax.spines["bottom"].set_linewidth(0.8)
    ax.tick_params(length=4, width=0.8)


def save_figure(fig: plt.Figure, output_dir: Path, stem: str) -> None:
    fig.tight_layout()
    fig.savefig(output_dir / f"{stem}.png", dpi=300)
    fig.savefig(output_dir / f"{stem}.svg", dpi=300)
    plt.close(fig)


def plot_grouped_boxplot(
    labels: List[str],
    metrics_by_label: Dict[str, Dict[str, List[float]]],
    output_dir: Path,
) -> None:
    metric_keys = [
        ("wl_kernel_similarity", "WL kernel"),
        ("one_minus_normalized_ged", "1 - normGED"),
        ("semantic_similarity", "Graph semantic"),
        ("causal_narrative_similarity", "Narrative"),
    ]
    metric_colors = ["#4C72B0", "#C44E52", "#55A868", "#8172B3"]
    n_groups = len(labels)
    x = np.arange(n_groups, dtype=float)
    width = 0.18
    offsets = np.linspace(-1.5 * width, 1.5 * width, len(metric_keys), dtype=float)

    fig, ax = plt.subplots(figsize=(9.5, 5.8))
    style_axes(ax)

    for idx, ((metric_key, metric_name), color) in enumerate(zip(metric_keys, metric_colors)):
        data = [metrics_by_label[label][metric_key] for label in labels]
        positions = x + offsets[idx]
        valid_positions = []
        valid_data = []
        for position, series in zip(positions, data):
            if series:
                valid_positions.append(position)
                valid_data.append(series)
        if not valid_data:
            continue
        box = ax.boxplot(
            valid_data,
            positions=valid_positions,
            widths=width * 0.9,
            patch_artist=True,
            medianprops={"color": "#222222", "linewidth": 1.2},
            whiskerprops={"color": "#555555", "linewidth": 0.9},
            capprops={"color": "#555555", "linewidth": 0.9},
            boxprops={"edgecolor": "#555555", "linewidth": 0.9},
            flierprops={
                "marker": "o",
                "markerfacecolor": "#999999",
                "markeredgecolor": "#999999",
                "markersize": 3,
                "alpha": 0.5,
            },
        )
        for patch in box["boxes"]:
            patch.set_facecolor(color)
            patch.set_alpha(0.5)
        ax.plot([], [], color=color, linewidth=8, alpha=0.5, label=metric_name)

    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylim(0.0, 1.05)
    ax.set_ylabel("Similarity Score")
    ax.set_xlabel("Rerun")
    ax.set_title("Rerun Comparison: Similarity Distributions")
    handles, legend_labels = ax.get_legend_handles_labels()
    if handles:
        ax.legend(loc="best", frameon=False)
    save_figure(fig, output_dir, "rerun_grouped_boxplot")


def plot_radar_chart(
    labels: List[str],
    metrics_by_label: Dict[str, Dict[str, List[float]]],
    output_dir: Path,
) -> None:
    axes_labels = ["WL kernel", "1 - normGED", "Graph semantic", "Narrative"]
    means_by_label: Dict[str, List[float]] = {}
    for label in labels:
        wl_values = metrics_by_label[label]["wl_kernel_similarity"]
        ged_values = metrics_by_label[label]["one_minus_normalized_ged"]
        semantic_values = metrics_by_label[label]["semantic_similarity"]
        causal_narrative_values = metrics_by_label[label]["causal_narrative_similarity"]
        means_by_label[label] = [
            float(np.mean(wl_values)) if wl_values else 0.0,
            float(np.mean(ged_values)) if ged_values else 0.0,
            float(np.mean(semantic_values)) if semantic_values else 0.0,
            float(np.mean(causal_narrative_values)) if causal_narrative_values else 0.0,
        ]

    angles = np.linspace(0, 2 * np.pi, len(axes_labels), endpoint=False).tolist()
    angles += angles[:1]

    fig = plt.figure(figsize=(7.2, 7.0))
    ax = fig.add_subplot(111, polar=True)
    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)
    ax.set_ylim(0.0, 1.0)
    ax.set_yticks([0.2, 0.4, 0.6, 0.8, 1.0])
    ax.set_yticklabels(["0.2", "0.4", "0.6", "0.8", "1.0"])
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(axes_labels)

    colors = ["#4C72B0", "#C44E52", "#55A868", "#8172B3", "#DD8452"]
    for index, label in enumerate(labels):
        values = means_by_label[label]
        values_closed = values + values[:1]
        color = colors[index % len(colors)]
        ax.plot(angles, values_closed, linewidth=2.0, color=color, label=label)
        ax.fill(angles, values_closed, color=color, alpha=0.15)

    ax.set_title("Rerun Comparison: Mean Similarity Radar", pad=18)
    ax.legend(loc="upper right", bbox_to_anchor=(1.25, 1.10), frameon=False)
    save_figure(fig, output_dir, "rerun_radar_mean")


def resolve_paths(raw_paths: List[str], filename: str) -> List[Path]:
    resolved: List[Path] = []
    for raw in raw_paths:
        resolved.append(find_latest_csv(Path(raw), filename))
    return resolved


def extract_round_index_from_name(name: str) -> int:
    digits = "".join(ch for ch in name if ch.isdigit())
    return int(digits) if digits else 0


def batch_id_sort_key(batch_id: str) -> Tuple[str, int, str]:
    text = str(batch_id or "").strip()
    match = re.match(r"^(.*)_(\d+)$", text)
    if match:
        return (match.group(1), int(match.group(2)), text)
    return (text, 0, text)


def batch_id_base(batch_id: str) -> str:
    text = str(batch_id or "").strip()
    match = re.match(r"^(.*)_(\d+)$", text)
    return match.group(1) if match else text


def discover_rerun_dirs(stability_root: Path) -> List[Path]:
    if not stability_root.exists():
        raise FileNotFoundError(f"stability root not found: {stability_root}")
    round_dirs = sorted(
        [path for path in stability_root.iterdir() if path.is_dir() and path.name.startswith("round_")],
        key=lambda path: extract_round_index_from_name(path.name),
    )
    if round_dirs:
        return round_dirs
    output_round_dirs = sorted(
        [path for path in stability_root.iterdir() if path.is_dir() and "_output_round_" in path.name],
        key=lambda path: extract_round_index_from_name(path.name),
    )
    if output_round_dirs:
        return output_round_dirs
    raise FileNotFoundError(
        f"No rerun directories found under {stability_root}. "
        "Expected round_* or *_output_round_* folders."
    )


def infer_round_index_from_path(path: Path) -> int:
    for part in path.parts[::-1]:
        lower = part.lower()
        if lower.startswith("round_"):
            return extract_round_index_from_name(lower)
        if "_output_round_" in lower:
            return extract_round_index_from_name(lower)
    return 0


def build_inputs_from_stability_root(
    stability_root: Path,
    max_reruns: int | None,
) -> tuple[List[str], List[Path], List[Path]]:
    rerun_dirs: List[Path] = []
    try:
        rerun_dirs = discover_rerun_dirs(stability_root)
    except FileNotFoundError:
        rerun_dirs = []

    if rerun_dirs:
        if max_reruns is not None and max_reruns > 0:
            rerun_dirs = rerun_dirs[:max_reruns]
        labels: List[str] = []
        structure_csv_paths: List[Path] = []
        semantic_csv_paths: List[Path] = []
        for rerun_dir in rerun_dirs:
            labels.append(rerun_dir.name)
            structure_csv_paths.append(find_latest_csv(rerun_dir, "case_scores.csv"))
            semantic_csv_paths.append(find_latest_csv(rerun_dir, "case_semantic_scores.csv"))
        return labels, structure_csv_paths, semantic_csv_paths

    structure_candidates = list(stability_root.rglob("case_scores.csv"))
    semantic_candidates = list(stability_root.rglob("case_semantic_scores.csv"))
    if not structure_candidates or not semantic_candidates:
        raise FileNotFoundError(
            f"No rerun directories or result CSVs found under {stability_root}. "
            "Expected round folders or nested case_scores.csv/case_semantic_scores.csv."
        )

    structure_by_round: Dict[int, List[Path]] = {}
    for path in structure_candidates:
        structure_by_round.setdefault(infer_round_index_from_path(path), []).append(path)
    semantic_by_round: Dict[int, List[Path]] = {}
    for path in semantic_candidates:
        semantic_by_round.setdefault(infer_round_index_from_path(path), []).append(path)

    round_indices = sorted(index for index in structure_by_round if index in semantic_by_round and index > 0)
    if round_indices:
        if max_reruns is not None and max_reruns > 0:
            round_indices = round_indices[:max_reruns]

        labels = [f"round_{index}" for index in round_indices]
        structure_csv_paths = [
            max(structure_by_round[index], key=lambda path: path.stat().st_mtime) for index in round_indices
        ]
        semantic_csv_paths = [
            max(semantic_by_round[index], key=lambda path: path.stat().st_mtime) for index in round_indices
        ]
        return labels, structure_csv_paths, semantic_csv_paths

    # Fallback: no explicit round index in paths; pair by chronological order.
    structure_sorted = sorted(structure_candidates, key=lambda path: path.stat().st_mtime)
    semantic_sorted = sorted(semantic_candidates, key=lambda path: path.stat().st_mtime)
    usable_count = min(len(structure_sorted), len(semantic_sorted))
    if usable_count <= 0:
        raise FileNotFoundError(
            f"Found CSV files under {stability_root}, but failed to build comparable rerun pairs."
        )
    if max_reruns is not None and max_reruns > 0:
        usable_count = min(usable_count, max_reruns)
    structure_csv_paths = structure_sorted[-usable_count:]
    semantic_csv_paths = semantic_sorted[-usable_count:]
    labels = [f"rerun_{index}" for index in range(1, usable_count + 1)]
    return labels, structure_csv_paths, semantic_csv_paths


def build_metrics_from_single_timestamp(
    stability_root: Path,
) -> tuple[List[str], Dict[str, Dict[str, List[float]]]]:
    structure_csv = find_latest_csv(stability_root, "case_scores.csv")
    semantic_csv = find_latest_csv(stability_root, "case_semantic_scores.csv")

    structure_rows_all = [
        row
        for row in read_csv_rows(structure_csv)
        if str(row.get("status", "")).strip().lower() == "ok"
    ]
    semantic_rows_all = [
        row
        for row in read_csv_rows(semantic_csv)
        if str(row.get("status", "")).strip().lower() == "ok"
    ]
    if not structure_rows_all:
        raise ValueError(f"No successful rows in {structure_csv}")
    if not semantic_rows_all:
        raise ValueError(f"No successful rows in {semantic_csv}")

    structure_by_batch: Dict[str, List[Dict[str, str]]] = {}
    for row in structure_rows_all:
        batch_id = str(row.get("batch_id", "")).strip()
        if not batch_id:
            continue
        structure_by_batch.setdefault(batch_id, []).append(row)
    semantic_by_batch: Dict[str, List[Dict[str, str]]] = {}
    for row in semantic_rows_all:
        batch_id = str(row.get("batch_id", "")).strip()
        if not batch_id:
            continue
        semantic_by_batch.setdefault(batch_id, []).append(row)

    sorted_batches = sorted(structure_by_batch.keys(), key=batch_id_sort_key)
    labels: List[str] = []
    metrics_by_label: Dict[str, Dict[str, List[float]]] = {}
    for batch_id in sorted_batches:
        structure_rows = structure_by_batch[batch_id]
        semantic_rows = semantic_by_batch.get(batch_id)
        if semantic_rows is None:
            base_key = batch_id_base(batch_id)
            semantic_rows = semantic_by_batch.get(base_key)
            if semantic_rows is not None:
                print(
                    f"[WARN] semantic batch_id '{batch_id}' not found; "
                    f"fallback to '{base_key}'."
                )
        if semantic_rows is None:
            raise ValueError(
                f"Missing semantic rows for batch_id={batch_id}. "
                f"structure file: {structure_csv}, semantic file: {semantic_csv}"
            )
        labels.append(batch_id)
        metrics_by_label[batch_id] = collect_metrics_from_rows(structure_rows, semantic_rows)
    return labels, metrics_by_label


def main() -> None:
    args = parse_args()
    if args.output_dir is not None:
        output_dir = ensure_output_dir(args.output_dir.resolve())
    else:
        output_dir = ensure_output_dir((args.stability_root / "combined_figures").resolve())
    if args.stability_root is not None:
        stability_root = args.stability_root.resolve()
        latest_structure_csv = find_latest_csv(stability_root, "case_scores.csv")
        latest_structure_rows = [
            row
            for row in read_csv_rows(latest_structure_csv)
            if str(row.get("status", "")).strip().lower() == "ok"
        ]
        latest_structure_batch_ids = {
            str(row.get("batch_id", "")).strip()
            for row in latest_structure_rows
            if str(row.get("batch_id", "")).strip()
        }
        if len(latest_structure_batch_ids) > 1:
            labels, metrics_by_label = build_metrics_from_single_timestamp(stability_root)
            if args.max_reruns is not None and args.max_reruns > 0:
                labels = labels[: args.max_reruns]
                metrics_by_label = {label: metrics_by_label[label] for label in labels}
            structure_csv_paths = [latest_structure_csv] * len(labels)
            semantic_csv_paths = [find_latest_csv(stability_root, "case_semantic_scores.csv")] * len(labels)
        else:
            labels, structure_csv_paths, semantic_csv_paths = build_inputs_from_stability_root(
                stability_root,
                args.max_reruns,
            )
            metrics_by_label: Dict[str, Dict[str, List[float]]] = {}
            for label, structure_csv_path, semantic_csv_path in zip(labels, structure_csv_paths, semantic_csv_paths):
                metrics_by_label[label] = collect_rerun_metrics(
                    structure_csv_path=structure_csv_path,
                    semantic_csv_path=semantic_csv_path,
                )
    else:
        if not args.labels or not args.structure_results or not args.semantic_results:
            raise ValueError(
                "Provide either --stability-root, or explicit --labels --structure-results --semantic-results."
            )
        labels = args.labels
        if len(set(labels)) != len(labels):
            raise ValueError("Labels must be unique.")
        if not (len(labels) == len(args.structure_results) == len(args.semantic_results)):
            raise ValueError("labels, structure-results, and semantic-results must have the same length.")
        structure_csv_paths = resolve_paths(args.structure_results, "case_scores.csv")
        semantic_csv_paths = resolve_paths(args.semantic_results, "case_semantic_scores.csv")
        metrics_by_label = {}
        for label, structure_csv_path, semantic_csv_path in zip(labels, structure_csv_paths, semantic_csv_paths):
            metrics_by_label[label] = collect_rerun_metrics(
                structure_csv_path=structure_csv_path,
                semantic_csv_path=semantic_csv_path,
            )

    plot_grouped_boxplot(labels, metrics_by_label, output_dir)
    plot_radar_chart(labels, metrics_by_label, output_dir)

    print(f"Saved figures to {output_dir}")
    for label, structure_csv_path, semantic_csv_path in zip(labels, structure_csv_paths, semantic_csv_paths):
        print(f"{label}:")
        print(f"  structure: {structure_csv_path}")
        print(f"  semantic : {semantic_csv_path}")


if __name__ == "__main__":
    main()
