"""
Plot issue type frequency comparison: No-FS vs With-FS.

Usage:
    python scripts/plot_issue_type_comparison.py
"""
import json
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from pathlib import Path
from collections import Counter

BASE   = Path("g:/Other computers/My computer/project C/gen ai/code/llm/runs/stability_test")
FS_DIR = BASE / "rounds_with_few_shot"
NO_DIR = BASE / "rounds"
OUT    = Path("g:/Other computers/My computer/project C/gen ai/code/llm/figures/issue_type_comparison.png")

plt.rcParams.update({
    "font.family": "serif",
    "font.size": 10,
    "axes.labelsize": 10,
    "axes.titlesize": 11,
    "axes.titleweight": "bold",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.dpi": 150,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
})

COLOR_NO = "#5E81AC"   # blue  — No few-shot
COLOR_FS = "#E76F51"   # coral — With few-shot


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def collect(run_dir):
    types = []
    n_cases = 0
    for f in sorted(Path(run_dir).glob("*/batch_*/*/graph_diagnosis_output.json")):
        issues = load_json(f).get("issues_summary", [])
        for iss in issues:
            types.append(iss.get("issue_type", "unknown"))
        n_cases += 1
    return Counter(types), n_cases


no_counter, no_n = collect(NO_DIR)
fs_counter, fs_n = collect(FS_DIR)

all_types = sorted(set(no_counter) | set(fs_counter))

no_means = [no_counter[t] / no_n for t in all_types]
fs_means = [fs_counter[t] / fs_n for t in all_types]

# Sort by No-FS frequency descending
order = sorted(range(len(all_types)), key=lambda i: no_means[i], reverse=True)
all_types = [all_types[i] for i in order]
no_means  = [no_means[i]  for i in order]
fs_means  = [fs_means[i]  for i in order]

# Readable labels
label_map = {
    "missing_local_link": "missing_local_link",
    "redundant_node":     "redundant_node",
    "missing_node":       "missing_node",
    "unsupported_edge":   "unsupported_edge",
    "overmerged_node":    "overmerged_node",
    "schema_mismatch":    "schema_mismatch",
    "shortcut_edge":      "shortcut_edge",
    "wrong_node_type":    "wrong_node_type",
    "wrong_relation":     "wrong_relation",
}
labels = [label_map.get(t, t) for t in all_types]

x     = np.arange(len(all_types))
width = 0.35

fig, ax = plt.subplots(figsize=(9, 4.5))

bars_no = ax.bar(x - width/2, no_means, width, label="No few-shot",  color=COLOR_NO, alpha=0.88)
bars_fs = ax.bar(x + width/2, fs_means, width, label="With few-shot", color=COLOR_FS, alpha=0.88)

# Diff annotation above each pair
for i in range(len(all_types)):
    diff = fs_means[i] - no_means[i]
    top  = max(no_means[i], fs_means[i])
    color = COLOR_FS if diff < 0 else "#888"
    ax.text(x[i], top + 0.008, f"{diff:+.3f}", ha="center", va="bottom",
            fontsize=7.5, color=color)

ax.set_xticks(x)
ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=9)
ax.set_ylabel("Mean count per case")
ax.set_title("Issue type frequency: No few-shot vs With few-shot")
ax.set_ylim(0, max(max(no_means), max(fs_means)) * 1.22)
ax.legend(frameon=False)
ax.grid(axis="y", alpha=0.2, linestyle="--")

OUT.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(OUT)
print(f"Saved: {OUT}")
