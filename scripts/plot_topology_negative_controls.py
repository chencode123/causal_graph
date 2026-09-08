from __future__ import annotations

"""Plot topology-destructive negative-control dose-response curves."""

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_ROOT = PROJECT_ROOT / "runs/stability_test/topology_negative_controls"
DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT
    / "runs/stability_test/figures_comparing_rounds/topology_negative_controls"
)
SUMMARY_FILENAME = "overall_summary.csv"
SOURCE_AUDIT_FILENAME = "topology_negative_control_audit.json"
EXPECTED_CASES = 112
EXPECTED_REPLICATES = 100
EXPECTED_SEVERITIES = (0.25, 0.50, 0.75)

CONTROL_SPECS = (
    ("node_deletion", "Node deletion", "#BEBEBE", "o", "-"),
    ("edge_deletion", "Edge deletion", "#8F8F8F", "s", "--"),
    ("edge_direction_reversal", "Direction reversal", "#86A3C5", "^", "-."),
    ("edge_endpoint_rewiring", "Endpoint rewiring", "#5E81AC", "D", ":"),
    ("combined", "Combined", "#2E4A6E", "X", "-"),
)

METRIC_SPECS = (
    ("mean_wl_similarity", "(a) WL Similarity"),
    ("mean_graph_edit_similarity", "(b) Graph Edit Similarity"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_ROOT,
        help="A result directory or a root containing timestamped result directories.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="Development only. Plot incomplete smoke-test data instead of requiring 112 cases.",
    )
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def find_result_dir(input_path: Path) -> Path:
    resolved = input_path.resolve()
    if (resolved / SUMMARY_FILENAME).exists():
        return resolved
    candidates = [path.parent for path in resolved.rglob(SUMMARY_FILENAME)]
    if not candidates:
        raise FileNotFoundError(f"Cannot find {SUMMARY_FILENAME} under {resolved}")
    return max(candidates, key=lambda path: (path / SUMMARY_FILENAME).stat().st_mtime)


def audit_input(
    result_dir: Path,
    rows: list[dict[str, str]],
    *,
    allow_incomplete: bool,
) -> dict[str, Any]:
    source_audit_path = result_dir / SOURCE_AUDIT_FILENAME
    source_audit = (
        json.loads(source_audit_path.read_text(encoding="utf-8"))
        if source_audit_path.exists()
        else {}
    )
    expected_controls = {item[0] for item in CONTROL_SPECS}
    controls = {row["control"] for row in rows}
    severities = sorted({float(row["severity"]) for row in rows})
    metrics = {row["metric"] for row in rows}
    expected_metrics = {item[0] for item in METRIC_SPECS}
    report_counts = {int(float(row["report_count"])) for row in rows}
    problems: list[str] = []

    if controls != expected_controls:
        problems.append(
            f"expected controls {sorted(expected_controls)}, found {sorted(controls)}"
        )
    if not np.allclose(severities, EXPECTED_SEVERITIES, rtol=0.0, atol=1e-12):
        problems.append(
            f"expected severities {list(EXPECTED_SEVERITIES)}, found {severities}"
        )
    if metrics != expected_metrics:
        problems.append(
            f"expected metrics {sorted(expected_metrics)}, found {sorted(metrics)}"
        )
    if report_counts != {EXPECTED_CASES}:
        problems.append(
            f"expected {EXPECTED_CASES} cases in every summary row, found {sorted(report_counts)}"
        )
    retained = source_audit.get("retained_report_count")
    if retained != EXPECTED_CASES:
        problems.append(f"source audit retained-case count is {retained}, expected {EXPECTED_CASES}")
    replicates = source_audit.get("replicates")
    if replicates != EXPECTED_REPLICATES:
        problems.append(
            f"source audit replicate count is {replicates}, expected {EXPECTED_REPLICATES}"
        )
    expected_rows = len(CONTROL_SPECS) * len(EXPECTED_SEVERITIES) * len(METRIC_SPECS)
    if len(rows) != expected_rows:
        problems.append(f"expected {expected_rows} summary rows, found {len(rows)}")
    if problems and not allow_incomplete:
        raise RuntimeError("Topology-control input audit failed. " + "; ".join(problems))

    return {
        "result_dir": str(result_dir),
        "summary_path": str((result_dir / SUMMARY_FILENAME).resolve()),
        "source_audit_path": str(source_audit_path.resolve()),
        "summary_rows": len(rows),
        "controls": sorted(controls),
        "severities": severities,
        "metrics": sorted(metrics),
        "report_counts": sorted(report_counts),
        "replicates": replicates,
        "allow_incomplete": allow_incomplete,
        "complete": not problems,
        "problems": problems,
    }


def select_curve(
    rows: list[dict[str, str]], control: str, metric: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    selected = sorted(
        (
            row
            for row in rows
            if row["control"] == control and row["metric"] == metric
        ),
        key=lambda row: float(row["severity"]),
    )
    severity = np.array([0.0] + [float(row["severity"]) for row in selected])
    means = np.array([1.0] + [float(row["mean_score"]) for row in selected])
    lows = np.array([1.0] + [float(row["score_ci95_low"]) for row in selected])
    highs = np.array([1.0] + [float(row["score_ci95_high"]) for row in selected])
    return severity, means, lows, highs


def configure_style() -> None:
    plt.style.use("default")
    plt.rcParams.update(
        {
            "figure.dpi": 150,
            "savefig.dpi": 300,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.facecolor": "white",
            "savefig.bbox": "tight",
            "font.family": "serif",
            "font.serif": ["Times New Roman", "DejaVu Serif"],
            "font.size": 12,
            "axes.labelsize": 12,
            "axes.titlesize": 12,
            "xtick.labelsize": 11,
            "ytick.labelsize": 11,
            "legend.fontsize": 10,
        }
    )


def plot(result_dir: Path, output_dir: Path, *, allow_incomplete: bool) -> Path:
    rows = read_csv(result_dir / SUMMARY_FILENAME)
    input_audit = audit_input(result_dir, rows, allow_incomplete=allow_incomplete)
    configure_style()

    fig, axes = plt.subplots(1, 2, figsize=(12.2, 4.7), sharey=True)
    for ax, (metric, title) in zip(axes, METRIC_SPECS):
        ax.grid(axis="y", color="#E6E6E6", linewidth=0.8, zorder=0)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_linewidth(0.8)
        ax.spines["bottom"].set_linewidth(0.8)
        ax.tick_params(length=4, width=0.8)

        for control, label, color, marker, linestyle in CONTROL_SPECS:
            x, center, low, high = select_curve(rows, control, metric)
            if len(x) == 1:
                continue
            ax.fill_between(x * 100.0, low, high, color=color, alpha=0.13, linewidth=0)
            ax.plot(
                x * 100.0,
                center,
                color=color,
                linestyle=linestyle,
                linewidth=1.9,
                marker=marker,
                markersize=6,
                markerfacecolor="white",
                markeredgecolor=color,
                markeredgewidth=1.2,
                label=label,
                zorder=3,
            )

        available_severities = sorted({0.0} | {float(row["severity"]) for row in rows})
        ax.set_xticks([value * 100.0 for value in available_severities])
        ax.set_xticklabels([f"{value:.0%}" for value in available_severities])
        ax.set_xlim(-2.5, max(available_severities) * 100.0 + 2.5)
        ax.set_ylim(0.0, 1.04)
        ax.set_xlabel("Topology perturbation level")
        ax.set_title(title, loc="left", fontweight="bold")

    axes[0].set_ylabel("Similarity score")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.subplots_adjust(bottom=0.25, wspace=0.14)
    fig.legend(
        handles,
        labels,
        loc="lower center",
        ncol=5,
        frameon=False,
        bbox_to_anchor=(0.5, 0.02),
        handlelength=2.6,
        columnspacing=1.3,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    base = output_dir / "topology_negative_control_dose_response"
    for suffix in (".pdf", ".png", ".svg"):
        fig.savefig(base.with_suffix(suffix))
    plt.close(fig)

    plot_audit = {
        "figure": str(base.resolve()),
        "input": input_audit,
        "x_axis": "configured topology perturbation severity",
        "aggregation": (
            "Replicates are averaged within each incident case. Curves and 95% confidence "
            "intervals are then calculated across case-level means."
        ),
        "positive_control": "unperturbed reference graph at severity 0 and similarity 1",
        "outputs": [str(base.with_suffix(suffix).resolve()) for suffix in (".pdf", ".png", ".svg")],
    }
    audit_path = output_dir / "topology_negative_control_plot_audit.json"
    audit_path.write_text(json.dumps(plot_audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved: {base.with_suffix('.pdf')}")
    print(f"Saved: {base.with_suffix('.png')}")
    print(f"Saved: {base.with_suffix('.svg')}")
    print(f"Audit: {audit_path}")
    return base.with_suffix(".png")


def main() -> None:
    args = parse_args()
    result_dir = find_result_dir(args.input)
    plot(result_dir, args.output_dir.resolve(), allow_incomplete=args.allow_incomplete)


if __name__ == "__main__":
    main()
