# Causal Graph Extraction Pipeline

Extract and evaluate process-safety causal graphs from incident descriptions using a frozen ontology and LLM prompts.

## Setup

Run from the repository root in a Python environment with the project dependencies:

```bash
pip install -e .
```

The evaluation tools additionally require NumPy, SciPy, pandas, matplotlib, NetworkX, and GraKeL. The main pipeline runners currently use Windows `winsound`. The published dependency list is not a frozen environment lockfile.

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

These entry points retain experiment-specific paths and recovery settings; they are not a turnkey fresh-corpus run:

- `batch_main_runner.py` resumes few-shot Round 4 and then resumes or creates Round 5. Its feedback file is configured under the locally supplied `runs/few-shot/` tree.
- `batch_main_runner_no_few_shot.py` uses Round 4 as the source for Round 5.
- `baseline_single_pass_runner.py` prepares five runs from `runs/stability_test/batched_reports` and writes to `runs/single_pass_baseline_all_batches`. The final evaluator expects `runs/stability_test/single_pass_baseline_all_batches`; align these paths before running.
- `no_revision_runner.py` defaults to dry-run. It reuses prepared scenario-candidate artifacts from the source rounds to execute the isolated edge-candidate stage. Consult `--help` for execution options.

Configure source and output folders, run counts, case selection, and few-shot input paths before launching. Supply the required prepared case inputs and reference graphs separately. Keep model, inference settings, prompt versions, and schemas fixed across retained runs. Generation invokes paid API requests, except for the No Revision dry-run.

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
| `scripts/` | Nine retained reproducibility scripts listed below |
| `tests/` | Focused implementation checks |
| `runs/` | Local inputs, generated graphs, references, and results; not distributed by Git |

Retained scripts:

```text
copy_reference_graphs_to_baseline.py
evaluate_soft_matching_api.py
evaluate_topology_negative_controls.py
evaluation_structure_similarity.py
generate_results_table.py
plot_graph_structure_factors.py
plot_stability_comparison_boxplot.py
plot_topology_negative_controls.py
scrape_csb_completed_reports.py
```

The CSB catalogue scraper records public catalogue metadata; it does not assign corpus inclusion decisions. Reference copying defaults to dry-run and matches exact case identifiers. Negative-control results must come from the corrected rewiring implementation, not superseded runs.

The local `figures/` directory is currently Git-ignored, including the mixed-effects analysis scripts. The repository therefore does not yet distribute the complete inferential analysis and all manuscript figure sources. Experiment data, expert reference graphs, and the configured feedback snapshot must also be supplied separately for full reproduction.

See [prompt authoring](docs/prompt_authoring.md) and the [few-shot library](prompt/review_feedback/README.md) for additional documentation.
