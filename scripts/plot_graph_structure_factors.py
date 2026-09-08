"""
Comprehensive panel: effect of expert graph structural properties on WL kernel similarity.
Properties: graph size, edge-to-node ratio, max in-degree, max out-degree.

Expert graph properties are parsed from the fixed round_1 reference graphs.
Revision + FS similarity scores are averaged across five runs per report.

Output: 2x2 panel saved to figures/fig_graph_structure_factors.png
"""
import json
import sys
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
from collections import Counter
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
FINAL_FS_CASE_SCORES = (
    BASE / "evaluation_final" / "few_shot" / "20260828_140052" / "case_scores.csv"
)
REFERENCE_ROOT = BASE / "rounds" / "round_1"
OUT_DIR = PROJECT_ROOT / "figures"
OUT_DIR.mkdir(parents=True, exist_ok=True)
AUDIT_PATH = OUT_DIR / "fig_graph_structure_factors_audit.json"
EXPECTED_REPORTS = 112
EXPECTED_RUNS = 5

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
        "edge_to_node_ratio": m / n            if n > 0 else np.nan,
        "max_in_degree":    max(in_deg.values(),  default=0),
        "max_out_degree":   max(out_deg.values(), default=0),
    }


# ── load similarity CSV ────────────────────────────────────────────────────────
import re as _re

SIM = "structural_similarity_accept_all_vs_updated"

df_sim = pd.read_csv(FINAL_FS_CASE_SCORES)
required_columns = {
    "round",
    "batch_id",
    "case_id",
    "status",
    "structural_similarity_accept_all_vs_updated",
    "graph_edit_similarity_accept_all_vs_updated",
}
missing_columns = sorted(required_columns - set(df_sim.columns))
if missing_columns:
    raise RuntimeError(f"Missing required columns: {missing_columns}")
if len(df_sim) != EXPECTED_REPORTS * EXPECTED_RUNS:
    raise RuntimeError(f"Expected 560 rows, found {len(df_sim)}")
failed_rows = df_sim[df_sim["status"].astype(str).str.lower() != "ok"]
if not failed_rows.empty:
    raise RuntimeError(f"Expected 560 successful rows, found {len(df_sim) - len(failed_rows)}")

df_sim["case_id"] = df_sim["case_id"].astype(str)
# Normalize batch identifiers while preserving the explicit five-run column.
df_sim["batch_prefix"] = df_sim["batch_id"].apply(
    lambda b: _re.sub(r"_output_round_\d+$", "", str(b))
)
SIM2 = "graph_edit_similarity_accept_all_vs_updated"
df_sim = df_sim[["batch_prefix", "case_id", "round", SIM, SIM2]].dropna(
    subset=[SIM, SIM2]
)

# The repeated model runs for a report are not independent observations.
# Exclude few-shot source reports, then average similarity scores across runs so
# that the report, identified by batch_prefix/case_id, is the analysis unit.
excluded_case_keys = load_excluded_case_keys(DEFAULT_EXCLUDED_CASES_PATH)
df_sim["case_key"] = df_sim.apply(
    lambda row: normalize_case_key(f"{row['batch_prefix']}/{row['case_id']}"), axis=1
)
excluded_rows = int(df_sim["case_key"].isin(excluded_case_keys).sum())
df_sim = df_sim[~df_sim["case_key"].isin(excluded_case_keys)].copy()
expected_rounds = {f"round_{index}" for index in range(1, EXPECTED_RUNS + 1)}
observed_rounds = set(df_sim["round"].astype(str))
if observed_rounds != expected_rounds:
    raise RuntimeError(
        f"Expected runs {sorted(expected_rounds)}, found {sorted(observed_rounds)}"
    )
duplicate_count = int(
    df_sim.duplicated(subset=["batch_prefix", "case_id", "round"]).sum()
)
if duplicate_count:
    raise RuntimeError(f"Found {duplicate_count} duplicate report-run rows")
run_counts = df_sim.groupby(["batch_prefix", "case_id"]).size()
if len(run_counts) != EXPECTED_REPORTS or set(run_counts.tolist()) != {EXPECTED_RUNS}:
    raise RuntimeError(
        f"Expected {EXPECTED_REPORTS} reports with five runs each, found "
        f"{len(run_counts)} reports with counts {sorted(set(run_counts.tolist()))}"
    )
