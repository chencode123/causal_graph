from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Iterable, List, Tuple

from openai import OpenAI
from scipy.optimize import linear_sum_assignment
from tqdm import tqdm


NODE_GROUP_SPECS = (
    ("hazard_consequence_node", "hazard_consequence"),
    ("entity_nodes", "entity"),
    ("condition_nodes", "condition"),
    ("event_nodes", "event"),
)

DEFAULT_PARENT_DIR = Path(r"runs\stability_test\rounds")  # Default parent directory containing batch folders; can be overridden by --parent-dir argument.
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_BATCH_ID = None
DEFAULT_NODE_MATCH_THRESHOLD = 0
DEFAULT_RELATION_MATCH_THRESHOLD = 0
DEFAULT_COMPARISON_MODE = "generated_vs_updated"
DEFAULT_USE_EMBEDDING_CACHE = True
DEFAULT_SHOW_EMBEDDING_CACHE_SUMMARY = True

CASE_SCORE_COLUMNS = [
    "batch_id",
    "case_id",
    "comparison_mode",
    "soft_node_precision",
    "soft_node_recall",
    "soft_node_f1",
    "soft_edge_precision",
    "soft_edge_recall",
    "soft_edge_f1",
    "matched_node_pair_count",
    "matched_edge_pair_count",
    "pred_node_count",
    "gold_node_count",
    "pred_edge_count",
    "gold_edge_count",
    "embedding_model",
    "node_match_threshold",
    "relation_match_threshold",
    "status",
    "warnings",
]

BATCH_SCORE_COLUMNS = [
    "batch_id",
    "comparison_mode",
    "case_count",
    "success_case_count",
    "failed_case_count",
    "mean_soft_node_precision",
    "mean_soft_node_recall",
    "mean_soft_node_f1",
    "mean_soft_edge_precision",
    "mean_soft_edge_recall",
    "mean_soft_edge_f1",
]

