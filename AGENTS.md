# Project Work Log and Agent Instructions

## Current objective

Implement and validate a strong schema-constrained single-pass LLM baseline for the
process-safety causal-relation graph pipeline. The baseline must receive the same report,
hazard vocabulary, accident-scenario schema, schema definitions, and causal-edge definitions
as the frozen main method, while producing the final graph in exactly one model call per
report.

The baseline is an ablation of pipeline decomposition. It must not use candidate extraction,
causal-narrative outputs, validation feedback, graph diagnosis, revision planning, expert
revisions, reference graphs, or few-shot feedback patterns.

## Frozen main-method constraint

The main-method results are finalized. Do not modify its prompts or require those results to
be regenerated. In particular, keep these files at their original committed content:

- `prompt/identify_hazard_consequence.txt`
- `prompt/identify_accident_scenario.txt`
- `prompt/graph_diagnosis.txt`

The baseline-specific registry and runtime additions are conditional and must not alter the
main method when `structured_output_schemas` is unset.

## Baseline implementation

- Runner: `baseline_single_pass_runner.py`
- Prompt: `prompt/direct_graph_extraction.txt`
- Prompt registration: `prompt/manifest.json`
- Step registration: `pipeline/step_registry.py`, key `direct_graph_extraction`
- Output JSON Schema: `scheme/baseline_causal_graph_output_schema.json`
- Baseline rule snapshots:
  - `scheme/baseline_hazard_selection_rules.txt`
  - `scheme/baseline_final_node_rules.txt`
  - `scheme/baseline_graph_connectivity_rules.txt`

The baseline output file is `causal_graph.json`. A baseline-specific deterministic
postprocessor renders `causal_graph.html` without invoking the main method's multi-stage graph
rebuilding logic.

## Structured output

`direct_graph_extraction` uses the Responses API structured-output configuration:

```json
{
  "type": "json_schema",
  "name": "direct_graph_extraction_output",
  "strict": true,
  "schema": "scheme/baseline_causal_graph_output_schema.json"
}
```

The schema requires exactly one `H1`, restricts node labels/types and controlled values,
requires exact node/edge fields, prohibits additional properties, restricts ID formats, and
allows only `has` and `enables` relations. Both direct Responses mode and Batch mode support
the per-step schema through `PipelineConfig.structured_output_schemas`.

JSON Schema does not enforce cross-object referential integrity, graph connectivity,
acyclicity, or evidence truth. Keep the local audit checks for these properties.

## Audit behavior

Each run writes `single_pass_audit.json`. The audit checks:

- required top-level fields;
- exactly one HazardConsequence node with ID `H1`;
- unique and non-empty node IDs;
- allowed relations and endpoint-type combinations;
- existing edge endpoints;
- duplicate JSON keys, duplicate edges, and self-loops;
- incoming/outgoing connectivity expectations;
- Condition-node incoming and outgoing edges;
- cycle presence and cycle rate;
- JSON and HTML availability.

Cycles are measured but are not automatically deleted. The frozen main method did not apply
explicit acyclicity enforcement, so the baseline must not receive an extra DAG-enforcement
advantage. Report cycle rate for both methods during evaluation.

Each new run copies the exact structured schema to
`run_XX/structured_output_schema.json`; the audit records its SHA-256 hash.

## Current baseline configuration

At the time this file was updated, `baseline_single_pass_runner.py` is configured as follows:

```python
SOURCE_DIR = PROJECT_ROOT / "runs" / "stability_test" / "batched_reports" / "batch_1"
OUTPUT_ROOT = PROJECT_ROOT / "runs" / "single_pass_baseline"
EXECUTION_MODE = "responses"
RESPONSES_ASYNC_ENABLED = False
TARGET_CASES = None
INDEPENDENT_RUNS = 1
START_RUN = 3
RESUME = False
OVERWRITE_EXISTING_RUN = False
MODEL_NAME = "gpt-5.4-2026-03-05"
REASONING_EFFORT = "medium"
VERBOSITY = "medium"
ACTIVE_STEP_KEYS = ("direct_graph_extraction",)
```

This configuration processes all 11 case folders in `batch_1`. It is still a development
run, not the final held-out evaluation configuration.

`OVERWRITE_EXISTING_RUN=False` preserves completed runs. If overwrite is enabled later, it
recursively removes only the selected `run_XX` directory before recreating it. Close open HTML
files, Explorer previews, and sync-client handles before any intentional overwrite.

## Known prior result issue

The existing pre-structured-output `run_01` result is invalid and must not be used in the
paper. The model emitted duplicate `source` keys in three edge objects: the endpoint source
was followed by a node-style provenance value `incident_description`. Standard JSON parsing
kept the latter value, producing invalid endpoints. This motivated strict JSON Schema output.

Any `run_01` or `run_02` result generated before the current prompt/schema version must not
be pooled with final results. Use the audited `run_03` outputs for current development work.

## Validation already completed

- Python compilation passes for the runner and modified pipeline modules.
- Prompt manifest and step registry validation return no errors.
- The direct prompt renders successfully for `batch_1/1`.
- The JSON Schema passes Draft 2020-12 schema validation.
- The Responses request payload contains `type=json_schema` and `strict=true`.
- The frozen GPT-5.4 snapshot supports Structured Outputs.
- The old invalid output fails the new schema on all three bad edge-source values.
- `run_03` completed all 11 `batch_1` cases with strict Structured Outputs.
- The `run_03` audit reports `valid_outputs=11`, `valid_html_outputs=11`, and no missing or
  invalid outputs.
- The `run_03` audit reports no cycles across the 11 evaluable graphs.

## How to run the current baseline configuration

Use the Conda environment interpreter, not the standalone Python 3.14 installation:

```powershell
conda activate llm
python .\baseline_single_pass_runner.py
```

The expected successful terminal summary for the current full-batch configuration is:

```text
[direct_graph_extraction] Sync done. ok=11, fail=0
Baseline HTML postprocess: ok=11, skipped=0, fail=0
Audit for run_03: valid=11/11, html=11/11, missing=0, invalid=0
```

Representative case outputs:

