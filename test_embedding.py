from __future__ import annotations

import os
import re
import json
from pathlib import Path
from typing import List, Tuple, Dict, Optional

import numpy as np
from dotenv import load_dotenv
from openai import OpenAI


# =============================
# Config
# =============================
load_dotenv(dotenv_path=Path(__file__).with_name(".env_openai"), override=True)

EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-large")

# Similarity thresholds (tune if needed)
EDGE_SIM_THRESHOLD = 0.86
NODE_SIM_THRESHOLD = 0.88

# If your files contain many edges, embeddings call can be big. Use batching.
EMBED_BATCH_SIZE = 128

# Cache embeddings to reduce cost when rerunning
CACHE_DIR = Path(r"runs/_eval_cache_embeddings")
CACHE_DIR.mkdir(parents=True, exist_ok=True)


# =============================
# Utilities: parsing
# =============================
EDGE_PATTERNS = [
    re.compile(r"^\s*(?P<src>.+?)\s*->\s*(?P<dst>.+?)\s*$"),
    # allow arrows like "→" if they appear
    re.compile(r"^\s*(?P<src>.+?)\s*→\s*(?P<dst>.+?)\s*$"),
]


def normalize_text(s: str) -> str:
    """Normalize node/edge text for more stable matching."""
    s = s.strip()
    # collapse whitespace
    s = re.sub(r"\s+", " ", s)
    # remove surrounding quotes/backticks
    s = s.strip('"\''"`")
    return s


def parse_edges_from_text(txt: str) -> List[Tuple[str, str]]:
    """
    Extract directed edges from a text file.
    We treat any line matching 'A -> B' (or 'A → B') as an edge.
    """
    edges: List[Tuple[str, str]] = []
    for raw_line in txt.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # ignore obvious non-edge lines
        if line.lower().startswith(("evidence:", "explanation:", "name:", "note:", "#")):
            continue

        matched = None
        for pat in EDGE_PATTERNS:
            m = pat.match(line)
            if m:
                matched = (normalize_text(m.group("src")), normalize_text(m.group("dst")))
                break
        if matched:
            src, dst = matched
            # filter out degenerate edges
            if src and dst and src != dst:
                edges.append((src, dst))

    # De-duplicate while preserving order
    seen = set()
    uniq: List[Tuple[str, str]] = []
    for e in edges:
        if e not in seen:
            seen.add(e)
            uniq.append(e)
    return uniq


def edges_to_strings(edges: List[Tuple[str, str]]) -> List[str]:
    return [f"{s} -> {t}" for s, t in edges]


def edges_to_nodes(edges: List[Tuple[str, str]]) -> List[str]:
    nodes = []
    for s, t in edges:
        nodes.append(s)
        nodes.append(t)
    # de-dup preserve order
    seen = set()
    uniq = []
    for n in nodes:
        n2 = normalize_text(n)
        if n2 and n2 not in seen:
            seen.add(n2)
            uniq.append(n2)
    return uniq


# =============================
# Utilities: similarity
# =============================
def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)


def jaccard_token_similarity(a: str, b: str) -> float:
    """Fallback similarity if embeddings are unavailable."""
    ta = set(re.findall(r"[A-Za-z0-9]+", a.lower()))
    tb = set(re.findall(r"[A-Za-z0-9]+", b.lower()))
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def cache_key(texts: List[str], model: str) -> str:
    # stable cache key: model + count + simple hash
    blob = ("\n".join(texts) + f"\n__MODEL__={model}").encode("utf-8", errors="ignore")
    import hashlib
    return hashlib.sha256(blob).hexdigest()


def load_cached_embeddings(key: str) -> Optional[List[np.ndarray]]:
    path = CACHE_DIR / f"{key}.json"
    if not path.exists():
        return None
    obj = json.loads(path.read_text(encoding="utf-8"))
    vecs = [np.array(v, dtype=np.float32) for v in obj["embeddings"]]
    return vecs


