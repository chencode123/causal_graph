from __future__ import annotations

"""Run audited five-run node, edge, and semantic evaluation for four conditions."""

import argparse
import csv
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

from openai import OpenAI
from dotenv import load_dotenv
from tqdm import tqdm

from run_semantic_evaluation import (
    average_vectors,
    cosine_similarity,
    graph_to_sentences,
    normalize_vector,
)
from scripts.evaluate_soft_matching_api import (
    EmbeddingHelper,
    build_node_matches,
    compute_edge_soft_metrics,
    ensure_openai_env,
    extract_edges,
    extract_typed_nodes,
    f1_from_precision_recall,
    normalize_text,
    safe_divide,
)
from utils.evaluation_case_filters import (
    DEFAULT_EXCLUDED_CASES_PATH,
    load_excluded_case_keys,
    normalize_case_key,
)


PROJECT_ROOT = Path(__file__).resolve().parent
REFERENCE_ROOT = PROJECT_ROOT / "runs/stability_test/rounds/round_1"
OUTPUT_ROOT = PROJECT_ROOT / "runs/stability_test/evaluation_final/auxiliary"
DEFAULT_CACHE_DIR = PROJECT_ROOT / "runs/stability_test/final_auxiliary_embedding_cache"
EXPECTED_REPORTS = 124
EXPECTED_EXCLUSIONS = 12
EXPECTED_HELD_OUT = 112
EXPECTED_RUNS = 5
DEFAULT_MODEL = "text-embedding-3-small"
DEFAULT_NODE_THRESHOLD = 0.40
THRESHOLD_GRID = tuple(round(0.40 + index * 0.05, 2) for index in range(12))


@dataclass(frozen=True)
class ConditionSpec:
    condition: str
    root: Path
    run_labels: tuple[str, ...]
    prediction_file: str


CONDITIONS = (
    ConditionSpec(
        "single_pass",
        PROJECT_ROOT / "runs/stability_test/single_pass_baseline_all_batches",
        tuple(f"run_{index:02d}" for index in range(1, 6)),
        "causal_graph.json",
    ),
    ConditionSpec(
        "no_revision",
        PROJECT_ROOT / "runs/stability_test/no_revision",
        tuple(f"round_{index}" for index in range(1, 6)),
        "no_revision_causal_graph.json",
    ),
    ConditionSpec(
        "revision",
        PROJECT_ROOT / "runs/stability_test/rounds",
        tuple(f"round_{index}" for index in range(1, 6)),
        "updated_causal_graph_accept_all.json",
    ),
    ConditionSpec(
        "revision_fs",
        PROJECT_ROOT / "runs/stability_test/rounds_with_few_shot",
        tuple(f"round_{index}" for index in range(1, 6)),
        "updated_causal_graph_accept_all.json",
    ),
)


CASE_COLUMNS = (
    "condition",
    "run",
    "report_id",
    "batch_id",
    "case_id",
    "soft_node_precision",
    "soft_node_recall",
    "soft_node_f1",
    "soft_edge_precision",
    "soft_edge_recall",
    "soft_edge_f1",
    "semantic_similarity",
    "pred_node_count",
    "gold_node_count",
    "pred_edge_count",
    "gold_edge_count",
    "matched_node_pair_count",
    "matched_edge_pair_count",
    "node_match_threshold",
    "relation_matching",
    "embedding_model",
    "status",
    "warnings",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--embedding-model", default=DEFAULT_MODEL)
    parser.add_argument("--embedding-batch-size", type=int, default=256)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--skip-cache-write",
        action="store_true",
        help="Keep newly requested embeddings in memory without writing per-text cache files.",
    )
    parser.add_argument("--exclude-case-list", type=Path, default=DEFAULT_EXCLUDED_CASES_PATH)
    parser.add_argument(
        "--node-threshold",
        type=float,
        default=DEFAULT_NODE_THRESHOLD,
        help=(
            "Frozen node-matching threshold (default: 0.40), selected on the "
            "12 excluded development cases before held-out evaluation."
        ),
    )
    return parser.parse_args()


