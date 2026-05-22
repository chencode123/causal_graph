"""
Comprehensive panel: effect of expert graph structural properties on WL kernel similarity.
Properties: standard density, average degree, max in-degree, max out-degree.

Expert graph properties are parsed from updated_causal_graph.json (round_1 only,
since the expert graph is identical across rounds).
Similarity scores are averaged across all three rounds per case.

Output: 2x2 panel saved to figures/fig_graph_structure_factors.png
"""
import json
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
from collections import Counter
from scipy import stats

# ── paths ─────────────────────────────────────────────────────────────────────
BASE    = Path("g:/Other computers/My computer/project C/gen ai/code/llm/runs/stability_test")
FS_DIR  = BASE / "rounds_with_few_shot"
OUT_DIR = Path("g:/Other computers/My computer/project C/gen ai/code/llm/figures")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ── style ─────────────────────────────────────────────────────────────────────
plt.rcParams.update({
    "font.family": "serif",
    "font.size": 30,
    "axes.titlesize": 30,
    "axes.titleweight": "bold",
    "axes.labelsize": 30,
    "xtick.labelsize": 26,
    "ytick.labelsize": 26,
    "legend.frameon": False,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.dpi": 150,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
})

COLOR     = "#5E81AC"
FIT_COLOR = "#E76F51"


# ── helpers ───────────────────────────────────────────────────────────────────
def latest_csv(parent: Path, glob: str) -> Path:
    for d in sorted(parent.glob("2*"), key=lambda p: p.name, reverse=True):
        matches = list(d.glob(glob))
        if matches:
            return matches[0]
    raise FileNotFoundError(f"No CSV matching {glob} under {parent}")


def parse_expert_graph(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))

    nodes = []
    for key in ("hazard_consequence_node", "entity_nodes", "condition_nodes", "event_nodes"):
        val = data.get(key, [])
        if isinstance(val, list):
            nodes.extend(val)
        elif isinstance(val, dict) and val:
            nodes.append(val)

    node_ids = {str(n.get("node_id", "")).strip() for n in nodes if n.get("node_id")}
    edges    = [e for e in data.get("edges", []) if isinstance(e, dict)]

    n = len(node_ids)
    m = len(edges)

    in_deg  = Counter(str(e.get("target", "")).strip() for e in edges)
    out_deg = Counter(str(e.get("source", "")).strip() for e in edges)

    return {
        "n_nodes":          n,
        "n_edges":          m,
        "standard_density": m / (n * (n - 1)) if n > 1 else np.nan,
        "avg_degree":       m / n              if n > 0 else np.nan,
        "max_in_degree":    max(in_deg.values(),  default=0),
        "max_out_degree":   max(out_deg.values(), default=0),
    }


# ── load similarity CSV ────────────────────────────────────────────────────────
import re as _re

SIM = "structural_similarity_accept_all_vs_updated"

df_sim = pd.read_csv(latest_csv(FS_DIR / "results", "case_scores.csv"))
df_sim["case_id"] = df_sim["case_id"].astype(str)
# extract batch prefix (e.g. "batch_10") and round from batch_id
df_sim["batch_prefix"] = df_sim["batch_id"].apply(
    lambda b: _re.sub(r"_output_round_\d+$", "", str(b))
)
df_sim["round"] = df_sim["batch_id"].apply(
    lambda b: m.group(1) if (m := _re.search(r"(round_\d+)", str(b))) else None
)
SIM2 = "graph_edit_similarity_accept_all_vs_updated"
df_sim = df_sim[["batch_prefix", "case_id", "round", SIM, SIM2]].dropna(subset=[SIM])

# ── parse expert graphs from round_1 — key: (batch_prefix, case_id) ──────────
records = []
for f in sorted((FS_DIR / "round_1").rglob("updated_causal_graph.json")):
    case_id   = f.parent.name
    batch_dir = f.parent.parent.name                        # e.g. batch_10_output_round_1
    batch_prefix = _re.sub(r"_output_round_\d+$", "", batch_dir)
    try:
        rec = parse_expert_graph(f)
        rec["case_id"]      = str(case_id)
        rec["batch_prefix"] = batch_prefix
        records.append(rec)
    except Exception as e:
        print(f"  Skip {f.relative_to(FS_DIR)}: {e}")