- `runs/single_pass_baseline/run_03/batch_1/1/causal_graph.json`
- `runs/single_pass_baseline/run_03/batch_1/1/causal_graph.html`
- raw response and debug-input snapshots under the case directory;
- `runs/single_pass_baseline/run_03/single_pass_audit.json`;
- `runs/single_pass_baseline/run_03/structured_output_schema.json`.

Never print or commit the full API key. It is loaded from `.env_openai`.

## GES implementation and evaluation status

The default `run_evaluation.py` GED algorithm is now a directed, typed Riesen-Bunke-style
bipartite approximation. Its method identifier is
`riesen_bunke_bipartite_directed_node_type_edge_relation_unit_cost_v1`.

- node insertion and deletion costs are one;
- node substitution costs one when ontology types differ and zero otherwise;
- edge insertion and deletion costs are one;
- edge substitution costs one when `has` and `enables` differ and zero otherwise;
- incoming and outgoing local edge assignments are solved separately;
- local incident-edge costs are multiplied by 0.5 to prevent double charging;
- the outer node assignment uses SciPy `linear_sum_assignment`;
- the induced edit path is reconstructed before the six operation counts and GES are computed.

GES is normalized as
`1 - approximate_GED / (|V1| + |E1| + |V2| + |E2|)`. It is an approximate induced-path
score, not the globally minimal exact GED. Node names and evidence text are intentionally
excluded because GES is used as a structural metric.

Eight synthetic unit tests pass in `tests/test_bipartite_ged.py`. They cover identical graphs,
node and edge insertion, node-type and relation substitution, direction reversal, symmetry,
and comparison with exact GED on a small graph. Python compilation and a real-case read-only
evaluation also pass.

The no-few-shot evaluation at
`runs/stability_test/rounds/results/20260819_214907` contains 366 successful cases. Its mean
GES is 0.696372, with values from 0.466667 to 1. Old results identified only as
`ged_bipartite` were generated by the previous implementation and must not be mixed with the
new results. The few-shot, baseline, and dependent comparison figures still require
recomputation with the new method.

The fixed development exclusion file `evaluation_excluded_few_shot_cases.json` records 12
incident cases. The compact active few-shot prompt draws its review patterns from 11 of those
case sources; `batch_9/1` belongs to the annotated development set but is not represented in
the compact prompt. Structural, semantic, and soft F1 evaluations exclude all 12 `batch/case`
keys by default and write `evaluation_case_exclusions.json` beside each result set. Use
`--include-few-shot-cases` only for an explicitly non-held-out analysis.

The existing result set at `runs/stability_test/rounds/results/20260819_214907` predates the
final 12-case exclusion behavior and has no `evaluation_case_exclusions.json` audit. It must
not be described as held-out. Structural, semantic, soft F1, stability, and dependent
summaries must use the frozen 12-case exclusion and the authoritative corpus hierarchy below.

## Directed graph structural metric naming

`scripts/plot_graph_structure_factors.py` currently calculates `avg_degree` as `|E| / |V|`.
For a directed graph, this value equals both mean in-degree and mean out-degree, but it is not
mean total degree, which is `2|E| / |V|`. Calling the current quantity "average degree" is
therefore ambiguous.

The agreed manuscript and figure name is **edge-to-node ratio**, defined as `|E| / |V|`.
Maximum in-degree and maximum out-degree remain separate metrics for upstream convergence and
downstream branching. Rename the internal key from `avg_degree` to `edge_to_node_ratio` and
change all plot, table, caption, and manuscript labels from "Average degree" to "Edge-to-node
ratio". This is a terminology change only and does not require numerical recomputation.

## Known evaluation issues

- `utils/stability_evaluation.py` still calls `compute_graph_edit_metrics` with the removed
  `exact_ged` keyword. Current round-to-round stability comparisons therefore fail.
- `run_stability_evaluation.py` points by default to a directory that does not exist.
- The NetworkX `exact` and `fast` GED branches do not pass `edge_match`, so their raw distances
  ignore edge-relation substitutions and are not comparable with the new bipartite method.
- Existing soft node and edge F1 results used node and relation thresholds of zero. The node
  type is also repeated in the embedding text. These settings can inflate weak same-type node
  matches and incorrect relation matches.
- The semantic metric averages edge-triple embeddings. It omits isolated nodes, causal-path
  order, evidence support, and graph topology, so it must be described only as an auxiliary
  embedding similarity.
- Existing semantic results have no causal-narrative reference, so causal-narrative similarity
  was not computed for the 366-case evaluation.
- Batch summaries collapse the three independent rounds by `batch_id`. Round-level variation
  and per-case paired analyses must be retained in the final statistical analysis.
- Cycle rate, unsupported-edge rate, directionality errors, ontology violations, and missed
  critical paths are not yet integrated into the common evaluation output.
- `run_evaluation.py` defaults to skipping GED operation-count output. This creates an empty
  GED-operation figure even though the bipartite calculation already reconstructs the edit
  path.
- The default `run_evaluation.py` folder contains no graph cases. Pass
  `--folder runs/stability_test/rounds` or update the default before running it without
  arguments.

## Remaining work

1. Visually inspect all 11 `run_03` JSON and HTML outputs for semantic plausibility.
2. Freeze the remaining held-out case IDs, keeping the recorded few-shot exclusions fixed.
3. Point `SOURCE_DIR`/`TARGET_CASES` only to the held-out test set for the final comparison.
4. Increase independent runs, preferably three to five, without changing prompt, schema,
   model, or inference configuration between runs.
5. Add an explicit reference-root mechanism so main and baseline graphs are evaluated against
   the same expert graph by normalized case ID.
6. Fix round-to-round stability evaluation and align it with the new bipartite GED interface.
7. Calibrate soft node matching on a separate development set and require exact matching for
   the controlled edge relations.
8. Recompute few-shot, no-few-shot, baseline, stability, and all dependent figures with frozen
   method identifiers and parameters.
9. Evaluate main method and baseline on identical cases using per-case paired analyses.
10. Report cycle, unsupported-edge, directionality, ontology, and missed-critical-path rates
    in addition to graph similarity and quality metrics.