def load_json_retry(path: Path) -> dict[str, Any]:
    for attempt in range(1, 4):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            if exc.errno != 22 or attempt == 3:
                raise
            time.sleep(0.25 * attempt)
    raise AssertionError("unreachable")


def reference_paths() -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in sorted(REFERENCE_ROOT.glob("batch_*/*/updated_causal_graph.json")):
        key = normalize_case_key(f"{path.parent.parent.name}/{path.parent.name}")
        result[key] = path
    return result


def condition_paths(spec: ConditionSpec) -> dict[tuple[str, str], Path]:
    result: dict[tuple[str, str], Path] = {}
    for run_label in spec.run_labels:
        for path in sorted((spec.root / run_label).glob(f"batch_*/*/{spec.prediction_file}")):
            report_id = normalize_case_key(f"{path.parent.parent.name}/{path.parent.name}")
            result[(run_label, report_id)] = path
    return result


def preflight(exclusions: set[str]) -> tuple[dict[str, Path], dict[str, dict[tuple[str, str], Path]]]:
    references = reference_paths()
    if len(references) != EXPECTED_REPORTS:
        raise RuntimeError(f"Expected {EXPECTED_REPORTS} references, found {len(references)}")
    if len(exclusions) != EXPECTED_EXCLUSIONS or not exclusions <= set(references):
        raise RuntimeError("The fixed 12-report development exclusion is not aligned with references.")
    held_out = set(references) - exclusions
    if len(held_out) != EXPECTED_HELD_OUT:
        raise RuntimeError(f"Expected {EXPECTED_HELD_OUT} held-out reports, found {len(held_out)}")

    discovered: dict[str, dict[tuple[str, str], Path]] = {}
    for spec in CONDITIONS:
        paths = condition_paths(spec)
        # The new No Revision condition was generated only for the frozen
        # held-out panel. Other historical conditions retain development-case
        # outputs, which are used only for provenance and never scored here.
        expected_reports = held_out if spec.condition == "no_revision" else set(references)
        expected_keys = {
            (run_label, report_id)
            for run_label in spec.run_labels
            for report_id in expected_reports
        }
        if set(paths) != expected_keys:
            missing = sorted(expected_keys - set(paths))
            extra = sorted(set(paths) - expected_keys)
            raise RuntimeError(
                f"{spec.condition}: incomplete inputs; missing={missing[:10]}, extra={extra[:10]}"
            )
        discovered[spec.condition] = paths
    return references, discovered


def prepare_nodes(data: dict[str, Any]) -> list[dict[str, str]]:
    """Embed node text only; ontology type is enforced separately in matching."""
    nodes = extract_typed_nodes(data)
    for node in nodes:
        text = normalize_text(node.get("text") or node.get("node_id"))
        node["embedding_text"] = text or normalize_text(node.get("node_id"))
    return nodes


def node_metrics(
    pred_nodes: list[dict[str, str]],
    gold_nodes: list[dict[str, str]],
    threshold: float,
    helper: EmbeddingHelper,
) -> tuple[float, float, float, int, dict[str, tuple[str, float]]]:
    matches, mapping = build_node_matches(pred_nodes, gold_nodes, threshold, helper)
    true_positive_weight = sum(score for _, _, score in matches)
    precision = safe_divide(true_positive_weight, float(len(pred_nodes)))
    recall = safe_divide(true_positive_weight, float(len(gold_nodes)))
    return precision, recall, f1_from_precision_recall(precision, recall), len(matches), mapping


def graph_embedding(data: dict[str, Any], helper: EmbeddingHelper) -> list[float]:
    sentences = graph_to_sentences(data)
    if not sentences:
        return []
    vectors = [normalize_vector(helper.embed_text(sentence)) for sentence in sentences]
    return normalize_vector(average_vectors(vectors))