df_graph = pd.DataFrame(records).drop_duplicates(subset=["batch_prefix", "case_id"])
df = df_sim.merge(df_graph, on=["batch_prefix", "case_id"], how="inner")
df["graph_size"] = df["n_nodes"] + df["n_edges"]
print(f"Matched {len(df)} observations ({len(df_graph)} cases × up to 3 rounds).")


# ── plot helper ───────────────────────────────────────────────────────────────
def scatter_panel(ax, x: pd.Series, y: pd.Series, label: str,
                  show_xlabel: bool, show_ylabel: bool,
                  xlabel: str, ylabel: str):
    xv = x.values.astype(float)
    yv = y.values.astype(float)
    mask = np.isfinite(xv) & np.isfinite(yv)
    xv, yv = xv[mask], yv[mask]

    ax.scatter(xv, yv, color=COLOR, alpha=0.55, s=50,
               edgecolors="white", linewidth=0.5, zorder=2)

    slope, intercept, r, p, se = stats.linregress(xv, yv)
    xfit = np.linspace(xv.min(), xv.max(), 300)
    yfit = slope * xfit + intercept

    n      = len(xv)
    t_val  = stats.t.ppf(0.975, df=n - 2)
    se_fit = se * np.sqrt(1/n + (xfit - xv.mean())**2 / ((xv - xv.mean())**2).sum())
    ax.fill_between(xfit, yfit - t_val * se_fit, yfit + t_val * se_fit,
                    color=FIT_COLOR, alpha=0.15, zorder=1)
    ax.plot(xfit, yfit, color=FIT_COLOR, linewidth=3.0, zorder=3)

    p_str = "p < 0.001" if p < 0.001 else f"p = {p:.3f}"
    ax.text(0.97, 0.12, f"r = {r:.3f}\n{p_str}",
            transform=ax.transAxes, ha="right", va="bottom", fontsize=26)

    ax.set_xlabel(xlabel if show_xlabel else "")
    ax.set_ylabel(ylabel if show_ylabel else "")
    if not show_xlabel:
        ax.tick_params(labelbottom=False)
    if not show_ylabel:
        ax.tick_params(labelleft=False)
    ax.set_ylim(0.0, 1.05)

    ax.text(0.0, 1.01, f"({label})",
            transform=ax.transAxes, ha="left", va="bottom",
            fontsize=30, fontweight="bold")


# ── 2×4 panel (rows: WL kernel, 1-normGED; cols: 4 structural properties) ────
props = [
    ("graph_size",     "Graph size"),
    ("avg_degree",     "Average degree"),
    ("max_in_degree",  "Max in-degree"),
    ("max_out_degree", "Max out-degree"),
]
metrics = [
    (SIM,  "WLS",  ("a","b","c","d")),
    (SIM2, "GES",  ("e","f","g","h")),
]

n_rows = len(metrics)
n_cols = len(props)
fig, axes = plt.subplots(n_rows, n_cols, figsize=(24, 11))

for row, (col, ylabel, labels) in enumerate(metrics):
    for col_i, ((prop, xlabel), lbl) in enumerate(zip(props, labels)):
        scatter_panel(
            axes[row, col_i],
            df[prop], df[col],
            label=lbl,
            show_xlabel=(row == n_rows - 1),
            show_ylabel=(col_i == 0),
            xlabel=xlabel,
            ylabel=ylabel,
        )

fig.tight_layout(pad=2.0, w_pad=0.25, h_pad=0.5)
fig.savefig(OUT_DIR / "fig_graph_structure_factors.png", dpi=300)
fig.savefig(OUT_DIR / "fig_graph_structure_factors.svg")
print(f"Saved: {OUT_DIR / 'fig_graph_structure_factors.png'}")
plt.close(fig)