11. Rename the ambiguous `avg_degree` structural factor to `edge_to_node_ratio` in code and
    all manuscript outputs while preserving its existing `|E| / |V|` calculation.

Do not mix outputs produced by different prompt or schema versions in one statistical result
set.

## Candidate-only ablation runner

`candidate_only_ablation_runner.py` implements an isolated candidate-only branch without
changing the frozen main pipeline, prompt manifest, or step registry. It reuses
`prompt/edge_candidate_extraction.txt` unchanged. Within the isolated output directory, each
`scenario_candidate_extraction_output.json` is copied byte-for-byte to the legacy
`identify_accident_scenario_output.json` input name required by the existing edge-candidate
step. Few-shot input is disabled.

The deterministic postprocessor maps candidate node groups to the standard graph groups and
maps `candidate_edges` to `edges`. It does not merge, split, rename, retype, filter, validate,
link, repair, or remove shortcuts. It writes
`candidate_only_edge_candidate_extraction_output.json`,
`candidate_only_causal_graph.json`, and `candidate_only_case_audit.json` per case. The audit
checks node IDs, H1, endpoint integrity, relation and endpoint types, duplicate edges,
self-loops, isolated nodes, and directed cycles. Invalid edges are reported rather than
silently removed.

The default mode is `dry-run`, which prepares prompts and never calls the API. A complete dry
run prepared 560 case-run prompts under `runs/stability_test/candidate_only`, comprising 112
held-out incident cases in each of five rounds. No edge outputs or graphs exist yet because no
paid API requests have been submitted. The root audit is
`runs/stability_test/candidate_only/candidate_only_audit.json`. Three focused tests pass in
`tests/test_candidate_only_ablation_runner.py`.

## Topology negative-control figure

`scripts/plot_topology_negative_controls.py` plots the topology-destructive controls as a
two-panel dose-response figure for WL similarity and graph edit similarity. It uses the same
serif typography, gray-to-blue palette, axis styling, and PDF/PNG/SVG export pattern as
`scripts/plot_stability_comparison_boxplot.py`. Each control has a distinct marker and line
style, and case-level 95% confidence intervals are shown as bands. The strict default audit
requires 112 held-out incident cases, 100 replicates, all five controls, and severities of
25%, 50%, and 75%. The unperturbed 0% positive-control point remains in the figure.
`--allow-incomplete` is development-only.

The script was compiled and visually checked using the one-case smoke result at
`outputs/topology_negative_controls_smoke`. Those smoke figures validate layout only and must
not be used in the manuscript. Formal figure outputs default to
`runs/stability_test/figures_comparing_rounds/topology_negative_controls` after a complete
result exists under `runs/stability_test/topology_negative_controls`.

## Authoritative corpus and analysis-unit hierarchy

The eligible source corpus contains **114 CSB reports**. Some source reports describe more
than one independently identified incident or event sequence. Those reports were split into
separate analysis cases, producing **124 independently analysed incident cases**. The source
document count and the analysis-case count must not be used interchangeably.

The fixed few-shot development exclusion list contains 12 case identifiers. Excluding those
12 development cases from the 124-case analysis panel leaves **112 held-out incident cases**.
Across four conditions and five runs, the repeated-measures panel therefore contains 2,240
case-run-condition observations, with 560 observations per condition. The independent unit
used by the current statistical scripts is the incident case. The legacy column name
`report_id` stores the normalized `batch_id/case_id` analysis-case key and must not be
described as an original-report count.

Manuscript, response-letter, figure, table, and supplementary wording must distinguish these
levels explicitly: 114 eligible source reports, 124 independently identified incident cases,
12 excluded development cases, and 112 held-out evaluation cases. Statements describing 124
or 112 as numbers of reports, or describing a 115-report cohort reduced to 103 reports, are
obsolete and must be corrected. Report-level identifiers in the corpus supplement should map
each analysis case back to its originating CSB report, especially for split multi-incident
reports.

## Final five-run node, edge, and semantic evaluation

`run_final_5run_auxiliary_evaluation.py` now evaluates the same fixed 112 held-out incident cases
across five runs for four conditions: Single Pass, No Revision, Revision, and Revision + FS.
It uses `rounds/round_1/<batch>/<case>/updated_causal_graph.json` as the case-matched
reference source and enforces the fixed 12-case development exclusion list. The completed
result is under `runs/stability_test/evaluation_final/auxiliary/20260829_180113` and contains
2,240 successful case-run-condition rows (560 per condition; 112 independent cases per condition).

Node matching embeds normalized node text without repeating the ontology type, requires the
node types to agree, and uses a threshold of 0.40 selected only on the 12 excluded development
cases. Edge matching requires mapped endpoints and exact normalized `has`/`enables`
relations. Semantic similarity remains an auxiliary cosine similarity between mean-normalized
embeddings of directed edge-triple sentences. The embedding model is
`text-embedding-3-small`. See `node_threshold_calibration.csv` and
`auxiliary_evaluation_audit.json` in the result directory for the frozen parameters and case
counts.

`scripts/plot_stability_comparison_boxplot.py` now combines structural similarity, node
matching, edge matching, and semantic similarity in a four-panel five-run figure. It preserves
the established gray-to-blue palette and places Single Pass at the far left in every metric
group. Publication outputs and the strict input audit are under
`runs/stability_test/figures_comparing_rounds/five_run` with the prefix
`five_run_combined_boxplot_label_`; PDF, PNG, and SVG variants are generated.

## CSB completed-report catalogue extraction

The public CSB completed-investigations catalogue is now extracted by
`scripts/scrape_csb_completed_reports.py`. The scraper walks all result pages, visits each
detail page, caches the raw HTML, and records official titles, dates, page links, report links,
accident types, and derived report-product types. It does not match the catalogue to the local
corpus or assign inclusion and exclusion decisions.

The catalogue snapshot generated on 2026-08-24 contains 133 unique CSB catalogue records
across 19 result pages. All 133 records have a final-report release date, detail-page URL, and
primary report URL. The CSB pages do not explicitly display a separate investigation-number
field. Recommendation-number prefixes are therefore stored only as review-required candidates
and must not be reported as verified identifiers.