OVERALL_SUMMARY_COLUMNS = [
    "comparison_mode",
    "total_batch_count",
    "total_case_count",
    "successful_case_count",
    "failed_case_count",
    "overall_mean_soft_node_precision",
    "overall_mean_soft_node_recall",
    "overall_mean_soft_node_f1",
    "overall_mean_soft_edge_precision",
    "overall_mean_soft_edge_recall",
    "overall_mean_soft_edge_f1",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate soft node/edge matching for one batch or all batches under "
            "a stability result root using embedding-based node matching."
        )
    )
    parser.add_argument(
        "--parent-dir",
        type=Path,
        default=DEFAULT_PARENT_DIR,
        help="Root directory containing batch folders and case subfolders.",
    )
    parser.add_argument(
        "--batch-id",
        default=DEFAULT_BATCH_ID,
        help=(
            "Optional batch folder name to evaluate, for example batch_4_1. "
            "If omitted, all batch folders under --parent-dir are evaluated."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=(
            "Base output directory where timestamped CSV results will be written. "
            "Defaults to <parent-dir>/result_soft_f1_api."
        ),
    )
    parser.add_argument(
        "--embedding-model",
        default=DEFAULT_EMBEDDING_MODEL,
        help="Embedding model used for node matching.",
    )
    parser.add_argument(
        "--node-match-threshold",
        type=float,
        default=DEFAULT_NODE_MATCH_THRESHOLD,
        help="Minimum node similarity required to accept a node match.",
    )
    parser.add_argument(
        "--relation-match-threshold",
        type=float,
        default=DEFAULT_RELATION_MATCH_THRESHOLD,
        help="Minimum relation similarity required to accept an edge match.",
    )
    parser.add_argument(
        "--comparison-mode",
        choices=("generated_vs_updated", "accept_all_vs_updated"),
        default=DEFAULT_COMPARISON_MODE,
        help="Which graph pair to compare for soft matching.",
    )
    parser.add_argument(
        "--embedding-cache-dir",
        type=Path,
        default=None,
        help=(
            "Directory for persistent embedding cache files. "
            "Defaults to <parent-dir>/embedding_cache/<embedding-model>."
        ),
    )
    parser.add_argument(
        "--use-embedding-cache",
        dest="use_embedding_cache",
        action="store_true",
        help="Enable persistent embedding cache lookup and save.",
    )
    parser.add_argument(
        "--skip-embedding-cache",
        dest="use_embedding_cache",
        action="store_false",
        help="Disable persistent embedding cache and always request uncached embeddings from the API.",
    )
    parser.add_argument(
        "--show-embedding-cache-summary",
        dest="show_embedding_cache_summary",
        action="store_true",
        help="Print memory hits, disk hits, and API call counts at the end of the run.",
    )
    parser.add_argument(
        "--hide-embedding-cache-summary",
        dest="show_embedding_cache_summary",
        action="store_false",
        help="Do not print memory hits, disk hits, and API call counts.",
    )
    parser.set_defaults(use_embedding_cache=DEFAULT_USE_EMBEDDING_CACHE)
    parser.set_defaults(show_embedding_cache_summary=DEFAULT_SHOW_EMBEDDING_CACHE_SUMMARY)
    return parser.parse_args()


def load_env_file(env_path: Path) -> None:
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
    if os.getenv("OPENAI_API_KEY"):
        return
    project_root = Path(__file__).resolve().parent.parent
    load_env_file(project_root / ".env_openai")


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def relation_similarity(left: str, right: str) -> float:
    left_norm = normalize_text(left)
    right_norm = normalize_text(right)
    if not left_norm and not right_norm:
        return 1.0
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0
    return SequenceMatcher(None, left_norm, right_norm).ratio()


def resolve_updated_graph_path(case_folder: Path) -> Path | None:
    exact_path = case_folder / "updated_causal_graph.json"
    return exact_path if exact_path.exists() else None


def resolve_accept_all_graph_path(case_folder: Path) -> Path | None:
    exact_path = case_folder / "updated_causal_graph_accept_all.json"
    return exact_path if exact_path.exists() else None


def find_case_folders(search_root: Path) -> List[Path]:
    if not search_root.exists():
        return []
    valid_folders: List[Path] = []
    for folder in search_root.rglob("*"):
        if not folder.is_dir():
            continue
        if (folder / "causal_graph.json").exists() and resolve_updated_graph_path(folder) is not None:
            valid_folders.append(folder)
    return sorted(valid_folders)


def infer_batch_id(case_folder: Path, parent_dir: Path) -> str:
    relative_parts = case_folder.relative_to(parent_dir).parts
    return relative_parts[0] if relative_parts else case_folder.name


def extract_typed_nodes(data: Dict[str, Any]) -> List[Dict[str, str]]:
    nodes: List[Dict[str, str]] = []
    for group_key, node_type in NODE_GROUP_SPECS:
        raw_group = data.get(group_key, [])
        if group_key == "hazard_consequence_node" and isinstance(raw_group, dict):
            raw_items = [raw_group]
        elif isinstance(raw_group, list):
            raw_items = raw_group
        else:
            raw_items = []
        for raw_node in raw_items:
            node_id = str(raw_node.get("node_id") or "").strip()
            text = str(
                raw_node.get("name")
                or raw_node.get("text")
                or node_id
            ).strip()
            nodes.append(
                {
                    "node_id": node_id,
                    "node_type": node_type,
                    "text": text,
                    "embedding_text": f"{node_type}: {normalize_text(text)}",
                }
            )
    return nodes


def extract_edges(data: Dict[str, Any]) -> List[Dict[str, str]]:
    raw_edges = data.get("edges", [])
    if not isinstance(raw_edges, list):
        return []
    edges: List[Dict[str, str]] = []
    for raw_edge in raw_edges:
        source = str(raw_edge.get("source") or "").strip()
        target = str(raw_edge.get("target") or "").strip()
        relation = str(raw_edge.get("relation") or raw_edge.get("label") or "").strip()
        if not source or not target:
            continue
        edges.append(
            {
                "source": source,
                "target": target,
                "relation": relation,
                "normalized_relation": normalize_text(relation),
            }
        )
    return edges


def l2_norm(vector: Iterable[float]) -> float:
    return sum(value * value for value in vector) ** 0.5


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
    cache_dir: Path
    use_embedding_cache: bool
    memory_hit_count: int = 0
    disk_hit_count: int = 0
    api_call_count: int = 0

    def embed_text(self, text: str) -> List[float]:
        with self.lock:
            cached = self.cache.get(text)
        if cached is not None:
            with self.lock:
                self.memory_hit_count += 1
            return cached

        cache_path = self.cache_path_for_text(text)
        if self.use_embedding_cache and cache_path.exists():
            vector = self.load_cached_vector(cache_path)
            with self.lock:
                self.cache[text] = vector
                self.disk_hit_count += 1
            return vector

        response = self.client.embeddings.create(model=self.model, input=text)
        vector = [float(value) for value in response.data[0].embedding]
        with self.lock:
            self.cache[text] = vector
            self.api_call_count += 1
        if self.use_embedding_cache:
            self.save_cached_vector(cache_path, text, vector)
        return vector

    def cache_path_for_text(self, text: str) -> Path:
        digest = hashlib.sha256(f"{self.model}\n{text}".encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.json"

    def load_cached_vector(self, path: Path) -> List[float]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return [float(value) for value in payload["embedding"]]

    def save_cached_vector(self, path: Path, text: str, vector: List[float]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "model": self.model,
            "text": text,
            "embedding": vector,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def build_node_matches(
    pred_nodes: List[Dict[str, str]],
    gold_nodes: List[Dict[str, str]],
    threshold: float,
    embedding_helper: EmbeddingHelper,
) -> Tuple[List[Tuple[int, int, float]], Dict[str, Tuple[str, float]]]:
    pred_count = len(pred_nodes)
    gold_count = len(gold_nodes)
    if pred_count == 0 or gold_count == 0:
        return [], {}

    pred_vectors = [embedding_helper.embed_text(node["embedding_text"]) for node in pred_nodes]
    gold_vectors = [embedding_helper.embed_text(node["embedding_text"]) for node in gold_nodes]

    matrix_size = pred_count + gold_count
    invalid_cost = 1_000_000.0
    cost_matrix = [[0.0 for _ in range(matrix_size)] for _ in range(matrix_size)]

    for pred_index, pred_node in enumerate(pred_nodes):
        for gold_index, gold_node in enumerate(gold_nodes):
            if pred_node["node_type"] != gold_node["node_type"]:
                cost_matrix[pred_index][gold_index] = invalid_cost
                continue
            similarity = cosine_similarity(pred_vectors[pred_index], gold_vectors[gold_index])
            cost_matrix[pred_index][gold_index] = (
                1.0 - similarity if similarity >= threshold else invalid_cost
            )
        for deletion_dummy_index in range(pred_count):
            cost_matrix[pred_index][gold_count + deletion_dummy_index] = invalid_cost
        cost_matrix[pred_index][gold_count + pred_index] = 1.0

    for insertion_dummy_index in range(gold_count):
        row_index = pred_count + insertion_dummy_index
        for gold_index in range(gold_count):
            cost_matrix[row_index][gold_index] = invalid_cost
        cost_matrix[row_index][insertion_dummy_index] = 1.0
        for deletion_dummy_index in range(pred_count):
            cost_matrix[row_index][gold_count + deletion_dummy_index] = 0.0

    row_ind, col_ind = linear_sum_assignment(cost_matrix)
    matches: List[Tuple[int, int, float]] = []
    pred_to_gold: Dict[str, Tuple[str, float]] = {}
    for row_index, col_index in zip(row_ind, col_ind):
        if row_index >= pred_count or col_index >= gold_count:
            continue
        if cost_matrix[row_index][col_index] >= invalid_cost:
            continue
        similarity = 1.0 - float(cost_matrix[row_index][col_index])
        if similarity < threshold:
            continue
        matches.append((int(row_index), int(col_index), similarity))
        pred_to_gold[pred_nodes[row_index]["node_id"]] = (gold_nodes[col_index]["node_id"], similarity)
    return matches, pred_to_gold


def safe_divide(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 1.0 if numerator <= 0 else 0.0
    return numerator / denominator


def f1_from_precision_recall(precision: float, recall: float) -> float:
    if precision + recall <= 0:
        return 0.0
    return 2.0 * precision * recall / (precision + recall)


def compute_edge_soft_metrics(
    pred_edges: List[Dict[str, str]],
    gold_edges: List[Dict[str, str]],
    pred_to_gold: Dict[str, Tuple[str, float]],
    relation_match_threshold: float,
) -> Tuple[float, float, float, int]:
    if not pred_edges and not gold_edges:
        return 1.0, 1.0, 1.0, 0
    if not pred_edges:
        return 1.0, 0.0, 0.0, 0
    if not gold_edges:
        return 0.0, 1.0, 0.0, 0

    matched_gold_indices: set[int] = set()
    matched_edge_count = 0
    matched_pair_count = 0

    for pred_edge in pred_edges:
        pred_source = pred_to_gold.get(pred_edge["source"])
        pred_target = pred_to_gold.get(pred_edge["target"])
        if pred_source is None or pred_target is None:
            continue

        candidate_index = None
        best_relation_score = 0.0
        for edge_index, gold_edge in enumerate(gold_edges):
            if edge_index in matched_gold_indices:
                continue
            if gold_edge["source"] != pred_source[0] or gold_edge["target"] != pred_target[0]:
                continue
            relation_score = relation_similarity(
                pred_edge["normalized_relation"],
                gold_edge["normalized_relation"],
            )
            if relation_score > best_relation_score:
                best_relation_score = relation_score
                candidate_index = edge_index
        if candidate_index is None or best_relation_score < relation_match_threshold:
            continue

        matched_gold_indices.add(candidate_index)
        matched_edge_count += 1
        matched_pair_count += 1

    precision = safe_divide(float(matched_edge_count), float(len(pred_edges)))
    recall = safe_divide(float(matched_edge_count), float(len(gold_edges)))
    f1 = f1_from_precision_recall(precision, recall)
    return precision, recall, f1, matched_pair_count


def evaluate_case(
    case_folder: Path,
    parent_dir: Path,
    embedding_helper: EmbeddingHelper,
    node_match_threshold: float,
    relation_match_threshold: float,
    comparison_mode: str,
) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "batch_id": infer_batch_id(case_folder, parent_dir),
        "case_id": case_folder.name,
        "comparison_mode": comparison_mode,
        "soft_node_precision": "",
        "soft_node_recall": "",
        "soft_node_f1": "",
        "soft_edge_precision": "",
        "soft_edge_recall": "",
        "soft_edge_f1": "",
        "matched_node_pair_count": "",
        "matched_edge_pair_count": "",
        "pred_node_count": "",
        "gold_node_count": "",
        "pred_edge_count": "",
        "gold_edge_count": "",
        "embedding_model": embedding_helper.model,
        "node_match_threshold": f"{node_match_threshold:.4f}",
        "relation_match_threshold": f"{relation_match_threshold:.4f}",
        "status": "failed",
        "warnings": "",
    }
    try:
        gold_path = resolve_updated_graph_path(case_folder)
        if gold_path is None:
            raise FileNotFoundError("No updated_causal_graph.json file found.")
        if comparison_mode == "accept_all_vs_updated":
            pred_path = resolve_accept_all_graph_path(case_folder)
            if pred_path is None:
                raise FileNotFoundError("No updated_causal_graph_accept_all.json file found.")
        else:
            pred_path = case_folder / "causal_graph.json"
            if not pred_path.exists():
                raise FileNotFoundError("No causal_graph.json file found.")

        pred_data = load_json(pred_path)
        gold_data = load_json(gold_path)

        pred_nodes = extract_typed_nodes(pred_data)
        gold_nodes = extract_typed_nodes(gold_data)
        pred_edges = extract_edges(pred_data)
        gold_edges = extract_edges(gold_data)

        matches, pred_to_gold = build_node_matches(
            pred_nodes,
            gold_nodes,
            node_match_threshold,
            embedding_helper,
        )
        soft_node_tp = sum(match_score for _, _, match_score in matches)
        node_precision = safe_divide(soft_node_tp, float(len(pred_nodes)))
        node_recall = safe_divide(soft_node_tp, float(len(gold_nodes)))
        node_f1 = f1_from_precision_recall(node_precision, node_recall)

        edge_precision, edge_recall, edge_f1, matched_edge_pair_count = compute_edge_soft_metrics(
            pred_edges,
            gold_edges,
            pred_to_gold,
            relation_match_threshold,
        )

        row.update(
            {
                "soft_node_precision": f"{node_precision:.6f}",
                "soft_node_recall": f"{node_recall:.6f}",
                "soft_node_f1": f"{node_f1:.6f}",
                "soft_edge_precision": f"{edge_precision:.6f}",
                "soft_edge_recall": f"{edge_recall:.6f}",
                "soft_edge_f1": f"{edge_f1:.6f}",
                "matched_node_pair_count": len(matches),
                "matched_edge_pair_count": matched_edge_pair_count,
                "pred_node_count": len(pred_nodes),
                "gold_node_count": len(gold_nodes),
                "pred_edge_count": len(pred_edges),
                "gold_edge_count": len(gold_edges),
                "status": "ok",
            }
        )
    except Exception as exc:
        row["warnings"] = f"{type(exc).__name__}: {exc}"
    return row


def to_float(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def mean_or_blank(values: Iterable[float]) -> str:
    values = list(values)
    if not values:
        return ""
    return f"{mean(values):.6f}"


def write_csv(path: Path, fieldnames: List[str], rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_batch_rows(case_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped_rows: Dict[str, List[Dict[str, Any]]] = {}
    for row in case_rows:
        batch_id = str(row.get("batch_id", "")).strip()
        grouped_rows.setdefault(batch_id, []).append(row)

    batch_rows: List[Dict[str, Any]] = []
    for batch_id in sorted(grouped_rows):
        rows = grouped_rows[batch_id]
        success_rows = [row for row in rows if row["status"] == "ok"]
        batch_rows.append(
            {
                "batch_id": batch_id,
                "comparison_mode": str(rows[0].get("comparison_mode", "")).strip(),
                "case_count": len(rows),
                "success_case_count": len(success_rows),
                "failed_case_count": len(rows) - len(success_rows),
                "mean_soft_node_precision": mean_or_blank(
                    to_float(row.get("soft_node_precision")) for row in success_rows
                    if to_float(row.get("soft_node_precision")) is not None
                ),
                "mean_soft_node_recall": mean_or_blank(
                    to_float(row.get("soft_node_recall")) for row in success_rows
                    if to_float(row.get("soft_node_recall")) is not None
                ),
                "mean_soft_node_f1": mean_or_blank(
                    to_float(row.get("soft_node_f1")) for row in success_rows
                    if to_float(row.get("soft_node_f1")) is not None
                ),
                "mean_soft_edge_precision": mean_or_blank(
                    to_float(row.get("soft_edge_precision")) for row in success_rows
                    if to_float(row.get("soft_edge_precision")) is not None
                ),
                "mean_soft_edge_recall": mean_or_blank(
                    to_float(row.get("soft_edge_recall")) for row in success_rows
                    if to_float(row.get("soft_edge_recall")) is not None
                ),
                "mean_soft_edge_f1": mean_or_blank(
                    to_float(row.get("soft_edge_f1")) for row in success_rows
                    if to_float(row.get("soft_edge_f1")) is not None
                ),
            }
        )
    return batch_rows


def build_overall_summary(case_rows: List[Dict[str, Any]], batch_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    success_rows = [row for row in case_rows if row["status"] == "ok"]
    return [
        {
            "comparison_mode": str(success_rows[0].get("comparison_mode", "")).strip() if success_rows else "",
            "total_batch_count": len(batch_rows),
            "total_case_count": len(case_rows),
            "successful_case_count": len(success_rows),
            "failed_case_count": len(case_rows) - len(success_rows),
            "overall_mean_soft_node_precision": mean_or_blank(
                to_float(row.get("soft_node_precision")) for row in success_rows
                if to_float(row.get("soft_node_precision")) is not None
            ),
            "overall_mean_soft_node_recall": mean_or_blank(
                to_float(row.get("soft_node_recall")) for row in success_rows
                if to_float(row.get("soft_node_recall")) is not None
            ),
            "overall_mean_soft_node_f1": mean_or_blank(
                to_float(row.get("soft_node_f1")) for row in success_rows
                if to_float(row.get("soft_node_f1")) is not None
            ),
            "overall_mean_soft_edge_precision": mean_or_blank(
                to_float(row.get("soft_edge_precision")) for row in success_rows
                if to_float(row.get("soft_edge_precision")) is not None
            ),
            "overall_mean_soft_edge_recall": mean_or_blank(
                to_float(row.get("soft_edge_recall")) for row in success_rows
                if to_float(row.get("soft_edge_recall")) is not None
            ),
            "overall_mean_soft_edge_f1": mean_or_blank(
                to_float(row.get("soft_edge_f1")) for row in success_rows
                if to_float(row.get("soft_edge_f1")) is not None
            ),
        }
    ]


def make_run_output_dir(base_output_dir: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = base_output_dir / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def main() -> Path:
    args = parse_args()
    ensure_openai_env()
    client = OpenAI()
    parent_dir = args.parent_dir.resolve()
    cache_dir = (
        args.embedding_cache_dir.resolve()
        if args.embedding_cache_dir is not None
        else (parent_dir / "embedding_cache" / args.embedding_model)
    )
    cache_dir.mkdir(parents=True, exist_ok=True)
    embedding_helper = EmbeddingHelper(
        client=client,
        model=args.embedding_model,
        cache={},
        lock=threading.Lock(),
        cache_dir=cache_dir,
        use_embedding_cache=args.use_embedding_cache,
    )

    if args.output_dir is not None:
        base_output_dir = args.output_dir.resolve()
    else:
        suffix = "result_soft_f1_api_accept_all_vs_updated" if args.comparison_mode == "accept_all_vs_updated" else "result_soft_f1_api"
        base_output_dir = parent_dir / suffix
    output_dir = make_run_output_dir(base_output_dir)
    search_root = (parent_dir / args.batch_id) if args.batch_id else parent_dir
    case_folders = find_case_folders(search_root)

    case_rows = [
        evaluate_case(
            case_folder,
            parent_dir,
            embedding_helper,
            args.node_match_threshold,
            args.relation_match_threshold,
            args.comparison_mode,
        )
        for case_folder in tqdm(case_folders, desc="Evaluating cases")
    ]
    batch_rows = build_batch_rows(case_rows)
    overall_rows = build_overall_summary(case_rows, batch_rows)

    write_csv(output_dir / "case_soft_f1_api_scores.csv", CASE_SCORE_COLUMNS, case_rows)
    write_csv(output_dir / "batch_soft_f1_api_scores.csv", BATCH_SCORE_COLUMNS, batch_rows)
    write_csv(output_dir / "overall_soft_f1_api_summary.csv", OVERALL_SUMMARY_COLUMNS, overall_rows)

    success_cases = sum(1 for row in case_rows if row["status"] == "ok")
    failed_cases = len(case_rows) - success_cases
    batch_scope = args.batch_id if args.batch_id else "all batches"
    print(
        f"Completed API soft F1 evaluation for {batch_scope} "
        f"({args.comparison_mode}). ok={success_cases}, fail={failed_cases}."
    )
    print(f"Saved API soft F1 CSV files to {output_dir}.")
    print(
        f"Embedding cache: {'enabled' if args.use_embedding_cache else 'disabled'} "
        f"({cache_dir})."
    )
    if args.show_embedding_cache_summary:
        print(
            "Embedding cache summary: "
            f"memory_hits={embedding_helper.memory_hit_count}, "
            f"disk_hits={embedding_helper.disk_hit_count}, "
            f"api_calls={embedding_helper.api_call_count}."
        )
    return output_dir


if __name__ == "__main__":
    main()
