"""
Analyse the effect of expert graph density on structural similarity (Revision + FS condition).
Data source: rounds_with_few_shot structural evaluation CSV.

1x2 panel:
  (a) Expert graph density vs WLS
  (b) Expert graph density vs GES
"""
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
from scipy import stats

# ── paths ─────────────────────────────────────────────────────────────────────
BASE    = Path("g:/Other computers/My computer/project C/gen ai/code/llm/runs/stability_test")
FS_DIR  = BASE / "rounds_with_few_shot"
OUT_DIR = Path("g:/Other computers/My computer/project C/gen ai/code/llm/figures")
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
    "updated_node_count", "updated_edge_count",
]
df = df.dropna(subset=needed)
df = df[(df["updated_node_count"] > 0) & (df["updated_edge_count"] > 0)]

df["expert_density"] = df["updated_edge_count"] / df["updated_node_count"]


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
    ax.text(0.97, 0.97, f"r = {r:.3f}\n{p_str}",
            transform=ax.transAxes, ha="right", va="top", fontsize=9)

    ax.set_xlabel("Expert graph density  (edges / nodes)")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.set_ylim(0, 1.05)


# ── 1×2 panel ────────────────────────────────────────────────────────────────
fig, axes = plt.subplots(1, 2, figsize=(9, 4))

scatter_panel(
    axes[0],
    df["expert_density"],
    df["structural_similarity_accept_all_vs_updated"],
    ylabel="WLS",
    title="(a) Expert graph density vs WLS",
)
scatter_panel(
    axes[1],
    df["expert_density"],
    df["graph_edit_similarity_accept_all_vs_updated"],
    ylabel="GES",
    title="(b) Expert graph density vs GES",
)

fig.tight_layout(pad=2.0)
fig.savefig(OUT_DIR / "fig_density_vs_similarity.png")
fig.savefig(OUT_DIR / "fig_density_vs_similarity.pdf")
print(f"Saved: {OUT_DIR / 'fig_density_vs_similarity.png'}")
plt.close(fig)