Current outputs are under `outputs/csb_completed_catalog`. The compact table is
`CSB_completed_reports_table.csv`; the complete audit table and JSON snapshot are
`csb_completed_reports.csv` and `csb_completed_reports.json`. The current extraction reports
133 successful records with no duplicate catalogue IDs.

## Reminder for 2026-08-26: causal-narrative prompt-version audit

Review the causal-narrative prompt history before continuing or accepting `round_4` as a
comparable stability run. Commit `d4d426bee705728bb7fb5fa327b31f453271df26`, authored under
the local Git identity on 2026-04-16 with subject `adding 3 steps for the causal narrative
extraction, not improved stability`, introduced
`causal_narrative_candidate_extraction`, `causal_narrative_structure_validation`, and the
current three-stage `causal_narrative_extraction` prompt.

Saved prompt snapshots show that `round_1` used the earlier single-stage causal-narrative
prompt for 121 reports, while `batch_4/1` used the three-stage version. `round_2` and
`round_3` used the earlier single-stage extraction prompt for all 122 reports. The candidate
and validation files present for `batch_4/1` in later rounds appear to have been copied seed
files rather than inputs used by their saved extraction prompts.

The attempted `round_4` run configured `causal_narrative_extraction` as its first active step
under the current three-stage registry. Prompt construction failed for 121 cases because the
required candidate-extraction and structure-validation outputs were absent, so only one API
Batch request was created. Do not pool this incomplete run with any evaluation. Decide whether
to restore the earlier single-stage prompt for comparability, rerun the full three-stage
pipeline as a separately versioned experiment, or regenerate the inconsistent prior
observation. Record the selected prompt hash and version for every retained round.

On 2026-08-25, the earlier single-stage option was selected for future comparable stability
runs. `prompt/causal_narrative_extraction.txt` was restored exactly to the version present at
commit `42d97cad4ce7ae8252fd0728440bf8930fb9b1f4`. Its Git blob hash is
`47aa6902eb0b5ea0661cfde42245d14baf3f03e8`. The corresponding manifest entry now requires
only `incident_description` and `identify_hazard_consequence_output`, and the step registry
maps those variables directly to the two folder outputs. Stale registrations for the archived
candidate-extraction and structure-validation prompts were removed. Their historical files
remain under `prompt/past_prompt`.

Prompt-manifest-registry validation now returns zero errors. A read-only dry render on
`runs/stability_test/rounds/round_3/batch_1/1` succeeded with exactly the three materialized
keys `incident_description`, `identify_hazard_consequence_output`, and `few_shot_examples`.
The rendered prompt contains no candidate-extraction or structure-validation blocks. This
restoration does not make the prior mixed-version rounds retroactively comparable. Any new
round must use a new output directory and record the prompt blob hash and inference settings.

## Current round-4 batch smoke-test configuration

`batch_main_runner.py` now supports `TARGET_BATCHES` and is temporarily configured with
`TARGET_BATCHES=("batch_1",)`, using `rounds_with_few_shot/round_3` as the source and
`STABILITY_START_ROUND=4`. The stability preparation logic preserves the destination as
`round_4/batch_1/<case>` even when only one batch is selected. Set `TARGET_BATCHES=None`
to restore all-batch processing.

With `STABILITY_RESUME=False`, starting a later all-batch round-4 run will recreate the
entire `round_4` directory, replacing the batch-1-only smoke-test output rather than
incrementally retaining it.

## Required case rerun

`batch_5/3` must be rerun. Do not include its existing output in the final evaluation or
pool it with audited results until the replacement run completes successfully under the
frozen prompt, model, inference configuration, and schema, and the regenerated artifacts
pass the same output and graph audits as the other retained cases.

`batch_main_runner.py` is temporarily configured to rerun this case in place with
`BASE_DIR=runs/stability_test/rounds_with_few_shot/round_1/batch_5/3`, Batch API mode,
`STABILITY_ROUNDS=1`, `STABILITY_START_ROUND=1`, and `STABILITY_OUTPUT_ROOT=None`.
The active pipeline outputs are therefore overwritten directly in that case directory;
no additional stability-round directory is created. Restore the normal all-report
stability configuration after this repair run finishes and is audited.

The configuration above is historical and is no longer the current runner state.
`batch_main_runner.py` is now a completion-aware few-shot recovery runner. It checks all
122 case folders in `rounds_with_few_shot/round_4`, preserves the completed
`causal_narrative_extraction` and `scenario_candidate_extraction` outputs, and resumes from
`scenario_structure_validation`. After all remaining Round 4 steps finish, it creates
`round_5` from Round 4 and runs all nine steps. If Round 5 later exists after an interrupted
launch, the same script resumes it from the first step whose output is not present for every
case. It uses Batch mode and one combined 122-request Batch per step.

## Required reviewer Comment 7 statistical revision

Reviewer Comment 7 requests per-report paired comparisons under a repeated-measures or
mixed-effects framework, with effect sizes, confidence intervals, and multiplicity control.
Because independently identified incidents are the actual graph-analysis units, this request
is operationalized as paired comparisons at the incident-case level, while retaining the
mapping from every case to its source report.
The graph-level evaluation algorithms and per-case metric values do not change because of
this comment. GES, WL similarity, node and edge F1, and semantic similarity must still be
calculated per generated graph using their frozen implementations.

The required change is the inferential aggregation of those case scores. An incident case,
identified by normalized `batch_id/case_id`, is the independent unit. Multiple rounds from
the same case are repeated observations and must not be treated as independent samples. Keep
the case-round rows in `case_scores.csv`, but analyse each metric using a model such as
`metric ~ condition + round + (1 | report_id)`. Conditions must also be compared through
within-case paired contrasts. Here `report_id` is only the legacy code-field name for case ID.

For each primary metric and planned condition contrast, report the estimated paired
difference, a 95% confidence interval, an appropriate paired effect size, the raw p-value,
and the multiplicity-adjusted p-value. Use Holm correction across the declared family of
primary tests unless a different correction is justified and documented. Round-level means
and standard deviations may remain as descriptive results, but `batch_scores.csv` or pooled
case-round rows must not be used as independent observations for inferential claims.