def collect_embedding_texts(
    references: dict[str, Path],
    paths_by_condition: dict[str, dict[tuple[str, str], Path]],
) -> set[str]:
    """Collect every unique node text and edge-triple sentence before evaluation."""
    unique_paths = set(references.values())
    for condition_paths_map in paths_by_condition.values():
        unique_paths.update(condition_paths_map.values())
    texts: set[str] = set()
    for path in tqdm(sorted(unique_paths), desc="Collecting embedding texts", unit="graph"):
        data = load_json_retry(path)
        texts.update(node["embedding_text"] for node in prepare_nodes(data) if node["embedding_text"])
        texts.update(sentence for sentence in graph_to_sentences(data) if sentence)
    return texts


def prewarm_embeddings(
    texts: set[str],
    helper: EmbeddingHelper,
    batch_size: int,
    workers: int,
    write_cache: bool = True,
) -> int:
    """Load disk hits and request all missing embeddings in batched API calls."""
    if batch_size < 1:
        raise ValueError("--embedding-batch-size must be at least 1")
    missing: list[str] = []
    invalid_cache_count = 0
    existing: list[tuple[str, Path]] = []
    # Google Drive-backed workspaces make thousands of individual exists()
    # calls disproportionately expensive. Enumerate the flat cache once and
    # match the deterministic SHA-256 filenames in memory.
    cached_names = {path.name for path in helper.cache_dir.glob("*.json")}
    for text in tqdm(sorted(texts), desc="Indexing embedding cache", unit="text"):
        path = helper.cache_path_for_text(text)
        if path.name in cached_names:
            existing.append((text, path))
        else:
            missing.append(text)

    def load_one(item: tuple[str, Path]) -> tuple[str, list[float] | None]:
        text, path = item
        try:
            return text, helper.load_cached_vector(path)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return text, None

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(load_one, item) for item in existing]
        for future in tqdm(
            as_completed(futures),
            total=len(futures),
            desc="Loading embedding cache",
            unit="text",
        ):
            text, vector = future.result()
            if vector is not None:
                helper.cache[text] = vector
                helper.disk_hit_count += 1
            else:
                invalid_cache_count += 1
                missing.append(text)
    print(
        f"Unique embedding texts: {len(texts)}; missing from disk cache: {len(missing)}; "
        f"invalid cache entries to replace: {invalid_cache_count}"
    )
    chunks = [missing[start : start + batch_size] for start in range(0, len(missing), batch_size)]

    def embed_chunk(chunk: list[str]) -> list[tuple[str, list[float]]]:
        response = helper.client.embeddings.create(model=helper.model, input=chunk)
        ordered = sorted(response.data, key=lambda item: item.index)
        if len(ordered) != len(chunk):
            raise RuntimeError("Embedding batch returned an unexpected vector count")
        return [
            (text, [float(value) for value in item.embedding])
            for text, item in zip(chunk, ordered)
        ]

    save_futures = []
    with ThreadPoolExecutor(max_workers=workers) as executor, ThreadPoolExecutor(
        max_workers=workers
    ) as save_executor:
        futures = [executor.submit(embed_chunk, chunk) for chunk in chunks]
        for future in tqdm(
            as_completed(futures),
            total=len(futures),
            desc="Embedding missing texts",
            unit="batch",
        ):
            for text, vector in future.result():
                helper.cache[text] = vector
                if write_cache:
                    save_futures.append(
                        save_executor.submit(
                            helper.save_cached_vector,
                            helper.cache_path_for_text(text),
                            text,
                            vector,
                        )
                    )
            helper.api_call_count += 1
        for future in tqdm(
            as_completed(save_futures),
            total=len(save_futures),
            desc="Writing embedding cache",
            unit="text",
        ):
            future.result()
    return invalid_cache_count