def save_cached_embeddings(key: str, texts: List[str], model: str, vecs: List[np.ndarray]) -> None:
    path = CACHE_DIR / f"{key}.json"
    payload = {
        "model": model,
        "n": len(texts),
        "texts_preview": texts[:5],
        "embeddings": [v.tolist() for v in vecs],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def get_embeddings(client: OpenAI, texts: List[str], model: str) -> List[np.ndarray]:
    """
    Get embeddings for a list of texts. Uses caching and batching.
    """
    key = cache_key(texts, model)
    cached = load_cached_embeddings(key)
    if cached is not None:
        return cached

    vecs: List[np.ndarray] = []
    for i in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[i:i + EMBED_BATCH_SIZE]
        resp = client.embeddings.create(model=model, input=batch)
        # API returns in same order
        for item in resp.data:
            vecs.append(np.array(item.embedding, dtype=np.float32))

    save_cached_embeddings(key, texts, model, vecs)
    return vecs


def compute_similarity_matrix_embeddings(
    model_texts: List[str],
    human_texts: List[str],
    embedding_model: str,
) -> np.ndarray:
    """
    Returns similarity matrix shape (len(model_texts), len(human_texts)).
    """
    client = OpenAI()

    m_vecs = get_embeddings(client, model_texts, model=embedding_model)
    h_vecs = get_embeddings(client, human_texts, model=embedding_model)

    sim = np.zeros((len(model_texts), len(human_texts)), dtype=np.float32)
    for i, mv in enumerate(m_vecs):
        # vectorized cosine could be faster, but keep it simple/robust
        for j, hv in enumerate(h_vecs):
            sim[i, j] = cosine_similarity(mv, hv)
    return sim


def compute_similarity_matrix_fallback(
    model_texts: List[str],
    human_texts: List[str],
) -> np.ndarray:
    sim = np.zeros((len(model_texts), len(human_texts)), dtype=np.float32)
    for i, a in enumerate(model_texts):
        for j, b in enumerate(human_texts):
            sim[i, j] = float(jaccard_token_similarity(a, b))
    return sim


# =============================
# Matching (one-to-one)
# =============================
def greedy_one_to_one_match(sim: np.ndarray) -> List[Tuple[int, int, float]]:
    """
    Greedy maximum matching on similarity matrix.
    Returns list of (i_model, j_human, sim_ij), one-to-one.
    """
    if sim.size == 0:
        return []

    pairs = []
    for i in range(sim.shape[0]):
        for j in range(sim.shape[1]):
            pairs.append((i, j, float(sim[i, j])))

    # sort by similarity descending
    pairs.sort(key=lambda x: x[2], reverse=True)

    used_i = set()
    used_j = set()
    matched: List[Tuple[int, int, float]] = []
    for i, j, s in pairs:
        if i in used_i or j in used_j:
            continue
        used_i.add(i)
        used_j.add(j)
        matched.append((i, j, s))
    return matched


def prf(tp: int, pred_n: int, gold_n: int) -> Dict[str, float]:
    precision = tp / pred_n if pred_n else 0.0
    recall = tp / gold_n if gold_n else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


# =============================
# Evaluation
# =============================
def evaluate_set(
    model_items: List[str],
    human_items: List[str],
    threshold: float,
    use_embeddings: bool = True,
    embedding_model: str = EMBEDDING_MODEL,
) -> Dict:
    """
    Evaluate with one-to-one matching:
      TP = number of matched pairs with sim >= threshold
    """
    if not model_items and not human_items:
        return {
            "n_model": 0, "n_human": 0, "tp": 0,
            "precision": 1.0, "recall": 1.0, "f1": 1.0,
            "matches": [],
        }

    if not model_items or not human_items:
        tp = 0
        metrics = prf(tp, len(model_items), len(human_items))
        return {
            "n_model": len(model_items),
            "n_human": len(human_items),
            "tp": tp,
            **metrics,
            "matches": [],
        }

    # Build similarity matrix
    sim = None
    emb_error = None
    if use_embeddings:
        try:
            sim = compute_similarity_matrix_embeddings(model_items, human_items, embedding_model)
        except Exception as e:
            emb_error = repr(e)

    if sim is None:
        sim = compute_similarity_matrix_fallback(model_items, human_items)

    matches = greedy_one_to_one_match(sim)
    good = [(i, j, s) for (i, j, s) in matches if s >= threshold]
    tp = len(good)

    metrics = prf(tp, len(model_items), len(human_items))
    return {
        "n_model": len(model_items),
        "n_human": len(human_items),
        "tp": tp,
        **metrics,
        "used_embeddings": (emb_error is None and use_embeddings),
        "embedding_error": emb_error,
        "threshold": threshold,
        "matches": [
            {
                "model_idx": i,
                "human_idx": j,
                "sim": s,
                "model": model_items[i],
                "human": human_items[j],
                "is_tp": (s >= threshold),
            }
            for (i, j, s) in matches
        ],
    }


def find_pair_files(folder: Path) -> Tuple[Path, Path]:
    """
    Find:
      - verified_*_final_check_output.txt (human)
      - prep_final_check_output.txt (model)
    """
    model_path = folder / "prep_final_check_output.txt"
    if not model_path.exists():
        raise FileNotFoundError(f"Missing model file: {model_path}")

    verified = list(folder.glob("verified_*_final_check_output.txt"))
    if not verified:
        raise FileNotFoundError(f"Missing verified file: {folder / 'verified_*_final_check_output.txt'}")
    if len(verified) > 1:
        # pick the shortest name deterministically
        verified.sort(key=lambda p: len(p.name))
    human_path = verified[0]
    return model_path, human_path


def evaluate_folder(folder: Path) -> Dict:
    model_file, human_file = find_pair_files(folder)

    model_txt = model_file.read_text(encoding="utf-8", errors="ignore")
    human_txt = human_file.read_text(encoding="utf-8", errors="ignore")

    model_edges = parse_edges_from_text(model_txt)
    human_edges = parse_edges_from_text(human_txt)

    model_edge_strs = edges_to_strings(model_edges)
    human_edge_strs = edges_to_strings(human_edges)

    model_nodes = edges_to_nodes(model_edges)
    human_nodes = edges_to_nodes(human_edges)

    edge_eval = evaluate_set(
        model_items=model_edge_strs,
        human_items=human_edge_strs,
        threshold=EDGE_SIM_THRESHOLD,
        use_embeddings=True,
        embedding_model=EMBEDDING_MODEL,
    )

    node_eval = evaluate_set(
        model_items=model_nodes,
        human_items=human_nodes,
        threshold=NODE_SIM_THRESHOLD,
        use_embeddings=True,
        embedding_model=EMBEDDING_MODEL,
    )

    # A simple combined score (weighted)
    combined_f1 = 0.7 * edge_eval["f1"] + 0.3 * node_eval["f1"]

    return {
        "folder": str(folder),
        "model_file": str(model_file),
        "human_file": str(human_file),
        "embedding_model": EMBEDDING_MODEL,
        "edge_threshold": EDGE_SIM_THRESHOLD,
        "node_threshold": NODE_SIM_THRESHOLD,
        "edge_eval": edge_eval,
        "node_eval": node_eval,
        "combined_f1": combined_f1,
    }


def main() -> None:
    # Option A: hardcode your example folder
    FOLDER = Path(r"runs\batch_api_test\batch_1\Barton_Solvents_Static_Spark_Ignites_Explosion_Inside_Flammable_Liquid_Storage_Tank")

    result = evaluate_folder(FOLDER)

    print("\n=== Evaluation Summary ===")
    print(f"Folder       : {result['folder']}")
    print(f"Model file   : {result['model_file']}")
    print(f"Human file   : {result['human_file']}")
    print(f"Emb model    : {result['embedding_model']}")
    print(f"Edge F1      : {result['edge_eval']['f1']:.4f} (P={result['edge_eval']['precision']:.4f}, R={result['edge_eval']['recall']:.4f})")
    print(f"Node F1      : {result['node_eval']['f1']:.4f} (P={result['node_eval']['precision']:.4f}, R={result['node_eval']['recall']:.4f})")
    print(f"Combined F1  : {result['combined_f1']:.4f}")

    # Save full report (includes match list)
    out_path = Path(r"runs/_eval_reports") / (FOLDER.name + "_eval.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\nSaved report: {out_path}")

    # Optional: print top mismatches (lowest sim among matched pairs)
    matches = result["edge_eval"]["matches"]
    if matches:
        # show a few non-TPs with highest similarity (near-misses)
        near = [m for m in matches if not m["is_tp"]]
        near.sort(key=lambda x: x["sim"], reverse=True)
        print("\n--- Edge near-misses (top 10) ---")
        for m in near[:10]:
            print(f"sim={m['sim']:.4f} | MODEL: {m['model']} || HUMAN: {m['human']}")


if __name__ == "__main__":
    main()