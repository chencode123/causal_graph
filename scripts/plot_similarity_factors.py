"""
Analyse the effect of the expert graph edge-to-node ratio on structural similarity
(revision + few-shot condition).
Data source: rounds_with_few_shot structural evaluation CSV.

1x2 panel:
  (a) Expert graph edge-to-node ratio vs WLS
  (b) Expert graph edge-to-node ratio vs GES
"""
import json
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import sys
from pathlib import Path
from scipy import stats

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.evaluation_case_filters import (
    DEFAULT_EXCLUDED_CASES_PATH,
    load_excluded_case_keys,
    normalize_case_key,
)

# ── paths ─────────────────────────────────────────────────────────────────────
BASE    = PROJECT_ROOT / "runs" / "stability_test"
FS_DIR  = BASE / "rounds_with_few_shot"
OUT_DIR = PROJECT_ROOT / "figures"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ── style ─────────────────────────────────────────────────────────────────────
plt.rcParams.update({
    "font.family": "serif",
    "font.size": 10,
    "axes.titlesize": 10,
    "axes.titleweight": "bold",
    "axes.labelsize": 10,
    "legend.fontsize": 9,
    "legend.frameon": False,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.dpi": 150,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
})

COLOR     = "#5E81AC"
FIT_COLOR = "#E76F51"


# ── load ──────────────────────────────────────────────────────────────────────
def latest_csv(parent: Path, glob: str) -> Path:
    for d in sorted(parent.glob("2*"), key=lambda p: p.name, reverse=True):
        matches = list(d.glob(glob))
        if matches:
            return matches[0]
    raise FileNotFoundError(f"No CSV matching {glob} under {parent}")


df = pd.read_csv(latest_csv(FS_DIR / "results", "case_scores.csv"))

needed = [
    "structural_similarity_accept_all_vs_updated",
    "graph_edit_similarity_accept_all_vs_updated",
]
df = df.dropna(subset=needed)

# Treat each report as one independent observation. The three model runs for a
# report are averaged after excluding reports used to construct few-shot patterns.
import re as _re

df["case_id"] = df["case_id"].astype(str)
df["batch_prefix"] = df["batch_id"].apply(
    lambda b: _re.sub(r"_output_round_\d+$", "", str(b))
)
excluded_case_keys = load_excluded_case_keys(DEFAULT_EXCLUDED_CASES_PATH)
df["case_key"] = df.apply(
    lambda row: normalize_case_key(f"{row['batch_prefix']}/{row['case_id']}"), axis=1
)
excluded_rows = int(df["case_key"].isin(excluded_case_keys).sum())
df = df[~df["case_key"].isin(excluded_case_keys)].copy()
run_counts = df.groupby(["batch_prefix", "case_id"]).size()
df = (
    df.groupby(["batch_prefix", "case_id"], as_index=False)[needed]
    .mean()
)
print(
    f"Excluded {excluded_rows} report-run observations from "
    f"{len(excluded_case_keys)} few-shot source reports."
)
print(
    f"Aggregated {int(run_counts.sum())} report-run observations into "
    f"{len(run_counts)} independent reports "
    f"({int(run_counts.min())}-{int(run_counts.max())} runs per report)."
)

# Read the fixed expert graph once per report. Recent evaluation CSVs no longer
# duplicate expert node and edge counts on every report-run row.
graph_records = []
for graph_path in sorted((FS_DIR / "round_1").rglob("updated_causal_graph.json")):
    payload = json.loads(graph_path.read_text(encoding="utf-8"))
    nodes = []
    for key in ("hazard_consequence_node", "entity_nodes", "condition_nodes", "event_nodes"):
        value = payload.get(key, [])
        if isinstance(value, list):
            nodes.extend(value)
        elif isinstance(value, dict) and value:
            nodes.append(value)
    node_ids = {
        str(node.get("node_id", "")).strip()
        for node in nodes
        if node.get("node_id")
    }
    edges = [edge for edge in payload.get("edges", []) if isinstance(edge, dict)]
    batch_prefix = _re.sub(
        r"_output_round_\d+$", "", graph_path.parent.parent.name
    )
    graph_records.append(
        {
            "batch_prefix": batch_prefix,
            "case_id": str(graph_path.parent.name),
            "edge_to_node_ratio": (
                len(edges) / len(node_ids) if node_ids else np.nan
            ),
        }
    )

df_graph = pd.DataFrame(graph_records).drop_duplicates(
    subset=["batch_prefix", "case_id"]
)
df = df.merge(df_graph, on=["batch_prefix", "case_id"], how="inner")
print(f"Matched {len(df)} independent reports to expert graph properties.")


# ── plot helper ───────────────────────────────────────────────────────────────
def scatter_panel(ax, x: pd.Series, y: pd.Series, ylabel: str, title: str):
    xv, yv = x.values, y.values
    mask = np.isfinite(xv) & np.isfinite(yv)
    xv, yv = xv[mask], yv[mask]

    ax.scatter(xv, yv, color=COLOR, alpha=0.55, s=18,
               edgecolors="white", linewidth=0.3, zorder=2)

    slope, intercept, r, p, se = stats.linregress(xv, yv)
    xfit = np.linspace(xv.min(), xv.max(), 300)
    yfit = slope * xfit + intercept

    # 95% confidence band
    n = len(xv)
    x_mean = xv.mean()
    t_val  = stats.t.ppf(0.975, df=n - 2)
    se_fit = se * np.sqrt(1/n + (xfit - x_mean)**2 / ((xv - x_mean)**2).sum())
    ax.fill_between(xfit, yfit - t_val * se_fit, yfit + t_val * se_fit,
                    color=FIT_COLOR, alpha=0.15, zorder=1)
    ax.plot(xfit, yfit, color=FIT_COLOR, linewidth=1.6, zorder=3)

    p_str = "p < 0.001" if p < 0.001 else f"p = {p:.3f}"
    ax.text(0.97, 0.97, f"r = {r:.3f}\n{p_str}\nn = {n}",
            transform=ax.transAxes, ha="right", va="top", fontsize=9)

    ax.set_xlabel("Expert graph edge-to-node ratio  (|E| / |V|)")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.set_ylim(0, 1.05)


# ── 1×2 panel ────────────────────────────────────────────────────────────────
fig, axes = plt.subplots(1, 2, figsize=(9, 4))

scatter_panel(
    axes[0],
    df["edge_to_node_ratio"],
    df["structural_similarity_accept_all_vs_updated"],
    ylabel="WLS",
    title="(a) Edge-to-node ratio vs WLS",
)
scatter_panel(
    axes[1],
    df["edge_to_node_ratio"],
    df["graph_edit_similarity_accept_all_vs_updated"],
    ylabel="GES",
    title="(b) Edge-to-node ratio vs GES",
)

fig.tight_layout(pad=2.0)
fig.savefig(OUT_DIR / "fig_edge_to_node_ratio_vs_similarity.png")
fig.savefig(OUT_DIR / "fig_edge_to_node_ratio_vs_similarity.pdf")
print(f"Saved: {OUT_DIR / 'fig_edge_to_node_ratio_vs_similarity.png'}")
plt.close(fig)