def calibrate_threshold(
    references: dict[str, Path],
    predictions: dict[tuple[str, str], Path],
    exclusions: set[str],
    helper: EmbeddingHelper,
) -> tuple[float, list[dict[str, Any]]]:
    """Choose one threshold on development reports, never on held-out reports."""
    calibration_pairs: list[tuple[list[dict[str, str]], list[dict[str, str]]]] = []
    for report_id in sorted(exclusions):
        pred = load_json_retry(predictions[("round_1", report_id)])
        gold = load_json_retry(references[report_id])
        calibration_pairs.append((prepare_nodes(pred), prepare_nodes(gold)))

    rows: list[dict[str, Any]] = []
    for threshold in THRESHOLD_GRID:
        values = [
            node_metrics(pred, gold, threshold, helper)[2]
            for pred, gold in calibration_pairs
        ]
        rows.append(
            {
                "node_match_threshold": threshold,
                "development_report_count": len(values),
                "mean_soft_node_f1": mean(values),
            }
        )
    # Prefer the stricter threshold when development means tie.
    best = max(rows, key=lambda row: (row["mean_soft_node_f1"], row["node_match_threshold"]))
    return float(best["node_match_threshold"]), rows


def evaluate_one(
    *,
    condition: str,
    run_label: str,
    report_id: str,
    prediction_path: Path,
    reference_path: Path,
    threshold: float,
    helper: EmbeddingHelper,
) -> dict[str, Any]:
    batch_id, case_id = report_id.split("/", 1)
    row: dict[str, Any] = {
        "condition": condition,
        "run": run_label,
        "report_id": report_id,
        "batch_id": batch_id,
        "case_id": case_id,
        "node_match_threshold": threshold,
        "relation_matching": "exact_normalized_relation",
        "embedding_model": helper.model,
        "status": "failed",
        "warnings": "",
    }
    try:
        pred = load_json_retry(prediction_path)
        gold = load_json_retry(reference_path)
        pred_nodes = prepare_nodes(pred)
        gold_nodes = prepare_nodes(gold)
        pred_edges = extract_edges(pred)
        gold_edges = extract_edges(gold)
        node_precision, node_recall, node_f1, matched_nodes, mapping = node_metrics(
            pred_nodes, gold_nodes, threshold, helper
        )
        edge_precision, edge_recall, edge_f1, matched_edges = compute_edge_soft_metrics(
            pred_edges,
            gold_edges,
            mapping,
            1.0,
        )
        semantic = cosine_similarity(graph_embedding(pred, helper), graph_embedding(gold, helper))
        row.update(
            {
                "soft_node_precision": node_precision,
                "soft_node_recall": node_recall,
                "soft_node_f1": node_f1,
                "soft_edge_precision": edge_precision,
                "soft_edge_recall": edge_recall,
                "soft_edge_f1": edge_f1,
                "semantic_similarity": semantic,
                "pred_node_count": len(pred_nodes),
                "gold_node_count": len(gold_nodes),
                "pred_edge_count": len(pred_edges),
                "gold_edge_count": len(gold_edges),
                "matched_node_pair_count": matched_nodes,
                "matched_edge_pair_count": matched_edges,
                "status": "ok",
            }
        )
    except Exception as exc:
        row["warnings"] = f"{type(exc).__name__}: {exc}"
    return row