The authoritative hierarchy is now 114 eligible source reports, which yield 124 independent
incident cases after multi-incident reports are split. The fixed 12-case development set is
excluded from evaluation, leaving 112 held-out cases. With five runs and four conditions, the
inferential panel contains 2,240 case-run-condition observations. The obsolete statement that
12 reports were removed from a 115-report cohort to leave 103 reports must not be used.

The compact active few-shot file draws 24 feedback patterns from 11 case sources. The fixed
development exclusion list nevertheless contains 12 cases, including `batch_9/1`, because
all development cases are conservatively excluded even when a case is absent from the compact
prompt. Structural, semantic, soft-matching, mixed-effects, and figure audits now enforce all
12 exclusions. Manuscript and reviewer-response text must call 112 the number of held-out
incident cases, not the number of source reports.

## No Revision condition redefinition and naming migration (2026-09-02)

The manuscript condition `No Revision` now refers to the isolated two-stage path
`scenario_candidate_extraction -> edge_candidate_extraction`. The earlier condition that
used the full validated pipeline graph before diagnosis/revision is no longer used as the
No Revision comparator. Its files have not been deleted.

The runner and artifacts are now named consistently:

- runner: `no_revision_runner.py`;
- raw root: `runs/stability_test/no_revision`;
- graph: `no_revision_causal_graph.json`;
- edge snapshot: `no_revision_edge_candidate_extraction_output.json`;
- case/input/round audits use the `no_revision_*.json` prefix;
- structural result: `runs/stability_test/evaluation_final/no_revision/20260902_164902`.

The former `candidate_only_ablation_runner.py`, `runs/stability_test/candidate_only`, and
`evaluation_final/candidate_only` names were replaced. All five rounds contain the fixed 112
held-out incident cases, for 560 case-run graphs. The structural evaluation completed with
560 successful rows; mean WLS is 0.663314 and mean GES is 0.674960.

The earlier `evaluation_final/no_few_shot` directory was copied with hash verification to
`evaluation_final/backup_old_no_revision_20260902/no_few_shot` and then renamed to
`evaluation_final/revision`. It remains the source of the accept-all revised graph metrics
for the `Revision` condition; its generated-graph columns must no longer be presented as
No Revision. Earlier auxiliary, five-run figure, and paired-effects outputs were also copied
under `evaluation_final/backup_old_no_revision_20260902` before regeneration.

All active evaluation condition keys are now `single_pass`, `no_revision`, `revision`, and
`revision_fs`. The auxiliary evaluator uses the frozen node threshold 0.40 and permits the
new No Revision source to contain only held-out cases. The replacement auxiliary evaluation
completed at `evaluation_final/auxiliary/20260902_172711` with 2,240 successful rows: 560 for
each of the four conditions. It required 41 embedding API calls and wrote the missing entries
to the shared cache. The combined and paired boxplots, descriptive results table, and
nine-metric mixed-effects outputs were then regenerated. The mixed-effects panel retains 112
cases, 2,240 repeated observations, nine metrics, six planned contrasts per metric, and one
Holm family of 54 tests. The pre-migration auxiliary and downstream artifacts remain
historical backups only.

## Interactive causal-graph HTML label-option repair

The JSON graph editor previously treated the pipe-delimited event-label declaration in
`scheme/accident_scenario_schema.json` as one long dropdown option. This prevented selecting
the seven individual event labels and could make an existing event node display the first
dropdown option when its current label was absent.

`_build_schema_form_options` now expands pipe-delimited labels and maps every expanded label
to its canonical node type. Controlled hazard-consequence names are also included as
compatibility aliases because historical main-method graphs use both
`label=HazardConsequence` and labels such as `BLEVE`, `Jet fire`, or `Dust explosion`.
The node-detail form also preserves an unexpected current label instead of silently falling
back to the first option.

The repair utility is `scripts/repair_causal_graph_html_schema_options.py`. It replaces only
the embedded `schemaForm` JSON and preserves graph snapshots, review suggestions, revision
decisions, and other HTML content. It considers only the three official filenames
`causal_graph.html`, `updated_causal_graph.html`, and
`updated_causal_graph_accept_all.html` when scanning directories.

On 2026-08-27, the utility repaired all 294 official graph HTML files under
`runs/stability_test/rounds_with_few_shot/round_4`. The applied audit is stored at
`outputs/round_4_html_schema_repair_applied.json`. A second dry run reported 294 unchanged
files. Three focused tests pass in `tests/test_causal_graph_html_schema_options.py`, and no
repaired official HTML contains a pipe-delimited label option or an embedded node label
missing from the resulting dropdown options.

The same repair was then applied to all 1,464 official graph HTML files in `round_1`,
`round_2`, `round_3`, and `round_5`. The corresponding audit is
`outputs/rounds_1_2_3_5_html_schema_repair_applied.json`. Across all five few-shot rounds,
1,758 HTML files were repaired with zero errors and zero embedded node labels missing from
the corrected form options.

## Baseline reference-graph copy utility

`scripts/copy_reference_graphs_to_baseline.py` prepares fixed main-method reference artifacts
for the single-pass baseline runs. The default source is
`runs/stability_test/rounds/round_1`, and the default target is
`runs/stability_test/single_pass_baseline_all_batches`. Target cases are discovered beneath
all `run_*` directories and matched to the source strictly by normalized
`batch_id/case_id`.

For every exact match, the utility copies both `updated_causal_graph.json`, which is read by
the evaluation code, and `updated_causal_graph.html`, which supports human inspection. It
does not copy review-state files, accept-all files, generated `causal_graph.json` files,
prompts, responses, or debug artifacts. The same fixed reference pair is copied to each
independent baseline run. The script defaults to dry-run mode, validates the graph JSON and
HTML inputs, records source and destination SHA-256 hashes, uses atomic writes, refuses to
replace a different existing destination unless `--overwrite` accompanies `--write`, and
writes a per-artifact JSON audit.

