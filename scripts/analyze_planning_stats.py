"""
Analyze graph_revision_planning_output.json across all cases in a run directory.

Usage:
    python scripts/analyze_planning_stats.py runs/stability_test/rounds
    python scripts/analyze_planning_stats.py runs/stability_test/rounds_with_few_shot
    python scripts/analyze_planning_stats.py runs/stability_test/rounds --compare runs/stability_test/rounds_with_few_shot
"""
import json
import argparse
from pathlib import Path
from collections import defaultdict, Counter
import statistics


# ── helpers ───────────────────────────────────────────────────────────────────

def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def iter_cases(run_dir):
    """Yield (round_name, batch_stem, case_id, case_dir) for every case."""
    run_dir = Path(run_dir)
    for planning_file in sorted(run_dir.glob("*/batch_*/*/graph_revision_planning_output.json")):
        case_dir   = planning_file.parent
        batch_dir  = case_dir.parent
        round_dir  = batch_dir.parent
        batch_stem = "_".join(batch_dir.name.split("_")[:2])
        yield round_dir.name, batch_stem, case_dir.name, case_dir


def parse_planning(case_dir):
    """Return a dict of stats for one case."""
    plan_path  = case_dir / "graph_revision_planning_output.json"
    state_path = case_dir / "updated_causal_graph_review_state.json"

    plan  = load_json(plan_path)
    state = load_json(state_path) if state_path.exists() else {}

    # ── revision counts ──────────────────────────────────────────────────────
    cats = {
        "node_updates":    "node_update",
        "node_additions":  "node_addition",
        "node_deletions":  "node_deletion",
        "edge_additions":  "edge_addition",
        "edge_deletions":  "edge_deletion",
        "edge_updates":    "edge_update",
    }
    rev_counts = {k: len(plan.get(v, [])) for v, k in [
        ("node_updates",   "node_update"),
        ("node_additions", "node_addition"),
        ("node_deletions", "node_deletion"),
        ("edge_additions", "edge_addition"),
        ("edge_deletions", "edge_deletion"),
        ("edge_updates",   "edge_update"),
    ]}
    total_revisions = sum(rev_counts.values())

    # ── issue types ──────────────────────────────────────────────────────────
    issues = plan.get("issues_summary", [])
    issue_types = [i.get("issue_type", "unknown") for i in issues]
    severities  = [i.get("severity",   "unknown") for i in issues]

    # ── overall quality ──────────────────────────────────────────────────────
    quality = plan.get("case_assessment", {}).get("overall_quality", "unknown")

    # ── acceptance decisions ─────────────────────────────────────────────────
    decisions = state.get("review_decisions", {})
    if isinstance(decisions, list):
        decisions = {item[0]: item[1] for item in decisions}

    accepted = rejected = 0
    for rev_key, dec in decisions.items():
        status = dec.get("status") if isinstance(dec, dict) else dec
        if status == "accepted":
            accepted += 1
        elif status == "rejected":
            rejected += 1

    return {
        "total_revisions": total_revisions,
        "rev_counts":      rev_counts,
        "issue_types":     issue_types,
        "severities":      severities,
        "quality":         quality,
        "accepted":        accepted,
        "rejected":        rejected,
        "total_decisions": accepted + rejected,
    }


# ── aggregation ───────────────────────────────────────────────────────────────

def aggregate(run_dir):
    """Collect stats across all cases in run_dir."""
    rows = []
    for round_name, batch_stem, case_id, case_dir in iter_cases(run_dir):
        try:
            s = parse_planning(case_dir)
        except Exception as e:
            print(f"  SKIP {case_dir}: {e}")
            continue
        s["round"] = round_name
        s["batch"] = batch_stem
        s["case"]  = case_id
        rows.append(s)
    return rows