def write_csv(path: Path, rows: list[dict[str, Any]], columns: tuple[str, ...] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(columns or tuple(rows[0]))
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    if args.workers < 1:
        raise ValueError("--workers must be at least 1")
    load_dotenv(PROJECT_ROOT / ".env_openai", override=True)
    ensure_openai_env()
    exclusions = load_excluded_case_keys(args.exclude_case_list)
    references, paths_by_condition = preflight(exclusions)
    held_out = sorted(set(references) - exclusions)

    output_dir = args.output_root.resolve() / datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=False)
    helper = EmbeddingHelper(
        client=OpenAI(),
        model=args.embedding_model,
        cache={},
        lock=threading.Lock(),
        cache_dir=args.cache_dir.resolve(),
        use_embedding_cache=True,
    )

    embedding_texts = collect_embedding_texts(references, paths_by_condition)
    invalid_cache_count = prewarm_embeddings(
        embedding_texts,
        helper,
        args.embedding_batch_size,
        args.workers,
        write_cache=not args.skip_cache_write,
    )

    calibration_rows: list[dict[str, Any]] = []
    if args.node_threshold is None:
        threshold, calibration_rows = calibrate_threshold(
            references,
            paths_by_condition["no_revision"],
            exclusions,
            helper,
        )
        write_csv(output_dir / "node_threshold_calibration.csv", calibration_rows)
    else:
        threshold = float(args.node_threshold)
    if not 0 <= threshold <= 1:
        raise ValueError("Node threshold must lie in [0, 1]")
    print(f"Node threshold: {threshold:.2f}")
    print("Relation matching: exact")
    print(f"Held-out reports: {len(held_out)}; runs: {EXPECTED_RUNS}; conditions: {len(CONDITIONS)}")

    futures = {}
    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        for spec in CONDITIONS:
            for run_label in spec.run_labels:
                for report_id in held_out:
                    future = executor.submit(
                        evaluate_one,
                        condition=spec.condition,
                        run_label=run_label,
                        report_id=report_id,
                        prediction_path=paths_by_condition[spec.condition][(run_label, report_id)],
                        reference_path=references[report_id],
                        threshold=threshold,
                        helper=helper,
                    )
                    futures[future] = (spec.condition, run_label, report_id)
        with tqdm(total=len(futures), desc="Auxiliary evaluation", unit="graph") as progress:
            for future in as_completed(futures):
                rows.append(future.result())
                progress.update(1)

    rows.sort(key=lambda row: (row["condition"], row["run"], row["report_id"]))
    failures = [row for row in rows if row["status"] != "ok"]
    if failures:
        write_csv(output_dir / "failed_rows.csv", failures, CASE_COLUMNS)
        raise RuntimeError(f"{len(failures)} auxiliary evaluation rows failed: {output_dir}")

    expected_per_condition = EXPECTED_HELD_OUT * EXPECTED_RUNS
    condition_audit: dict[str, Any] = {}
    for spec in CONDITIONS:
        selected = [row for row in rows if row["condition"] == spec.condition]
        reports = {row["report_id"] for row in selected}
        runs = {row["run"] for row in selected}
        if len(selected) != expected_per_condition or len(reports) != EXPECTED_HELD_OUT or runs != set(spec.run_labels):
            raise RuntimeError(f"Incomplete final panel for {spec.condition}")
        condition_audit[spec.condition] = {
            "report_run_observations": len(selected),
            "independent_reports": len(reports),
            "runs": sorted(runs),
        }

    write_csv(output_dir / "combined_auxiliary_case_scores.csv", rows, CASE_COLUMNS)
    audit = {
        "reference_root": str(REFERENCE_ROOT.resolve()),
        "excluded_case_list": str(args.exclude_case_list.resolve()),
        "excluded_development_reports": sorted(exclusions),
        "held_out_report_count": len(held_out),
        "runs_per_condition": EXPECTED_RUNS,
        "node_embedding_text": "normalized node text without repeated ontology type",
        "node_match_threshold": threshold,
        "threshold_selection": (
            "fixed CLI value" if args.node_threshold is not None
            else "max mean soft node F1 on 12 excluded development reports; stricter tie break"
        ),
        "threshold_grid": list(THRESHOLD_GRID) if calibration_rows else None,
        "edge_relation_matching": "exact normalized relation",
        "semantic_representation": "mean normalized embedding of directed edge-triple sentences",
        "embedding_model": args.embedding_model,
        "embedding_cache_dir": str(args.cache_dir.resolve()),
        "new_embeddings_written_to_disk_cache": not args.skip_cache_write,
        "embedding_cache_memory_hits": helper.memory_hit_count,
        "embedding_cache_disk_hits": helper.disk_hit_count,
        "invalid_embedding_cache_entries_replaced": invalid_cache_count,
        "embedding_api_calls": helper.api_call_count,
        "conditions": condition_audit,
    }
    (output_dir / "auxiliary_evaluation_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Saved {len(rows)} rows: {output_dir}")
    print(
        f"Embedding cache hits: memory={helper.memory_hit_count}, disk={helper.disk_hit_count}; "
        f"API calls={helper.api_call_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