The 2026-08-27 dry run found 620 baseline case-run directories and therefore 1,240 intended
reference artifacts. Of these, 1,220 artifacts can be matched exactly. The remaining 20
missing artifacts correspond to two report identities, `batch_7/2_split_1` and
`batch_7/2_split_2`: each lacks both the JSON and HTML reference in each of five baseline
runs. The source currently contains only the combined case `batch_7/2`, whose
`updated_causal_graph.json` and `updated_causal_graph.html` must not be duplicated into both
split cases because the two baseline inputs represent different incident portions. Create
and verify separate references at
`rounds/round_1/batch_7/2_split_1/updated_causal_graph.{json,html}` and
`rounds/round_1/batch_7/2_split_2/updated_causal_graph.{json,html}` before claiming complete
reference coverage. The dry-run audit is
`outputs/baseline_reference_copy_dry_run.json`. No reference files had been copied when this
entry was recorded.

## Batch 7 case-2 split migration

On 2026-08-27, the combined `batch_7/2` case directory was moved out of every retained round
in both `runs/stability_test/rounds` and
`runs/stability_test/rounds_with_few_shot`. Ten directories were moved in total: one from
each of five rounds in each condition. They were not deleted and remain recoverable under
`runs/stability_test/archived_batch_7_case_2_20260827`, with the original
`<series>/<round>/batch_7/2` hierarchy preserved.

The input directories `batch_7/2_split_1` and `batch_7/2_split_2` were then copied from
`runs/stability_test/batched_reports` into `batch_7` in all ten rounds, creating 20 new case
directories. Each new directory currently contains its incident PDF and
`identify_incident_output.json`; the source-only hidden `desktop.ini` metadata file was
intentionally not copied. SHA-256 verification passed for all 40 copied experimental input
files with zero mismatches. Every old in-round `batch_7/2` path is absent, every archived
copy is present, and both split directories are present in every round.

These new split directories contain inputs only. They must be run through the appropriate
frozen no-few-shot or few-shot pipeline for each round before they are included in evaluation.
They do not yet contain independently reviewed `updated_causal_graph.json` or
`updated_causal_graph.html` references, so the baseline-reference copy audit will continue to
report the two split report identities as missing until those references are constructed and
verified.

## No-few-shot Round-5 recovery status (2026-08-28)

`runs/stability_test/rounds/round_5` contains 124 case directories. The recovery initially
reported 121 incomplete cases because `batch_5/3`, `batch_7/2_split_1`, and
`batch_7/2_split_2` had already completed the remaining pipeline steps; 121 was therefore an
incomplete-case count, not the Round-5 corpus size.

OpenAI Batch validation repeatedly failed before processing any request. The final recorded
Batch object reported that its newly uploaded input file could not be found or that the
organization lacked access, even though the same API client could retrieve that file with
`purpose=batch` and `status=processed`. The failed Batch had zero request counts and zero
token usage. After 29 unsuccessful scheduled attempts, `repair_no_few_shot_round5.py` was
changed to the Responses API with asynchronous execution, a maximum concurrency of 10,
per-step missing-output selection, and `stop_on_step_failure=True`. Completed case-step
outputs remain preserved on reruns.

The Responses recovery subsequently completed. A filesystem audit on 2026-08-28 found all
124 cases containing each of the six recovered model outputs:
`identify_accident_scenario_output.json`, `edge_candidate_extraction_output.json`,
`edge_structure_validation_output.json`, `causal_edge_linking_output.json`,
`graph_diagnosis_output.json`, and `graph_revision_planning_output.json`. All 124 cases also
contain `causal_graph.json` and the three regenerated accept-all artifacts:
`updated_causal_graph_accept_all.json`, `updated_causal_graph_accept_all.html`, and
`updated_causal_graph_review_state_accept_all.json`.

Generation covers all 124 cases. The 12 fixed few-shot development cases are excluded only
during held-out evaluation, so the intended inferential unit count remains 112 independent
incident cases per condition and 560 case-run observations per condition across five runs.

## Paired mixed-effects analysis and figure

`figures/gen_fig_paired_mixed_effects.py` now implements the final four-condition inferential
analysis. The conditions are Single Pass, No Revision, Revision, and Revision + FS. The
default inputs are single-pass result `20260828_141620`, final no-few-shot result
`20260829_170239`, and few-shot result `20260828_140052`. No Revision reads the generated-graph
columns, while Revision and Revision + FS read the corresponding
`*_accept_all_vs_updated` columns. This mapping is recorded in the input audit.

The script fits `metric ~ condition + run + (1 | report_id)` by REML for GES and WLS. The
legacy `report_id` field identifies normalized incident cases. It requires exactly 112 cases
and five runs for every condition. The final panel contains 2,240 case-run-condition
observations, with 560 per condition. Six pairwise condition contrasts are
estimated for each metric, giving 12 primary tests under one Holm correction. Cohen's dz is
calculated from per-case five-run condition means, with 10,000 case-level bootstrap
resamples for its confidence interval.

The original L-BFGS fit falsely reported convergence with infinite likelihood, a zero
intercept, and zero random-intercept variance. The fitter now rejects nonfinite or singular
solutions and tries BFGS before Powell and L-BFGS. Both final models converged with BFGS.
Random-intercept variances were 0.00565 for GES and 0.00529 for WLS. The final analysis is not
preliminary and retains all 112 held-out incident cases.

Final artifacts are under `runs/stability_test/statistical_analysis/paired_effects`. They
include `analysis_long_data.csv`, `paired_mixed_effects_results.csv`,
`analysis_input_audit.json`, and PDF, PNG, and SVG figure outputs. The earlier 111-report
artifacts under `paired_effects_preliminary` are superseded and must not be reported.

