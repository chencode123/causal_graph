"""
Generate per-round results table with within-round std and cross-round std.
Rows: metrics  |  Columns: condition × (R1 mean±std, R2 mean±std, R3 mean±std, Mean, Cross-round std)
"""
import pandas as pd
import numpy as np
from pathlib import Path

BASE = Path("g:/Other computers/My computer/project C/gen ai/code/llm/runs/stability_test")
ROUNDS_DIR   = BASE / "rounds"
FS_DIR       = BASE / "rounds_with_few_shot"

PY = "C:/Users/cheny/miniconda3/envs/llm/python.exe"


# ── helpers ───────────────────────────────────────────────────────────────────

def latest_csv(parent: Path, glob_pattern: str) -> Path | None:
    """Return the CSV inside the most-recently-modified timestamped subdir."""
    dirs = sorted(parent.glob("2*"), key=lambda p: p.name, reverse=True)
    for d in dirs:
        matches = list(d.glob(glob_pattern))
        if matches:
            return matches[0]
    return None


def extract_round(batch_id: str) -> str:
    """Normalize batch_id to round_N (handles 'round_1' or 'batch_X_output_round_1')."""
    import re
    m = re.search(r"(round_\d+)", batch_id)
    return m.group(1) if m else batch_id


def round_stats(df: pd.DataFrame, value_col: str) -> dict:
    """For each round, compute mean and std across cases."""
    df = df.copy()
    if "round" in df.columns:
        df["_round"] = df["round"].apply(extract_round)
    else:
        df["_round"] = df["batch_id"].apply(extract_round)
    result = {}
    rounds = ["round_1", "round_2", "round_3"]
    for r in rounds:
        vals = df.loc[df["_round"] == r, value_col].dropna()
        result[r] = {"mean": vals.mean(), "std": vals.std(ddof=1)}
    round_means = [result[r]["mean"] for r in rounds]
    result["cross_std"] = np.std(round_means, ddof=1)
    result["overall_mean"] = np.mean(round_means)
    return result


# ── load data ─────────────────────────────────────────────────────────────────

# Structural metrics (both no-rev and accept-all in one file)
struct_no_fs_csv  = latest_csv(ROUNDS_DIR / "results", "case_scores.csv")
struct_fs_csv     = latest_csv(FS_DIR / "results",     "case_scores.csv")

# Soft matching
soft_no_rev_no_fs_csv       = latest_csv(ROUNDS_DIR / "result_soft_f1_api",                    "case_soft_f1_api_scores.csv")
soft_accept_no_fs_csv       = latest_csv(ROUNDS_DIR / "result_soft_f1_api_accept_all_vs_updated", "case_soft_f1_api_scores.csv")
soft_no_rev_fs_csv          = latest_csv(ROUNDS_DIR / "result_soft_f1_api",                    "case_soft_f1_api_scores.csv")
soft_accept_fs_csv          = latest_csv(FS_DIR / "result_soft_f1_api_accept_all_vs_updated",  "case_soft_f1_api_scores.csv")

# Semantic
sem_no_fs_csv = latest_csv(ROUNDS_DIR / "result_semantic", "case_semantic_scores.csv")
sem_fs_csv    = latest_csv(FS_DIR / "result_semantic",     "case_semantic_scores.csv")

for label, path in [
    ("struct_no_fs",       struct_no_fs_csv),
    ("struct_fs",          struct_fs_csv),
    ("soft_no_rev_no_fs",  soft_no_rev_no_fs_csv),
    ("soft_accept_no_fs",  soft_accept_no_fs_csv),
    ("soft_no_rev_fs",     soft_no_rev_fs_csv),
    ("soft_accept_fs",     soft_accept_fs_csv),
    ("sem_no_fs",          sem_no_fs_csv),
    ("sem_fs",             sem_fs_csv),
]:
    status = "OK" if path and path.exists() else "MISSING"
    print(f"  {label:<22} {status}  {path or ''}")

print()

struct_no_fs  = pd.read_csv(struct_no_fs_csv)
struct_fs     = pd.read_csv(struct_fs_csv)
soft_no_rev_no_fs = pd.read_csv(soft_no_rev_no_fs_csv)
soft_accept_no_fs = pd.read_csv(soft_accept_no_fs_csv)
soft_no_rev_fs    = pd.read_csv(soft_no_rev_fs_csv)
soft_accept_fs    = pd.read_csv(soft_accept_fs_csv)
sem_no_fs = pd.read_csv(sem_no_fs_csv)
sem_fs    = pd.read_csv(sem_fs_csv)


# ── compute stats per condition ───────────────────────────────────────────────

conditions = {
    "No Revision":   {},
    "Revision":      {},
    "Revision + FS": {},
}

metrics = [
    "WL Kernel",
    "1-normGED",
    "Node Precision",
    "Node Recall",
    "Node F1",
    "Edge Precision",
    "Edge Recall",
    "Edge F1",
    "Semantic Sim.",
]

data = {cond: {m: None for m in metrics} for cond in conditions}

# WL Kernel
data["No Revision"]["WL Kernel"]    = round_stats(struct_no_fs, "structural_similarity")
data["Revision"]["WL Kernel"]       = round_stats(struct_no_fs, "structural_similarity_accept_all_vs_updated")
data["Revision + FS"]["WL Kernel"]  = round_stats(struct_fs,    "structural_similarity_accept_all_vs_updated")

