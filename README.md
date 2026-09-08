# Causal Graph Extraction Pipeline

Extract and evaluate process-safety causal graphs from incident descriptions using a frozen ontology and LLM prompts.

## Setup

Run from the repository root in a Python environment with the project dependencies:

```bash
pip install -e .
```

The evaluation tools additionally require NumPy, SciPy, pandas, matplotlib, NetworkX, and GraKeL. The published dependency list is not a frozen environment lockfile.

Create a local `.env_openai` containing `OPENAI_API_KEY`. Credentials, experiment outputs under `runs/`, and local maintenance utilities are excluded from Git.

## Experimental conditions

| Condition | Entry point | Scope |
| --- | --- | --- |
| Single Pass | `baseline_single_pass_runner.py` | One strict JSON-schema model call per case and run |
| No Revision | `no_revision_runner.py` | Scenario candidates followed by edge candidates, without validation or revision |
| Revision | `batch_main_runner_no_few_shot.py` | Main pipeline without few-shot feedback; evaluate the accept-all revised graph |
| Revision + FS | `batch_main_runner.py` | Main pipeline with few-shot diagnosis and revision feedback |

The main pipeline's active sequence after prepared hazard identification is:

```text
causal_narrative_extraction
scenario_candidate_extraction
scenario_structure_validation
identify_accident_scenario
edge_candidate_extraction
edge_structure_validation
causal_edge_linking
graph_diagnosis
graph_revision_planning
```

The causal-narrative prompt is the restored single-stage version. Historical candidate and validation stages for causal narratives are not part of this sequence. Preserve the frozen prompts and schemas when comparing conditions.

## Configure before generation

Both main-method runners generate rounds 1 through 5 from the same prepared source tree, defaulting to `runs/stability_test/batched_reports/batch_*/<case>/`. Each case must contain `identify_incident_output.json` and the fixed `identify_hazard_consequence_output.json`. Raw incident descriptions alone are insufficient for these nine-step runners. Obtain the prepared inputs used in the experiment; do not substitute newly generated hazard outputs when reproducing the frozen comparison.

- `batch_main_runner_no_few_shot.py` writes Revision rounds to `runs/stability_test/rounds`.
- `batch_main_runner.py` writes Revision + FS rounds to `runs/stability_test/rounds_with_few_shot`. It reads the committed compact feedback snapshot under `prompt/review_feedback/case_coverage_12/`; this file is byte-identical to the original experiment input.
- `baseline_single_pass_runner.py` writes five runs to `runs/stability_test/single_pass_baseline_all_batches`, matching the final evaluator. Its source cases require incident descriptions, not the main method's hazard outputs.
- `no_revision_runner.py` defaults to dry-run and uses scenario candidates from the corresponding completed Revision rounds. Run it after the no-few-shot main method. Consult `--help` to select API execution.

Check prepared inputs before launching the main methods:

```bash
python batch_main_runner_no_few_shot.py --dry-run
python batch_main_runner.py --dry-run
```

These checks render the first active prompt for every selected case, validate prepared JSON inputs and feedback availability, and check existing round outputs. They do not invoke the API or write experiment artifacts. Both runners support `--source-dir` and `--output-root`. Existing complete rounds are skipped; incomplete rounds produce an error and are preserved. Use a new output root for a separate experiment. Availability checks do not certify historical prompt equivalence or scientific validity.

After successful checks, run the same commands without `--dry-run` to generate the two main conditions, followed by the Single Pass and No Revision runners. Generation makes paid API requests. Keep the frozen model, inference settings, prompts, and schemas unchanged. Download and place the expert reference graphs separately; generated accept-all revisions are not expert references.

## Evaluation

The corpus hierarchy is 114 source CSB reports, 124 incident cases, 12 excluded development cases, and 112 held-out evaluation cases. `evaluation_excluded_few_shot_cases.json` records the fixed exclusions. Five runs across four conditions yield 2,240 case-run-condition observations. The legacy `report_id` field identifies an incident case, not an original source report.

```bash
# Structural evaluation of an explicitly selected result folder
python run_evaluation.py --folder <run_dir>

# Audit and evaluate all four conditions across five runs
python run_final_5run_evaluation.py

# Final node, edge, and auxiliary semantic evaluation
python run_final_5run_auxiliary_evaluation.py --help
```

Inspect the configured input roots before the final five-run evaluation. Both conditions and references must be matched by normalized `batch_id/case_id`. The auxiliary evaluator imports `run_semantic_evaluation.py`, which remains part of the repository.

GES is normalized directed, typed bipartite approximate graph-edit similarity. WLS is the WL structural similarity. Final node matching requires equal ontology types and a development-calibrated threshold of 0.40; edge matching requires mapped endpoints and exact controlled relations. Semantic similarity is an auxiliary embedding measure, not evidence of causal validity.

Repeated runs of the same case are repeated observations. Inferential comparisons must retain case pairing and use the declared multiplicity correction. The historical standalone `run_stability_evaluation.py` is excluded because its GED interface is obsolete.

## Experiment results

Experiment results are available on [Google Drive](https://drive.google.com/drive/folders/1apb6cQ8Xc7TADFh9npXLjE4DztVVUwfB?usp=sharing).

## Repository layout

| Path | Contents |
| --- | --- |
| `pipeline/` | Pipeline construction, registration, and execution |
| `prompt/` | Prompts, manifest, hazard vocabulary, and available feedback resources |
| `scheme/` | Ontology definitions and strict baseline output schema |
| `utils/` | Shared processing, evaluation, and evaluation plotting implementation |
| `scripts/` | Evaluation, statistical analysis, plotting, and data preparation |
| `tests/` | Focused implementation checks |
| `runs/` | Local inputs, generated graphs, references, and results; not distributed by Git |

The CSB catalogue scraper records public catalogue metadata; it does not assign corpus inclusion decisions. Reference copying defaults to dry-run and matches exact case identifiers. Negative-control results must come from the corrected rewiring implementation, not superseded runs.

The mixed-effects analysis scripts are distributed under `scripts/`. Install their additional dependencies with `python -m pip install statsmodels patsy`, then inspect the available input and output options:

```bash
python scripts/gen_fig_paired_mixed_effects.py --help
python scripts/gen_fig_mixed_effects_by_condition.py --help
```

The paired script analyzes GES and WLS and generates a forest plot. The condition-oriented script analyzes nine metrics with six condition contrasts per metric and one Holm correction across 54 tests. Both retain incident-case pairing across runs. Their default outputs are under `runs/stability_test/statistical_analysis/paired_effects`. The paired script accepts structural input overrides through `--condition NAME=PATH`; the condition-oriented script uses the shared `DEFAULT_CONDITION_PATHS` mapping and accepts `--auxiliary-path` for auxiliary scores. Adjust that mapping if the condition-oriented structural inputs are stored elsewhere.

The local `figures/` directory remains Git-ignored. Experiment data, expert reference graphs, and the configured feedback snapshot must be supplied separately for full reproduction; see the experiment results link above.

See [prompt authoring](docs/prompt_authoring.md) and the [few-shot library](prompt/review_feedback/README.md) for additional documentation.