All three pipeline conditions significantly outperform Single Pass for both primary metrics
after Holm correction. Within the pipeline, Revision versus No Revision increases WLS by
0.0214 (95% CI 0.0089 to 0.0340; Cohen's dz 0.631; Holm-adjusted p = 0.00488). The analogous
GES difference is 0.0038 (95% CI -0.0082 to 0.0157) and is not significant. Revision + FS
does not significantly improve either primary metric relative to No Revision or Revision.
Do not claim a significant FS benefit for WLS or GES.

The current figure emitted by `gen_fig_paired_mixed_effects.py` is a 2x2 mixed-effects forest
plot. The rows separate GES and WLS, while the columns show model-adjusted paired differences
and Cohen's dz. Diamonds show estimates, error bars show 95% confidence intervals, and filled
diamonds indicate Holm-adjusted p < 0.05. The figure uses the same Times font, gray-to-blue
condition palette, panel-title style, grid, spine widths, and PDF/PNG/SVG export settings as
`plot_stability_comparison_boxplot.py`. This inferential figure complements rather than
duplicates the paired descriptive boxplot.

`figures/gen_fig_mixed_effects_by_condition.py` now adds a condition-oriented 3x3 companion
figure covering GES, WLS, semantic similarity, node precision/recall/F1, and edge
precision/recall/F1. It strictly merges the structural and auxiliary evaluations one-to-one
on `condition/report_id/run`, retains 112 incident cases and 2,240 repeated observations, and
uses the same mixed-effects formula. Boxes show each case's five-run condition mean; white
diamonds and error bars show run-adjusted marginal means and 95% confidence intervals, with
each adjusted mean labelled to three decimal places. Three
sequential paired contrasts are annotated per panel with Cohen's dz, while one Holm
correction is applied across all six planned contrasts for all nine metrics (54 tests).
The audit, adjusted-mean table, complete contrast table, long data, and PDF/PNG/SVG outputs
are stored under `runs/stability_test/statistical_analysis/paired_effects` with the
`condition_` and `fig_mixed_effects_by_condition` prefixes.

## Original and paired five-run boxplots

`scripts/plot_stability_comparison_boxplot.py` now generates both the original report-run
plots and additional paired report-mean plots in one execution. Both variants preserve the
same 2x2 construction, metric order, labels, colors, fonts, legend, and export settings.
Original files keep their existing names and use 560 report-run observations per condition.
Paired files add `_paired` to the filename and use 112 values per condition after averaging
the five runs within each report.

The output directory is `runs/stability_test/figures_comparing_rounds/five_run`. Original
files use `five_run_combined_boxplot_label_{above,left}.{pdf,png,svg}`. Paired files use
`five_run_combined_boxplot_paired_label_{above,left}.{pdf,png,svg}`. Compatibility copies are
also written one directory higher unless `--no-legacy-aliases` is supplied. The audit
`five_run_combined_boxplot_audit.json` records 560 values for every original condition-metric
series and 112 values for every paired series.

The displayed order remains Single Pass, No Revision, Revision, and Revision + FS. The colors
remain `#D0D0D0`, `#A8A8A8`, `#5E81AC`, and `#2E4A6E`. For `label_above`, every numeric mean
label is positioned independently. Its height is the larger of that condition's upper whisker
and highest flier, plus 0.02. The white diamond is placed at the actual arithmetic mean. In
the paired variant, the box distribution contains case-level five-run means. Because every
case has exactly five runs, original and paired arithmetic means are equal, while medians,
quartiles, whiskers, and fliers can differ.

## Final five-run interpretation for manuscript reporting

The paired condition means for Single Pass, No Revision, Revision, and Revision + FS are,
respectively, WLS 0.506, 0.732, 0.754, and 0.745; GES 0.414, 0.692, 0.696, and 0.694; node F1
0.552, 0.830, 0.828, and 0.831; edge F1 0.328, 0.685, 0.691, and 0.689; and semantic
similarity 0.892, 0.958, 0.958, and 0.959.

FS primarily changes the precision-recall balance. Relative to Revision, Revision + FS raises
edge recall from 0.695 to 0.707 and node recall from 0.832 to 0.842. It lowers edge precision
from 0.699 to 0.683, leaving edge F1 essentially unchanged at 0.691 versus 0.689. Node, edge,
and semantic comparisons are descriptive because formal mixed-effects contrasts were
prespecified only for WLS and GES. The manuscript may state that FS descriptively increases
edge recall, but must not claim that FS significantly improves overall structural quality.

The five-run CV results also do not support a claim that FS consistently improves stability.
Revision + FS has CVs of 2.15% for WLS, 3.88% for edge precision, 2.46% for edge recall, and
3.09% for edge F1. Semantic similarity remains the most stable metric, with condition CVs
between 0.10% and 0.22%. Similarity metrics do not establish evidence support, causal
validity, unsupported-edge rates, or missed critical paths.

`scripts/plot_graph_structure_factors.py` now uses Revision + FS scores averaged across five
runs within each of 112 independent incident cases. It uses the agreed `edge_to_node_ratio`
name. The case-level Pearson results are stored in `figures/fig_graph_structure_factors_audit.json`.
Raw correlations show WLS versus edge-to-node ratio at r = -0.237 (p = 0.012) and GES versus
graph size at r = -0.334 (p < 0.001). The other six raw p-values exceed 0.05. If Holm
correction is applied across all eight correlations, only graph size versus GES remains
significant (adjusted p = 0.0026).

The current regression-band calculation in `plot_graph_structure_factors.py` uses the slope
standard error returned by `scipy.stats.linregress` as though it were the residual standard
error. Do not describe the shaded region as a valid 95% regression confidence band until this
calculation is corrected and the figure is regenerated.

The revised PSEP-style Results and Discussion draft now uses four conditions, five runs, 112
independent incident cases, paired case-level boxplots, and mixed-effects inference for WLS and
GES. Ten substantive paragraphs were drafted at 116--130 words each, with every sentence at
25 words or fewer. The old three-condition, three-round wording and the claims that FS
improves GES, edge F1, or overall stability are superseded.

## Topology-destructive negative controls

`scripts/evaluate_topology_negative_controls.py` implements corpus-level negative controls
for validating the topology sensitivity of the frozen GES and WL metrics. It uses the fixed
reference graphs under `runs/stability_test/rounds/round_1`, applies the 12-case few-shot
development exclusion by default, and requires exactly 112 retained incident cases. It directly
reuses `compute_structural_similarity` and the directed typed bipartite GES implementation in
`scripts/evaluation_structure_similarity.py`.

The topology-only controls are non-H1 node deletion, edge deletion, edge-direction reversal,
directed endpoint rewiring, and a combined control. Endpoint rewiring uses directed double-edge
swaps to preserve every retained node's in-degree and out-degree. Node labels, node types, edge
relations, and textual evidence are not deliberately shuffled or substituted. Defaults are
10%, 25%, and 50% severity, 100 fixed-seed randomizations per case/control/severity, and
eight case-level worker processes. Randomization replicates are averaged within case, so the
inferential unit remains the incident case rather than the randomized graph.

The script writes resumable per-case shards, `replicate_scores.csv`, `report_summary.csv`,
`overall_summary.csv`, and `topology_negative_control_audit.json`. The `report_summary.csv`
filename and any `report_id` field are legacy implementation names for cases. The overall
summary includes case-level means, 95% t confidence intervals, decrease from the positive self-comparison,
Cohen's dz, raw p-values, and one Holm correction across the metric-by-control-by-severity
family. The audit records fixed seeds, method identifiers, retained cases, exclusions,
parameters, and whether mean scores are nonincreasing with perturbation severity.

Five focused tests pass in `tests/test_topology_negative_controls.py`. A real one-case smoke
test also passed, and discovery verified 124 available reference cases derived from 114 source
reports, 12 configured case exclusions, and 112 retained held-out cases. The smoke artifacts are under
`outputs/topology_negative_controls_smoke` and are development-only, not manuscript results.
The full default run completed on 2026-08-29 under
`runs/stability_test/topology_negative_controls/final`. It contains 112 case shards and
168,112 comparisons: 168,000 randomized negative-control graphs plus 112 positive
self-comparisons. The outputs contain no missing metric values or duplicate
report/control/severity/replicate keys; `report` is the legacy case identifier in these keys.
Positive-control GES and WLS are exactly 1.0 for all 112 cases.

At target severities of 10%, 25%, and 50%, respectively, mean GES was 0.835, 0.657, and
0.452 for node deletion; 0.904, 0.799, and 0.698 for edge deletion; 0.870, 0.746, and 0.628
for edge-direction reversal; 0.921, 0.864, and 0.785 for endpoint rewiring; and 0.702, 0.546,
and 0.394 for the combined control. Mean WLS was 0.889, 0.747, and 0.553; 0.914, 0.802, and
0.649; 0.827, 0.662, and 0.532; 0.884, 0.815, and 0.737; and 0.680, 0.514, and 0.380 for the
same five controls. Every control-metric overall mean was nonincreasing with severity. All 30
negative-control tests remained significant after a single Holm correction; the largest
adjusted p-value was approximately 4.12e-39.

Because graph sizes are discrete, target percentages do not always equal realized percentages
in small graphs. In particular, endpoint rewiring changed a mean of 14.9%, 28.2%, and 52.2%
of edges at nominal 10%, 25%, and 50% levels. Manuscript reporting should call these target
perturbation levels and report the realized fractions. A few individual-report curves have
ties or small nonmonotonic differences caused by integer rounding and randomization, although
the corpus-level means are monotonic for every metric and control.

Post-run inspection found that the original endpoint-rewiring implementation allowed newly
created edges to be selected by a later double-edge swap. In 189 of the 33,600 endpoint-only
randomizations (0.56%), later swaps exactly restored the original edge set. This small fraction
does not alter the observed corpus-level sensitivity trend, but the run must be treated as
superseded rather than the final manuscript result because every randomized negative control
should actually alter topology. The implementation now permits only untouched original edges
to participate in a swap, preventing later swaps from undoing earlier ones. All five tests
pass after the correction, and a 37,200-randomization stress audit across all 124 reference
graphs found zero unchanged edge sets and zero cases with no rewired edges. Rerun the full
analysis into a new output directory before reporting the final numerical results.

## Reviewer-response and supplementary-table audit (2026-09-08)

The local `psep-reviewer-response` skill was updated and validated. Every response-drafting
turn must first provide a short Chinese strategy explanation, then quote the relevant current
manuscript passage verbatim, and then assess whether that passage fully answers the reviewer.
Any wording not yet present in the inspected manuscript must be displayed separately under
`Proposed revision in` or `Proposed addition to`. Proposed, polished, reconstructed, or
paraphrased wording must never appear below a completed-action statement such as `The revision
was made in Section X, as shown below.` Text beneath such a statement must be copied exactly
from the current manuscript. The updated skill passes `quick_validate.py` with UTF-8 mode.

The complete source for Supplementary Table S2 is
`runs/stability_test/statistical_analysis/paired_effects/condition_mixed_effects_contrasts.csv`.
It contains 54 rows, comprising nine metrics and six planned condition contrasts per metric.
It reports model-adjusted differences, difference standard errors, two-sided 95% confidence
limits, paired Cohen's dz values and bootstrap limits, raw p-values, and Holm-adjusted p-values.
Condition-specific adjusted means and their intervals are stored separately in
`condition_adjusted_means.csv`. The older `paired_mixed_effects_results.csv` contains only 12
rows for WLS and GES and must not be used as the complete Table S2.

The current accepted-text manuscript identifies the complete contrast results as Table S2 in
the statistical-method passage, but the Figure 3 caption still refers to Table S1. Table S1 is
already assigned to corpus identifiers and exclusions. The Figure 3 caption must therefore be
changed from Table S1 to Table S2 before submission.

The accepted-text manuscript currently uses GES for the normalized graph-edit similarity in
its narrative, tables, figures, and results. Reviewer responses must not claim that GED was
removed everywhere. GED is reserved for the underlying unnormalized edit distance in the
formal definition and derivation, whereas GES is the normalized similarity that is reported
and interpreted. The current Section 3.2 graph-factor result reports graph size versus GES as
`r = -0.334` with `p < 0.001`; the older response wording using `r = -0.276` is obsolete.

The current case study is numbered Figure 6. Section 3.3.1 describes Figure 6(a) as the
expert-verified reference graph constructed from the original CSB causal findings and Figure
6(b) as an independent automated-pipeline result. The text distinguishes the reference
pathway involving `liquid` and `high volatility` from the automated revision involving
`liquid` and `combustibility`. One stale sentence still says `Figure 5(b)` and must be changed
to `Fig. 6(b)`. The current manuscript does not explicitly state that Figure 6(a) contains no
modification highlighting, so that sentence must not be quoted as existing manuscript text
unless it is first inserted and verified.