# 1-normGED
data["No Revision"]["1-normGED"]    = round_stats(struct_no_fs, "graph_edit_similarity")
data["Revision"]["1-normGED"]       = round_stats(struct_no_fs, "graph_edit_similarity_accept_all_vs_updated")
data["Revision + FS"]["1-normGED"]  = round_stats(struct_fs,    "graph_edit_similarity_accept_all_vs_updated")

# Node Precision / Recall / F1
data["No Revision"]["Node Precision"]    = round_stats(soft_no_rev_no_fs, "soft_node_precision")
data["Revision"]["Node Precision"]       = round_stats(soft_accept_no_fs, "soft_node_precision")
data["Revision + FS"]["Node Precision"]  = round_stats(soft_accept_fs,    "soft_node_precision")

data["No Revision"]["Node Recall"]    = round_stats(soft_no_rev_no_fs, "soft_node_recall")
data["Revision"]["Node Recall"]       = round_stats(soft_accept_no_fs, "soft_node_recall")
data["Revision + FS"]["Node Recall"]  = round_stats(soft_accept_fs,    "soft_node_recall")

data["No Revision"]["Node F1"]    = round_stats(soft_no_rev_no_fs, "soft_node_f1")
data["Revision"]["Node F1"]       = round_stats(soft_accept_no_fs, "soft_node_f1")
data["Revision + FS"]["Node F1"]  = round_stats(soft_accept_fs,    "soft_node_f1")

# Edge Precision / Recall / F1
data["No Revision"]["Edge Precision"]    = round_stats(soft_no_rev_no_fs, "soft_edge_precision")
data["Revision"]["Edge Precision"]       = round_stats(soft_accept_no_fs, "soft_edge_precision")
data["Revision + FS"]["Edge Precision"]  = round_stats(soft_accept_fs,    "soft_edge_precision")

data["No Revision"]["Edge Recall"]    = round_stats(soft_no_rev_no_fs, "soft_edge_recall")
data["Revision"]["Edge Recall"]       = round_stats(soft_accept_no_fs, "soft_edge_recall")
data["Revision + FS"]["Edge Recall"]  = round_stats(soft_accept_fs,    "soft_edge_recall")

data["No Revision"]["Edge F1"]    = round_stats(soft_no_rev_no_fs, "soft_edge_f1")
data["Revision"]["Edge F1"]       = round_stats(soft_accept_no_fs, "soft_edge_f1")
data["Revision + FS"]["Edge F1"]  = round_stats(soft_accept_fs,    "soft_edge_f1")

# Semantic
data["No Revision"]["Semantic Sim."]    = round_stats(sem_no_fs, "semantic_similarity_generated_vs_updated")
data["Revision"]["Semantic Sim."]       = round_stats(sem_no_fs, "semantic_similarity_accept_all_vs_updated")
data["Revision + FS"]["Semantic Sim."]  = round_stats(sem_fs,    "semantic_similarity_accept_all_vs_updated")


# ── print table ───────────────────────────────────────────────────────────────

rounds = ["round_1", "round_2", "round_3"]

def fmt(mean, std):
    return f"{mean:.3f}±{std:.3f}"

for cond in conditions:
    print(f"\n{'='*70}")
    print(f"  Condition: {cond}")
    print(f"{'='*70}")
    header = f"  {'Metric':<16} {'Round 1':^16} {'Round 2':^16} {'Round 3':^16} {'Mean':^8} {'CR-Std':^8}"
    print(header)
    print(f"  {'-'*76}")
    for m in metrics:
        s = data[cond][m]
        r1 = fmt(s["round_1"]["mean"], s["round_1"]["std"])
        r2 = fmt(s["round_2"]["mean"], s["round_2"]["std"])
        r3 = fmt(s["round_3"]["mean"], s["round_3"]["std"])
        overall = f"{s['overall_mean']:.3f}"
        cr = f"{s['cross_std']:.4f}"
        print(f"  {m:<16} {r1:^16} {r2:^16} {r3:^16} {overall:^8} {cr:^8}")


# ── export CSV (mean±std merged per cell) ─────────────────────────────────────
import csv

def cell(s, round_key):
    return f"{s[round_key]['mean']:.3f}±{s[round_key]['std']:.3f}"

out_dir = Path(r"G:\Other computers\My computer\project C\gen ai\manuscript\llm_manuscript")
out_dir.mkdir(parents=True, exist_ok=True)
out_csv = out_dir / "results_table.csv"

with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["Metric", "Condition", "Round 1", "Round 2", "Round 3", "Mean", "CV (%)"])
    for m in metrics:
        for cond in conditions:
            s = data[cond][m]
            cv = (s["cross_std"] / s["overall_mean"] * 100) if s["overall_mean"] else 0
            w.writerow([
                m, cond,
                cell(s, "round_1"),
                cell(s, "round_2"),
                cell(s, "round_3"),
                f"{s['overall_mean']:.3f}",
                f"{cv:.2f}%",
            ])

print(f"\nCSV saved: {out_csv}")
