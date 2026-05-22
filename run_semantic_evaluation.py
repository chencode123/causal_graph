from __future__ import annotations

import argparse
import csv
import json
import math
import os
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Iterable, List, Tuple

import matplotlib.pyplot as plt
import numpy as np
from openai import OpenAI
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed

NODE_GROUP_KEYS = (
    "hazard_consequence_node",
    "entity_nodes",
    "condition_nodes",
    "event_nodes",
)

DEFAULT_PARENT_DIR = Path(r"runs\stability_test\rounds")
DEFAULT_CAUSAL_NARRATIVE_REFERENCE_DIR = None
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"

CASE_SCORE_COLUMNS = [
    "batch_id",
    "case_id",
    "semantic_similarity",
    "semantic_similarity_generated_vs_updated",
    "semantic_similarity_accept_all_vs_updated",
    "semantic_similarity_delta_accept_all_minus_generated",
    "causal_narrative_similarity",
    "generated_sentence_count",
    "updated_sentence_count",
    "accept_all_sentence_count",
    "causal_narrative_step_count",
    "reference_causal_narrative_step_count",
    "embedding_model",
    "status",
    "warnings",
]

BATCH_SCORE_COLUMNS = [
    "batch_id",
    "case_count",
    "success_case_count",
    "failed_case_count",
    "mean_semantic_similarity",
    "mean_semantic_similarity_generated_vs_updated",
    "mean_semantic_similarity_accept_all_vs_updated",
    "mean_semantic_similarity_delta_accept_all_minus_generated",
    "mean_causal_narrative_similarity",
    "mean_generated_sentence_count",
    "mean_updated_sentence_count",
    "mean_accept_all_sentence_count",
    "mean_causal_narrative_step_count",
    "mean_reference_causal_narrative_step_count",
]

OVERALL_SUMMARY_COLUMNS = [
    "total_batch_count",
    "total_case_count",
    "successful_case_count",
    "failed_case_count",
    "overall_mean_semantic_similarity",
    "overall_mean_semantic_similarity_generated_vs_updated",
    "overall_mean_semantic_similarity_accept_all_vs_updated",
    "overall_mean_semantic_similarity_delta_accept_all_minus_generated",
    "overall_mean_causal_narrative_similarity",
    "overall_mean_generated_sentence_count",
    "overall_mean_updated_sentence_count",
    "overall_mean_accept_all_sentence_count",
    "overall_mean_causal_narrative_step_count",
    "overall_mean_reference_causal_narrative_step_count",
]


def load_env_file(env_path: Path) -> None:
    """Load KEY=VALUE lines from a .env-style file into process env if key is missing."""
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def ensure_openai_env() -> None:
    """Ensure OPENAI_API_KEY is available, using .env_openai as fallback."""
    if os.getenv("OPENAI_API_KEY"):
        return
    project_root = Path(__file__).resolve().parent
    load_env_file(project_root / ".env_openai")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate whole-graph semantic similarity between causal_graph.json and "
            "updated_causal_graph.json using edge-triple sentence embedding aggregation."
        )
    )
    parser.add_argument(
        "--parent-dir",
        type=Path,
        default=DEFAULT_PARENT_DIR,
        help="Parent directory to recursively scan for case folders.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory where CSV files will be written. Default: <parent-dir>/result_semantic",
    )
    parser.add_argument(
        "--embedding-model",
        type=str,
        default=DEFAULT_EMBEDDING_MODEL,
        help="Embedding model name for semantic similarity.",
    )
    parser.add_argument(
        "--causal-narrative-reference-dir",
        type=Path,
        default=DEFAULT_CAUSAL_NARRATIVE_REFERENCE_DIR,
        help=(
            "Reference batch directory for causal narrative similarity. "
            "Each case is matched by case_id, e.g. <reference-dir>/<case_id>/"
            "causal_narrative_extraction_output.json. Use a missing path to leave "
            "the narrative metric blank."
        ),
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of worker threads. Use 1 to disable parallelism.",
    )
    parser.add_argument(
        "--show-progress",
        dest="show_progress",
        action="store_true",
        help="Show tqdm progress bar.",
    )
    parser.add_argument(
        "--hide-progress",
        dest="show_progress",
        action="store_false",
        help="Hide tqdm progress bar.",
    )
    parser.add_argument(
        "--save-sentences",
        dest="save_sentences",
        action="store_true",
        help="Save triple-sentence graph serialization for each case.",
    )
    parser.add_argument(
        "--skip-save-sentences",
        dest="save_sentences",
        action="store_false",
        help="Do not save sentence-level graph serialization files.",
    )
    parser.set_defaults(show_progress=True)
    parser.set_defaults(save_sentences=True)
    return parser.parse_args()


