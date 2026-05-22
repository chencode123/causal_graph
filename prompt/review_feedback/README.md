# Review Feedback Few-Shot Library

This directory stores curated few-shot example sets used by the `graph_diagnosis` and `graph_revision_planning` pipeline steps.

## How it is used

In `batch_main_runner.py`, point `FEW_SHOT_PATTERN_FILES_BY_STEP` at one of the JSON files here:

```python
FEW_SHOT_PATTERN_FILES_BY_STEP = {
    "graph_diagnosis": (
        Path(r"prompt\review_feedback\case_coverage_12\review_feedback_analysis_few_shot_balanced_small.json"),
    ),
    "graph_revision_planning": (
        Path(r"prompt\review_feedback\case_coverage_12\review_feedback_analysis_few_shot_balanced_small.json"),
    ),
}
```

At runtime, `step_var_resolver._build_pattern_few_shot_examples()` reads the file and injects the patterns into the `{few_shot_examples}` placeholder in the prompt template.

## JSON structure

Each file contains two parallel arrays:

```json
{
  "planning_patterns": [
    {
      "proposed_change": "...",
      "decision": "accepted | rejected",
      "reviewer_reason": "...",
      "matched_rule": "...",
      "few_shot_takeaway": "..."
    }
  ],
  "diagnosis_patterns": [
    {
      "observed_pattern": "...",
      "decision": "accepted | rejected",
      "diagnosis_interpretation": "...",
      "supporting_rule": "...",
      "few_shot_takeaway": "..."
    }
  ]
}
```

`planning_patterns` → used by `graph_revision_planning`  
`diagnosis_patterns` → used by `graph_diagnosis`

## Files in this directory

| File | Patterns (plan / diag) | Source |
|------|----------------------|--------|
| `review_feedback_analysis_aggregated.json` | 62 / 62 | batches 4, 5, 6 — full unfiltered pool |
| `review_feedback_analysis_few_shot_balanced.json` | balanced subset | selected from aggregated |
| `review_feedback_analysis_few_shot_core.json` | core subset | high-confidence patterns only |
| `review_feedback_analysis_few_shot_curated.json` | curated subset | manually reviewed |
| `case_coverage_12/` | see below | 12-case coverage set |

## `case_coverage_12/`

A curated set built from 12 cases spanning diverse decision patterns (accept-heavy, reject-heavy, mixed). The recommended file for general use is:

```
case_coverage_12/review_feedback_analysis_few_shot_balanced_small.json
```

12 planning + 12 diagnosis patterns, balanced 6 accept / 6 reject each.  
See `case_coverage_12/README.txt` for the per-case pattern breakdown.