df_sim = (
    df_sim.groupby(["batch_prefix", "case_id"], as_index=False)[[SIM, SIM2]]
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

# ── parse fixed expert graphs from round_1 — key: (batch_prefix, case_id) ─────
records = []
for f in sorted(REFERENCE_ROOT.rglob("updated_causal_graph.json")):
    case_id   = f.parent.name
    batch_dir = f.parent.parent.name
    batch_prefix = _re.sub(r"_output_round_\d+$", "", batch_dir)
    try:
        rec = parse_expert_graph(f)
        rec["case_id"]      = str(case_id)
        rec["batch_prefix"] = batch_prefix
        records.append(rec)
    except Exception as e:
        print(f"  Skip {f.relative_to(REFERENCE_ROOT)}: {e}")

df_graph = pd.DataFrame(records).drop_duplicates(subset=["batch_prefix", "case_id"])
df = df_sim.merge(df_graph, on=["batch_prefix", "case_id"], how="inner")
df["graph_size"] = df["n_nodes"] + df["n_edges"]
if len(df) != EXPECTED_REPORTS:
    matched_keys = set(zip(df["batch_prefix"], df["case_id"]))
    expected_keys = set(zip(df_sim["batch_prefix"], df_sim["case_id"]))
    missing_keys = sorted(expected_keys - matched_keys)
    raise RuntimeError(
        f"Expected {EXPECTED_REPORTS} matched reports, found {len(df)}. "
        f"Missing references: {missing_keys}"
    )
print(
    f"Matched {len(df)} independent report observations "
    f"against {len(df_graph)} available expert graphs."
)


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
    ax.text(0.97, 0.12, f"r = {r:.3f}\n{p_str}\nn = {n}",
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
    return {
        "panel": label,
        "structural_factor": xlabel,
        "metric": ylabel,
        "n": int(n),
        "pearson_r": float(r),
        "p_value": float(p),
        "slope": float(slope),
        "intercept": float(intercept),
    }


# ── 2×4 panel (rows: WL kernel, 1-normGED; cols: 4 structural properties) ────
props = [
    ("graph_size",     "Graph size"),
    ("edge_to_node_ratio", "Edge-to-node ratio"),
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
panel_statistics = []

for row, (col, ylabel, labels) in enumerate(metrics):
    for col_i, ((prop, xlabel), lbl) in enumerate(zip(props, labels)):
        panel_statistics.append(scatter_panel(
            axes[row, col_i],
            df[prop], df[col],
            label=lbl,
            show_xlabel=(row == n_rows - 1),
            show_ylabel=(col_i == 0),
            xlabel=xlabel,
            ylabel=ylabel,
        ))

fig.tight_layout(pad=2.0, w_pad=0.25, h_pad=0.5)
fig.savefig(OUT_DIR / "fig_graph_structure_factors.png", dpi=300)
fig.savefig(OUT_DIR / "fig_graph_structure_factors.svg")
print(f"Saved: {OUT_DIR / 'fig_graph_structure_factors.png'}")
plt.close(fig)

AUDIT_PATH.write_text(
    json.dumps(
        {
            "condition": "Revision + FS",
            "case_scores_path": str(FINAL_FS_CASE_SCORES.resolve()),
            "reference_root": str(REFERENCE_ROOT.resolve()),
            "configured_excluded_report_count": len(excluded_case_keys),
            "excluded_rows_present_in_final_input": excluded_rows,
            "report_run_rows": int(run_counts.sum()),
            "independent_reports": int(len(run_counts)),
            "runs": sorted(expected_rounds),
            "runs_per_report": EXPECTED_RUNS,
            "available_reference_graphs": int(len(df_graph)),
            "matched_reference_graphs": int(len(df)),
            "aggregation": "mean across five runs within each report",
            "structural_factors": [name for name, _ in props],
            "metrics": [SIM, SIM2],
            "panel_statistics": panel_statistics,
            "outputs": [
                str((OUT_DIR / "fig_graph_structure_factors.png").resolve()),
                str((OUT_DIR / "fig_graph_structure_factors.svg").resolve()),
            ],
        },
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)
print(f"Audit: {AUDIT_PATH}")