def resolve_updated_graph_path(case_folder: Path) -> Path | None:
    exact_path = case_folder / "updated_causal_graph.json"
    if exact_path.exists():
        return exact_path
    fallback_candidates = sorted(case_folder.glob("updated_causal_graph*.json"))
    return fallback_candidates[0] if fallback_candidates else None


def resolve_accept_all_graph_path(case_folder: Path) -> Path | None:
    exact_path = case_folder / "updated_causal_graph_accept_all.json"
    if exact_path.exists():
        return exact_path
    fallback_candidates = sorted(case_folder.glob("updated_causal_graph_accept_all*.json"))
    return fallback_candidates[0] if fallback_candidates else None


def find_case_folders(parent_dir: Path) -> List[Path]:
    valid_folders: List[Path] = []
    for folder in parent_dir.rglob("*"):
        if not folder.is_dir():
            continue
        if (folder / "causal_graph.json").exists() and resolve_updated_graph_path(folder) is not None:
            valid_folders.append(folder)
    return sorted(valid_folders)


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def flatten_nodes(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    nodes: List[Dict[str, Any]] = []
    for key in NODE_GROUP_KEYS:
        group_nodes = data.get(key, [])
        if isinstance(group_nodes, list):
            nodes.extend(group_nodes)
    return nodes


def read_edges(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    edges = data.get("edges", [])
    return edges if isinstance(edges, list) else []


def normalize_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    return " ".join(text.split())


def edge_sort_key(
    edge: Dict[str, Any],
    node_map: Dict[str, Dict[str, Any]],
) -> Tuple[str, str, str, str, str]:
    source_id = str(edge.get("source") or "").strip()
    target_id = str(edge.get("target") or "").strip()
    relation = normalize_text(edge.get("relation") or edge.get("label") or "related_to")
    source_node = node_map.get(source_id, {})
    target_node = node_map.get(target_id, {})
    source_name = normalize_text(source_node.get("name") or source_id)
    target_name = normalize_text(target_node.get("name") or target_id)
    return (source_name, relation, target_name, normalize_text(source_id), normalize_text(target_id))


def edge_to_triple_sentence(edge: Dict[str, Any], node_map: Dict[str, Dict[str, Any]]) -> str:
    source_id = str(edge.get("source") or "").strip()
    target_id = str(edge.get("target") or "").strip()
    relation = normalize_text(edge.get("relation") or edge.get("label") or "related_to")
    source_node = node_map.get(source_id, {})
    target_node = node_map.get(target_id, {})
    source_name = normalize_text(source_node.get("name") or source_id) or "unknown_source"
    target_name = normalize_text(target_node.get("name") or target_id) or "unknown_target"
    return f"{source_name} {relation} {target_name}"


def graph_to_sentences(data: Dict[str, Any]) -> List[str]:
    nodes = flatten_nodes(data)
    edges = read_edges(data)
    node_map = {str(node.get("node_id") or "").strip(): node for node in nodes if node.get("node_id")}

    combined = [
        edge_to_triple_sentence(edge, node_map)
        for edge in sorted(edges, key=lambda item: edge_sort_key(item, node_map))
    ]

    # Deduplicate while preserving sorted order to keep representation stable.
    seen = set()
    unique_sentences: List[str] = []
    for sentence in combined:
        if sentence in seen:
            continue
        seen.add(sentence)
        unique_sentences.append(sentence)
    return unique_sentences


def causal_narrative_to_sentences(data: Dict[str, Any]) -> List[str]:
    """Serialize causal narrative steps into stable embedding sentences."""
    steps = data.get("causal_steps", [])
    if not isinstance(steps, list):
        return []

    def step_sort_key(step: Any) -> Tuple[int, str]:
        if not isinstance(step, dict):
            return (10**9, str(step))
        raw_number = step.get("step_number")
        try:
            number = int(raw_number)
        except (TypeError, ValueError):
            number = 10**9
        return (number, normalize_text(step.get("description") or step))

    sentences: List[str] = []
    for step in sorted(steps, key=step_sort_key):
        if isinstance(step, dict):
            text = str(step.get("description") or "").strip()
        else:
            text = str(step).strip()
        if text:
            sentences.append(" ".join(text.split()))
    return sentences


def resolve_causal_narrative_reference_path(
    *,
    case_folder: Path,
    reference_dir: Path | None,
) -> Path | None:
    if reference_dir is None:
        return None
    candidate_paths = [
        reference_dir / case_folder.name / "causal_narrative_extraction_output.json",
        reference_dir / case_folder.parent.name / case_folder.name / "causal_narrative_extraction_output.json",
    ]
    for candidate in candidate_paths:
        if candidate.exists():
            return candidate
    return None


def l2_norm(vector: Iterable[float]) -> float:
    return math.sqrt(sum(value * value for value in vector))


def normalize_vector(vector: List[float]) -> List[float]:
    norm = l2_norm(vector)
    if norm <= 0:
        return [0.0] * len(vector)
    return [value / norm for value in vector]


def average_vectors(vectors: List[List[float]]) -> List[float]:
    if not vectors:
        return []
    dimension = len(vectors[0])
    sums = [0.0] * dimension
    for vector in vectors:
        for index, value in enumerate(vector):
            sums[index] += value
    return [value / len(vectors) for value in sums]


def cosine_similarity(left: List[float], right: List[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    left_norm = l2_norm(left)
    right_norm = l2_norm(right)
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    dot = sum(l * r for l, r in zip(left, right))
    return dot / (left_norm * right_norm)


@dataclass
class EmbeddingHelper:
    client: OpenAI
    model: str
    cache: Dict[str, List[float]]
    lock: threading.Lock

    def embed_text(self, text: str) -> List[float]:
        with self.lock:
            cached = self.cache.get(text)
        if cached is not None:
            return cached
        response = self.client.embeddings.create(model=self.model, input=text)
        vector = [float(value) for value in response.data[0].embedding]
        with self.lock:
            self.cache[text] = vector
        return vector

    def embed_graph_sentences(self, sentences: List[str]) -> List[float]:
        if not sentences:
            return []
        sentence_vectors = [normalize_vector(self.embed_text(sentence)) for sentence in sentences]
        graph_vector = average_vectors(sentence_vectors)
        return normalize_vector(graph_vector)


def infer_batch_id(case_folder: Path, parent_dir: Path) -> str:
    relative_parts = case_folder.relative_to(parent_dir).parts
    if len(relative_parts) >= 2:
        return relative_parts[0]
    return "root"


def to_float(value: Any) -> float | None:
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def mean_or_blank(values: List[float]) -> str:
    if not values:
        return ""
    return f"{mean(values):.6f}"


def make_run_output_dir(base_output_dir: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_output_dir = base_output_dir / timestamp
    run_output_dir.mkdir(parents=True, exist_ok=True)
    return run_output_dir


def write_csv(path: Path, fieldnames: List[str], rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def numeric_sort_key(value: Any) -> Tuple[int, str]:
    text = str(value or "").strip()
    return (int(text), text) if text.isdigit() else (10**9, text)


def ensure_figure_dir(output_dir: Path) -> Path:
    figure_dir = output_dir / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    for pattern in ("figure_*.png", "figure_*.svg"):
        for path in figure_dir.glob(pattern):
            path.unlink()
    return figure_dir


def save_figure(fig: plt.Figure, figure_dir: Path, stem: str) -> None:
    fig.tight_layout()
    fig.savefig(figure_dir / f"{stem}.png", dpi=300)
    fig.savefig(figure_dir / f"{stem}.svg", dpi=300)
    plt.close(fig)


def set_plot_style() -> None:
    plt.rcParams.update(
        {
            "figure.dpi": 150,
            "savefig.dpi": 300,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.alpha": 0.18,
            "font.size": 10,
        }
    )


def collect_float(row: Dict[str, Any], key: str) -> float | None:
    return to_float(row.get(key, ""))


def successful_rows(case_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [row for row in case_rows if str(row.get("status", "")).strip().lower() == "ok"]


def plot_case_similarity_trends(case_rows: List[Dict[str, Any]], figure_dir: Path) -> None:
    rows = successful_rows(case_rows)
    if not rows:
        return
    batches = sorted({str(row.get("batch_id", "")) for row in rows})
    cases = sorted({str(row.get("case_id", "")) for row in rows}, key=numeric_sort_key)
    x = np.arange(len(cases), dtype=float)
    case_to_x = {case_id: index for index, case_id in enumerate(cases)}
    colors = ["#4C72B0", "#C44E52", "#55A868", "#8172B3", "#DD8452", "#937860"]

    fig, axes = plt.subplots(2, 1, figsize=(9.6, 7.2), sharex=True)
    metric_specs = [
        ("semantic_similarity_generated_vs_updated", "Graph Semantic Similarity"),
        ("causal_narrative_similarity", "Causal Narrative Similarity"),
    ]
    for ax, (metric_key, title) in zip(axes, metric_specs):
        for index, batch_id in enumerate(batches):
            batch_rows = [
                row
                for row in rows
                if str(row.get("batch_id", "")) == batch_id
                and collect_float(row, metric_key) is not None
            ]
            if not batch_rows:
                continue
            batch_rows.sort(key=lambda row: numeric_sort_key(row.get("case_id", "")))
            xs = [case_to_x[str(row.get("case_id", ""))] for row in batch_rows]
            ys = [collect_float(row, metric_key) for row in batch_rows]
            ax.plot(
                xs,
                ys,
                marker="o",
                linewidth=1.7,
                markersize=4,
                color=colors[index % len(colors)],
                label=batch_id,
            )
        ax.set_ylabel("Similarity")
        ax.set_title(title)
        ax.set_ylim(0.0, 1.05)
        ax.legend(frameon=False, ncols=min(3, max(1, len(batches))))
    axes[-1].set_xticks(x)
    axes[-1].set_xticklabels(cases)
    axes[-1].set_xlabel("Case ID")
    save_figure(fig, figure_dir, "figure_1_case_similarity_trends")


def plot_similarity_distributions(case_rows: List[Dict[str, Any]], figure_dir: Path) -> None:
    rows = successful_rows(case_rows)
    if not rows:
        return
    batches = sorted({str(row.get("batch_id", "")) for row in rows})
    metric_specs = [
        ("semantic_similarity_generated_vs_updated", "Graph semantic", "#4C72B0"),
        ("causal_narrative_similarity", "Narrative", "#55A868"),
    ]
    width = 0.28
    x = np.arange(len(batches), dtype=float)
    offsets = np.linspace(-width / 1.2, width / 1.2, len(metric_specs))

    fig, ax = plt.subplots(figsize=(9.2, 5.6))
    for metric_index, (metric_key, metric_label, color) in enumerate(metric_specs):
        series_by_batch: List[List[float]] = []
        positions: List[float] = []
        for batch_index, batch_id in enumerate(batches):
            values = [
                value
                for value in (collect_float(row, metric_key) for row in rows if str(row.get("batch_id", "")) == batch_id)
                if value is not None
            ]
            if not values:
                continue
            series_by_batch.append(values)
            positions.append(float(x[batch_index] + offsets[metric_index]))
        if not series_by_batch:
            continue
        box = ax.boxplot(
            series_by_batch,
            positions=positions,
            widths=width,
            patch_artist=True,
            medianprops={"color": "#222222", "linewidth": 1.2},
            boxprops={"edgecolor": "#555555", "linewidth": 0.9},
            whiskerprops={"color": "#555555", "linewidth": 0.9},
            capprops={"color": "#555555", "linewidth": 0.9},
            flierprops={"marker": "o", "markersize": 3, "alpha": 0.45},
        )
        for patch in box["boxes"]:
            patch.set_facecolor(color)
            patch.set_alpha(0.48)
        ax.plot([], [], color=color, linewidth=8, alpha=0.48, label=metric_label)
    ax.set_xticks(x)
    ax.set_xticklabels(batches)
    ax.set_ylim(0.0, 1.05)
    ax.set_xlabel("Batch / Round")
    ax.set_ylabel("Similarity")
    ax.set_title("Semantic Similarity Distributions")
    ax.legend(frameon=False)
    save_figure(fig, figure_dir, "figure_2_similarity_distributions")


def plot_batch_mean_similarity(batch_rows: List[Dict[str, Any]], figure_dir: Path) -> None:
    if not batch_rows:
        return
    rows = sorted(batch_rows, key=lambda row: str(row.get("batch_id", "")))
    labels = [str(row.get("batch_id", "")) for row in rows]
    x = np.arange(len(labels), dtype=float)
    graph_values = [
        collect_float(row, "mean_semantic_similarity_generated_vs_updated") or np.nan
        for row in rows
    ]
    narrative_values = [
        collect_float(row, "mean_causal_narrative_similarity") or np.nan
        for row in rows
    ]

    fig, ax = plt.subplots(figsize=(8.8, 5.2))
    ax.plot(x, graph_values, marker="o", linewidth=1.9, color="#4C72B0", label="Graph semantic")
    ax.plot(x, narrative_values, marker="s", linewidth=1.9, color="#55A868", label="Causal narrative")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylim(0.0, 1.05)
    ax.set_xlabel("Batch / Round")
    ax.set_ylabel("Mean Similarity")
    ax.set_title("Mean Semantic Similarity by Batch")
    ax.legend(frameon=False)
    save_figure(fig, figure_dir, "figure_3_batch_mean_similarity")


def generate_semantic_figures(
    *,
    output_dir: Path,
    case_rows: List[Dict[str, Any]],
    batch_rows: List[Dict[str, Any]],
) -> Path:
    set_plot_style()
    figure_dir = ensure_figure_dir(output_dir)
    plot_case_similarity_trends(case_rows, figure_dir)
    plot_similarity_distributions(case_rows, figure_dir)
    plot_batch_mean_similarity(batch_rows, figure_dir)
    return figure_dir


def save_graph_sentences(
    *,
    output_dir: Path,
    parent_dir: Path,
    case_folder: Path,
    generated_sentences: List[str],
    updated_sentences: List[str],
    accept_all_sentences: List[str] | None = None,
    causal_narrative_sentences: List[str] | None = None,
    reference_causal_narrative_sentences: List[str] | None = None,
) -> None:
    relative_dir = case_folder.relative_to(parent_dir)
    case_output_dir = output_dir / "sentence_graphs" / relative_dir
    case_output_dir.mkdir(parents=True, exist_ok=True)
    (case_output_dir / "generated_graph_sentences.json").write_text(
        json.dumps(generated_sentences, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (case_output_dir / "updated_graph_sentences.json").write_text(
        json.dumps(updated_sentences, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if accept_all_sentences is not None:
        (case_output_dir / "accept_all_graph_sentences.json").write_text(
            json.dumps(accept_all_sentences, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if causal_narrative_sentences is not None:
        (case_output_dir / "causal_narrative_sentences.json").write_text(
            json.dumps(causal_narrative_sentences, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if reference_causal_narrative_sentences is not None:
        (case_output_dir / "reference_causal_narrative_sentences.json").write_text(
            json.dumps(reference_causal_narrative_sentences, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def evaluate_case(
    case_folder: Path,
    parent_dir: Path,
    embedding_helper: EmbeddingHelper,
    sentence_output_dir: Path | None = None,
    causal_narrative_reference_dir: Path | None = None,
) -> Dict[str, Any]:
    case_id = case_folder.name
    batch_id = infer_batch_id(case_folder, parent_dir)
    row: Dict[str, Any] = {
        "case_id": case_id,
        "batch_id": batch_id,
        "semantic_similarity": "",
        "semantic_similarity_generated_vs_updated": "",
        "semantic_similarity_accept_all_vs_updated": "",
        "semantic_similarity_delta_accept_all_minus_generated": "",
        "causal_narrative_similarity": "",
        "generated_sentence_count": "",
        "updated_sentence_count": "",
        "accept_all_sentence_count": "",
        "causal_narrative_step_count": "",
        "reference_causal_narrative_step_count": "",
        "embedding_model": embedding_helper.model,
        "status": "failed",
        "warnings": "",
    }

    try:
        generated_graph = load_json(case_folder / "causal_graph.json")
        updated_path = resolve_updated_graph_path(case_folder)
        if updated_path is None:
            raise FileNotFoundError("No updated_causal_graph*.json file found.")
        updated_graph = load_json(updated_path)

        generated_sentences = graph_to_sentences(generated_graph)
        updated_sentences = graph_to_sentences(updated_graph)
        accept_all_path = resolve_accept_all_graph_path(case_folder)
        accept_all_sentences: List[str] | None = None
        if accept_all_path is not None:
            accept_all_graph = load_json(accept_all_path)
            accept_all_sentences = graph_to_sentences(accept_all_graph)

        causal_narrative_sentences: List[str] = []
        reference_causal_narrative_sentences: List[str] = []
        causal_narrative_similarity: float | None = None
        causal_narrative_path = case_folder / "causal_narrative_extraction_output.json"
        reference_causal_narrative_path = resolve_causal_narrative_reference_path(
            case_folder=case_folder,
            reference_dir=causal_narrative_reference_dir,
        )
        if causal_narrative_path.exists() and reference_causal_narrative_path is not None:
            causal_narrative_sentences = causal_narrative_to_sentences(load_json(causal_narrative_path))
            reference_causal_narrative_sentences = causal_narrative_to_sentences(
                load_json(reference_causal_narrative_path)
            )

        if sentence_output_dir is not None:
            save_graph_sentences(
                output_dir=sentence_output_dir,
                parent_dir=parent_dir,
                case_folder=case_folder,
                generated_sentences=generated_sentences,
                updated_sentences=updated_sentences,
                accept_all_sentences=accept_all_sentences,
                causal_narrative_sentences=causal_narrative_sentences,
                reference_causal_narrative_sentences=reference_causal_narrative_sentences,
            )

        generated_vector = embedding_helper.embed_graph_sentences(generated_sentences)
        updated_vector = embedding_helper.embed_graph_sentences(updated_sentences)
        similarity_generated_vs_updated = cosine_similarity(generated_vector, updated_vector)

        similarity_accept_all_vs_updated: float | None = None
        if accept_all_sentences is not None:
            accept_all_vector = embedding_helper.embed_graph_sentences(accept_all_sentences)
            similarity_accept_all_vs_updated = cosine_similarity(accept_all_vector, updated_vector)

        delta_value: float | None = None
        if similarity_accept_all_vs_updated is not None:
            delta_value = similarity_accept_all_vs_updated - similarity_generated_vs_updated

        if causal_narrative_sentences and reference_causal_narrative_sentences:
            causal_narrative_vector = embedding_helper.embed_graph_sentences(causal_narrative_sentences)
            reference_causal_narrative_vector = embedding_helper.embed_graph_sentences(
                reference_causal_narrative_sentences
            )
            causal_narrative_similarity = cosine_similarity(
                causal_narrative_vector,
                reference_causal_narrative_vector,
            )

        warnings_list: List[str] = []
        if updated_path.name != "updated_causal_graph.json":
            warnings_list.append(f"Used fallback updated graph file: {updated_path.name}.")
        if accept_all_path is None:
            warnings_list.append("Missing updated_causal_graph_accept_all.json.")
        elif accept_all_path.name != "updated_causal_graph_accept_all.json":
            warnings_list.append(f"Used fallback accept-all graph file: {accept_all_path.name}.")
        if not causal_narrative_path.exists():
            warnings_list.append("Missing causal_narrative_extraction_output.json.")
        if reference_causal_narrative_path is None:
            warnings_list.append("Missing reference causal_narrative_extraction_output.json.")

        row.update(
            {
                "semantic_similarity": f"{similarity_generated_vs_updated:.6f}",
                "semantic_similarity_generated_vs_updated": f"{similarity_generated_vs_updated:.6f}",
                "semantic_similarity_accept_all_vs_updated": (
                    f"{similarity_accept_all_vs_updated:.6f}"
                    if similarity_accept_all_vs_updated is not None
                    else ""
                ),
                "semantic_similarity_delta_accept_all_minus_generated": (
                    f"{delta_value:.6f}" if delta_value is not None else ""
                ),
                "causal_narrative_similarity": (
                    f"{causal_narrative_similarity:.6f}"
                    if causal_narrative_similarity is not None
                    else ""
                ),
                "generated_sentence_count": len(generated_sentences),
                "updated_sentence_count": len(updated_sentences),
                "accept_all_sentence_count": (
                    len(accept_all_sentences) if accept_all_sentences is not None else ""
                ),
                "causal_narrative_step_count": (
                    len(causal_narrative_sentences) if causal_narrative_path.exists() else ""
                ),
                "reference_causal_narrative_step_count": (
                    len(reference_causal_narrative_sentences)
                    if reference_causal_narrative_path is not None
                    else ""
                ),
                "status": "ok",
                "warnings": " | ".join(warnings_list),
            }
        )
    except Exception as exc:
        row["warnings"] = f"{type(exc).__name__}: {exc}"

    return row


def build_batch_rows(case_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in case_rows:
        grouped.setdefault(str(row["batch_id"]), []).append(row)

    batch_rows: List[Dict[str, Any]] = []
    for batch_id in sorted(grouped):
        rows = grouped[batch_id]
        success_rows = [row for row in rows if row["status"] == "ok"]
        semantic_values = [
            value
            for value in (to_float(row.get("semantic_similarity", "")) for row in success_rows)
            if value is not None
        ]
        generated_vs_updated_values = [
            value
            for value in (
                to_float(row.get("semantic_similarity_generated_vs_updated", ""))
                for row in success_rows
            )
            if value is not None
        ]
        accept_all_vs_updated_values = [
            value
            for value in (
                to_float(row.get("semantic_similarity_accept_all_vs_updated", ""))
                for row in success_rows
            )
            if value is not None
        ]
        delta_values = [
            value
            for value in (
                to_float(row.get("semantic_similarity_delta_accept_all_minus_generated", ""))
                for row in success_rows
            )
            if value is not None
        ]
        causal_narrative_values = [
            value
            for value in (
                to_float(row.get("causal_narrative_similarity", "")) for row in success_rows
            )
            if value is not None
        ]
        generated_sentence_values = [
            value
            for value in (to_float(row.get("generated_sentence_count", "")) for row in success_rows)
            if value is not None
        ]
        updated_sentence_values = [
            value
            for value in (to_float(row.get("updated_sentence_count", "")) for row in success_rows)
            if value is not None
        ]
        accept_all_sentence_values = [
            value
            for value in (to_float(row.get("accept_all_sentence_count", "")) for row in success_rows)
            if value is not None
        ]
        causal_narrative_step_values = [
            value
            for value in (to_float(row.get("causal_narrative_step_count", "")) for row in success_rows)
            if value is not None
        ]
        reference_causal_narrative_step_values = [
            value
            for value in (
                to_float(row.get("reference_causal_narrative_step_count", ""))
                for row in success_rows
            )
            if value is not None
        ]
        batch_rows.append(
            {
                "batch_id": batch_id,
                "case_count": len(rows),
                "success_case_count": len(success_rows),
                "failed_case_count": len(rows) - len(success_rows),
                "mean_semantic_similarity": mean_or_blank(semantic_values),
                "mean_semantic_similarity_generated_vs_updated": mean_or_blank(generated_vs_updated_values),
                "mean_semantic_similarity_accept_all_vs_updated": mean_or_blank(accept_all_vs_updated_values),
                "mean_semantic_similarity_delta_accept_all_minus_generated": mean_or_blank(delta_values),
                "mean_causal_narrative_similarity": mean_or_blank(causal_narrative_values),
                "mean_generated_sentence_count": mean_or_blank(generated_sentence_values),
                "mean_updated_sentence_count": mean_or_blank(updated_sentence_values),
                "mean_accept_all_sentence_count": mean_or_blank(accept_all_sentence_values),
                "mean_causal_narrative_step_count": mean_or_blank(causal_narrative_step_values),
                "mean_reference_causal_narrative_step_count": mean_or_blank(
                    reference_causal_narrative_step_values
                ),
            }
        )
    return batch_rows


def build_overall_summary(case_rows: List[Dict[str, Any]], batch_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    success_rows = [row for row in case_rows if row["status"] == "ok"]
    semantic_values = [
        value
        for value in (to_float(row.get("semantic_similarity", "")) for row in success_rows)
        if value is not None
    ]
    generated_vs_updated_values = [
        value
        for value in (
            to_float(row.get("semantic_similarity_generated_vs_updated", ""))
            for row in success_rows
        )
        if value is not None
    ]
    accept_all_vs_updated_values = [
        value
        for value in (
            to_float(row.get("semantic_similarity_accept_all_vs_updated", ""))
            for row in success_rows
        )
        if value is not None
    ]
    delta_values = [
        value
        for value in (
            to_float(row.get("semantic_similarity_delta_accept_all_minus_generated", ""))
            for row in success_rows
        )
        if value is not None
    ]
    causal_narrative_values = [
        value
        for value in (
            to_float(row.get("causal_narrative_similarity", "")) for row in success_rows
        )
        if value is not None
    ]
    generated_sentence_values = [
        value
        for value in (to_float(row.get("generated_sentence_count", "")) for row in success_rows)
        if value is not None
    ]
    updated_sentence_values = [
        value
        for value in (to_float(row.get("updated_sentence_count", "")) for row in success_rows)
        if value is not None
    ]
    accept_all_sentence_values = [
        value
        for value in (to_float(row.get("accept_all_sentence_count", "")) for row in success_rows)
        if value is not None
    ]
    causal_narrative_step_values = [
        value
        for value in (to_float(row.get("causal_narrative_step_count", "")) for row in success_rows)
        if value is not None
    ]
    reference_causal_narrative_step_values = [
        value
        for value in (
            to_float(row.get("reference_causal_narrative_step_count", ""))
            for row in success_rows
        )
        if value is not None
    ]
    return [
        {
            "total_batch_count": len(batch_rows),
            "total_case_count": len(case_rows),
            "successful_case_count": len(success_rows),
            "failed_case_count": len(case_rows) - len(success_rows),
            "overall_mean_semantic_similarity": mean_or_blank(semantic_values),
            "overall_mean_semantic_similarity_generated_vs_updated": mean_or_blank(generated_vs_updated_values),
            "overall_mean_semantic_similarity_accept_all_vs_updated": mean_or_blank(accept_all_vs_updated_values),
            "overall_mean_semantic_similarity_delta_accept_all_minus_generated": mean_or_blank(delta_values),
            "overall_mean_causal_narrative_similarity": mean_or_blank(causal_narrative_values),
            "overall_mean_generated_sentence_count": mean_or_blank(generated_sentence_values),
            "overall_mean_updated_sentence_count": mean_or_blank(updated_sentence_values),
            "overall_mean_accept_all_sentence_count": mean_or_blank(accept_all_sentence_values),
            "overall_mean_causal_narrative_step_count": mean_or_blank(causal_narrative_step_values),
            "overall_mean_reference_causal_narrative_step_count": mean_or_blank(
                reference_causal_narrative_step_values
            ),
        }
    ]


def main() -> Path:
    args = parse_args()
    ensure_openai_env()
    parent_dir: Path = args.parent_dir
    base_output_dir = args.output_dir or (parent_dir / "result_semantic")
    output_dir = make_run_output_dir(base_output_dir)
    case_folders = find_case_folders(parent_dir)

    print(f"Evaluating {len(case_folders)} case(s) under {parent_dir}.")
    embedding_helper = EmbeddingHelper(
        client=OpenAI(),
        model=args.embedding_model,
        cache={},
        lock=threading.Lock(),
    )
    worker_count = max(1, int(args.workers))
    sentence_output_dir = output_dir if args.save_sentences else None
    case_rows: List[Dict[str, Any]] = []
    if worker_count == 1:
        for folder in tqdm(
            case_folders,
            desc="Semantic evaluation",
            unit="case",
            dynamic_ncols=True,
            disable=not args.show_progress,
        ):
            case_rows.append(
                evaluate_case(
                    folder,
                    parent_dir,
                    embedding_helper,
                    sentence_output_dir=sentence_output_dir,
                    causal_narrative_reference_dir=args.causal_narrative_reference_dir,
                )
            )
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [
                executor.submit(
                    evaluate_case,
                    folder,
                    parent_dir,
                    embedding_helper,
                    sentence_output_dir,
                    args.causal_narrative_reference_dir,
                )
                for folder in case_folders
            ]
            for future in tqdm(
                as_completed(futures),
                total=len(futures),
                desc="Semantic evaluation",
                unit="case",
                dynamic_ncols=True,
                disable=not args.show_progress,
            ):
                case_rows.append(future.result())
        case_rows.sort(key=lambda row: (str(row.get("batch_id", "")), str(row.get("case_id", ""))))
    batch_rows = build_batch_rows(case_rows)
    overall_rows = build_overall_summary(case_rows, batch_rows)

    write_csv(output_dir / "case_semantic_scores.csv", CASE_SCORE_COLUMNS, case_rows)
    write_csv(output_dir / "batch_semantic_scores.csv", BATCH_SCORE_COLUMNS, batch_rows)
    write_csv(output_dir / "overall_semantic_summary.csv", OVERALL_SUMMARY_COLUMNS, overall_rows)
    figures_dir = generate_semantic_figures(
        output_dir=output_dir,
        case_rows=case_rows,
        batch_rows=batch_rows,
    )

    success_cases = sum(1 for row in case_rows if row["status"] == "ok")
    failed_cases = len(case_rows) - success_cases
    print(f"Completed semantic evaluation. ok={success_cases}, fail={failed_cases}.")
    print(f"Saved semantic evaluation CSV files to {output_dir}.")
    print(f"Saved semantic evaluation figures to {figures_dir}.")
    return output_dir


if __name__ == "__main__":
    main()
