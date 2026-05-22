# Causal Graph Extraction Pipeline

An LLM-powered pipeline that extracts causal graphs from process-safety incident reports. Given an incident description, the pipeline identifies hazards, scenarios, and causal edges, then builds and reviews a structured causal graph.

## Setup

1. **Install dependencies**

```bash
pip install -e .
```

2. **Configure API key**

Create a `.env_openai` file in the project root:

```
OPENAI_API_KEY=sk-...
```

3. **Check hazard/condition schemas**

The pipeline uses `prompt/hazards_consequence.json` and `prompt/conditions.json` as domain knowledge. Verify these match your use case before running.

## Running the pipeline

All run configuration is set at the top of `batch_main_runner.py`. Edit the constants there, then run:

```bash
python batch_main_runner.py
```

Key parameters:

| Parameter | Description |
|-----------|-------------|
| `BASE_DIR` | Input folder — a single `batch_*` dir or a parent containing multiple `batch_*` dirs |
| `EXECUTION_MODE` | `"batch"` (OpenAI Batch API) or `"responses"` (direct API, faster for debugging) |
| `ACTIVE_STEP_KEYS` | Which pipeline steps to run and in what order |
| `MODEL_NAME` | OpenAI model to use |
| `USE_FEW_SHOT` | Enable/disable few-shot examples |

## Pipeline steps

The pipeline runs steps in the order defined by `ACTIVE_STEP_KEYS`:

```
identify_hazard_consequence
causal_narrative_candidate_extraction
causal_narrative_structure_validation
causal_narrative_extraction
scenario_candidate_extraction
scenario_structure_validation
identify_accident_scenario
edge_candidate_extraction
edge_structure_validation
causal_edge_linking
review_causal_graph          ← expands to: graph_diagnosis + graph_revision_planning
```

Each step reads from the case folder, calls the LLM with a prompt template, and writes a `<step>_output.json` back to the same folder.

## Evaluation

```bash
# Structural similarity evaluation
python run_evaluation.py --folder <run_dir>

# Semantic similarity evaluation
python run_semantic_evaluation.py --parent-dir <run_dir>

# Stability evaluation (multi-round consistency)
python run_stability_evaluation.py --folder <stability_run_dir>
```

## Project structure

```
batch_main_runner.py   — run configuration and entrypoint
pipeline/              — core pipeline logic
prompt/                — prompt templates and manifest
  manifest.json        — prompt registration
  hazards_consequence.json / conditions.json  — domain schemas
  review_feedback/     — few-shot example library
scheme/                — output JSON schemas
scripts/               — evaluation and analysis scripts
utils/                 — shared utilities
runs/                  — pipeline outputs (git-ignored)
```

## Documentation

- [Prompt authoring guide](docs/prompt_authoring.md) — how to add or modify pipeline steps
- [Few-shot library](prompt/review_feedback/README.md) — available few-shot sets for graph review steps