def summarize(rows, label="Run"):
    print(f"\n{'='*60}")
    print(f"  {label}  ({len(rows)} cases)")
    print(f"{'='*60}")

    # ── revision volume ──────────────────────────────────────────────────────
    totals = [r["total_revisions"] for r in rows]
    print(f"\n[Revisions per case]")
    print(f"  Mean   : {statistics.mean(totals):.2f}")
    print(f"  Median : {statistics.median(totals):.1f}")
    print(f"  Stdev  : {statistics.stdev(totals):.2f}" if len(totals) > 1 else "")
    print(f"  Zero   : {sum(1 for t in totals if t == 0)} cases ({100*sum(1 for t in totals if t==0)/len(totals):.1f}%)")

    # ── revision breakdown ───────────────────────────────────────────────────
    keys = ["node_addition","node_deletion","node_update",
            "edge_addition","edge_deletion","edge_update"]
    print(f"\n[Revision type breakdown (mean per case)]")
    for k in keys:
        vals = [r["rev_counts"][k] for r in rows]
        print(f"  {k:<20}: {statistics.mean(vals):.3f}  (total {sum(vals)})")

    # ── issue types ──────────────────────────────────────────────────────────
    all_issues = [t for r in rows for t in r["issue_types"]]
    print(f"\n[Issue types]  total={len(all_issues)}, mean={len(all_issues)/len(rows):.2f}/case")
    for t, n in Counter(all_issues).most_common():
        print(f"  {t:<30}: {n:>4}  ({100*n/len(all_issues):.1f}%)")

    # ── severity ─────────────────────────────────────────────────────────────
    all_sev = [s for r in rows for s in r["severities"]]
    print(f"\n[Severity]")
    for s, n in Counter(all_sev).most_common():
        print(f"  {s:<15}: {n:>4}  ({100*n/len(all_sev):.1f}%)" if all_sev else "")

    # ── overall quality ──────────────────────────────────────────────────────
    print(f"\n[Overall quality]")
    for q, n in Counter(r["quality"] for r in rows).most_common():
        print(f"  {q:<20}: {n:>4}  ({100*n/len(rows):.1f}%)")

    # ── accept / reject ──────────────────────────────────────────────────────
    total_acc = sum(r["accepted"] for r in rows)
    total_rej = sum(r["rejected"] for r in rows)
    total_dec = total_acc + total_rej
    if total_dec > 0:
        print(f"\n[Human review decisions]  total={total_dec}")
        print(f"  accepted : {total_acc} ({100*total_acc/total_dec:.1f}%)")
        print(f"  rejected : {total_rej} ({100*total_rej/total_dec:.1f}%)")
        cases_with_rej = sum(1 for r in rows if r["rejected"] > 0)
        print(f"  cases with >=1 rejection: {cases_with_rej} ({100*cases_with_rej/len(rows):.1f}%)")
    else:
        print(f"\n[Human review decisions]  (no review state files found)")

    # ── by round ─────────────────────────────────────────────────────────────
    by_round = defaultdict(list)
    for r in rows:
        by_round[r["round"]].append(r)
    if len(by_round) > 1:
        print(f"\n[By round — mean revisions per case]")
        for rnd in sorted(by_round):
            rv = [r["total_revisions"] for r in by_round[rnd]]
            print(f"  {rnd:<12}: {statistics.mean(rv):.2f}  (n={len(rv)})")


def compare(rows_a, label_a, rows_b, label_b):
    """Side-by-side comparison of two runs."""
    print(f"\n{'='*60}")
    print(f"  COMPARISON: {label_a}  vs  {label_b}")
    print(f"{'='*60}")

    def mean_by_key(rows, key, sub=None):
        vals = [r[key][sub] if sub else r[key] for r in rows]
        return statistics.mean(vals), sum(vals)

    print(f"\n{'Metric':<35} {label_a:>18} {label_b:>18}")
    print("-" * 73)

    # revision counts
    for k in ["total_revisions"]:
        ma, _ = mean_by_key(rows_a, k)
        mb, _ = mean_by_key(rows_b, k)
        print(f"  {'mean revisions/case':<33} {ma:>18.3f} {mb:>18.3f}")

    for k in ["node_addition","node_deletion","edge_addition","edge_deletion"]:
        ma, ta = mean_by_key(rows_a, "rev_counts", k)
        mb, tb = mean_by_key(rows_b, "rev_counts", k)
        print(f"  {k:<33} {ma:>18.3f} {mb:>18.3f}")

    # issue type rates
    all_a = [t for r in rows_a for t in r["issue_types"]]
    all_b = [t for r in rows_b for t in r["issue_types"]]
    all_types = sorted(set(all_a) | set(all_b))
    print(f"\n{'Issue type':<35} {label_a:>18} {label_b:>18}")
    print("-" * 73)
    ca, cb = Counter(all_a), Counter(all_b)
    for t in all_types:
        ra = ca[t] / len(rows_a) if rows_a else 0
        rb = cb[t] / len(rows_b) if rows_b else 0
        print(f"  {t:<33} {ra:>18.3f} {rb:>18.3f}")

    # accept/reject
    ta_acc = sum(r["accepted"] for r in rows_a)
    ta_rej = sum(r["rejected"] for r in rows_a)
    tb_acc = sum(r["accepted"] for r in rows_b)
    tb_rej = sum(r["rejected"] for r in rows_b)
    if ta_acc + ta_rej > 0 and tb_acc + tb_rej > 0:
        print(f"\n{'Decision':<35} {label_a:>18} {label_b:>18}")
        print("-" * 73)
        print(f"  {'accept rate':<33} {ta_acc/(ta_acc+ta_rej):>18.3f} {tb_acc/(tb_acc+tb_rej):>18.3f}")
        print(f"  {'reject rate':<33} {ta_rej/(ta_acc+ta_rej):>18.3f} {tb_rej/(tb_acc+tb_rej):>18.3f}")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Summarize graph_revision_planning results.")
    parser.add_argument("run_dir", help="Base run directory (e.g. runs/stability_test/rounds)")
    parser.add_argument("--compare", metavar="RUN_DIR_B",
                        help="Second run directory to compare against")
    parser.add_argument("--round", metavar="ROUND_NAME",
                        help="Filter to a single round (e.g. round_1)")
    args = parser.parse_args()

    rows_a = aggregate(args.run_dir)
    if args.round:
        rows_a = [r for r in rows_a if r["round"] == args.round]

    summarize(rows_a, label=Path(args.run_dir).name)

    if args.compare:
        rows_b = aggregate(args.compare)
        if args.round:
            rows_b = [r for r in rows_b if r["round"] == args.round]
        summarize(rows_b, label=Path(args.compare).name)
        compare(rows_a, Path(args.run_dir).name, rows_b, Path(args.compare).name)


if __name__ == "__main__":
    main()
