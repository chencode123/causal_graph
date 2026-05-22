# Prompt Authoring Guide

Five core files govern the pipeline:

- `prompt/<step_key>.txt` — prompt template (task instructions and `{variable}` placeholders)
- `prompt/manifest.json` — prompt registration and variable declarations
- `pipeline/step_registry.py` — step metadata and `required_vars` mapping (variable → source)
- `pipeline/step_var_resolver.py` — variable resolution logic and auto-resolve naming conventions
- `batch_main_runner.py` — run configuration: `ACTIVE_STEP_KEYS`, few-shot settings, model params

## 0. One rule

Never write prompt content inside `step_var_resolver.py`.  
Prompts go in `prompt/<step_key>.txt` only.

## 1. Adding a new step

1. Create `prompt/<step_key>.txt` — write the task instructions and `{variable}` placeholders.

2. Update `prompt/manifest.json`:
   - `template_file`
   - `required_vars`
   - `optional_vars`

   Every `{variable}` in the template must be declared in manifest and vice versa.

3. Update `pipeline/step_registry.py`:
   - Add the same step key
   - Set `output_file`
   - Set `required_vars` (variable name → source address)
   - Optional: `default_params`

4. Add the step key to `ACTIVE_STEP_KEYS` in `batch_main_runner.py` to control execution order.

5. Run the sync tests:

```bash
pytest tests/test_prompt_keys_sync.py tests/test_prompt_vars_sync.py -q -p no:cacheprovider
```

Or use the project script (recommended):

```powershell
.\scripts\test_prompt.ps1
```

## 2. `required_vars` syntax

In `pipeline/step_registry.py`, `required_vars` is a mapping of variable name to source:

```python
"required_vars": {
    "identify_incident_output": "folder:identify_incident_output.txt",
    "hazards_consequence_json": "config:hazards_json",
    "identify_hazard_consequence_scheme": "project:scheme/identify_hazard_consequence_scheme.json"
}
```

Supported source prefixes:

- `folder:<filename>` — file under the current case folder
- `project:<relative path>` — file relative to the project root
- `config:hazards_json` — hazards JSON from run config
- `config:conditions_json` — conditions JSON from run config

### Auto-resolve conventions (explicit declaration optional)

`step_var_resolver.py` resolves variables automatically based on their name. No explicit source is needed in these cases:

| Variable name pattern | Resolves to |
|-----------------------|-------------|
| ends with `_output` | `folder/<var_name>.txt` |
| ends with `_scheme` | `project/scheme/<var_name>.json` |
| ends with `_schema` | `project/scheme/<var_name>.json` |
| ends with `_schema_definition` | `project/scheme/<var_name>.txt` |
| `incident_description` | text extracted from `identify_incident_output.json` |
| `identify_incident_output` | text extracted from `identify_incident_output.json` |
| `candidate_evidence_snippets` | extracted from `scenario_candidate_extraction_output.json` |
| `edge_candidate_evidence_snippets` | extracted from `edge_candidate_extraction_output.json` |

Only add an explicit source when the variable name does not match any rule above.

## 3. `ACTIVE_STEP_KEYS`

Execution order is controlled by `ACTIVE_STEP_KEYS` at the top of `batch_main_runner.py`:

```python
ACTIVE_STEP_KEYS = (
    "identify_hazard_consequence",
    "scenario_candidate_extraction",
    "scenario_structure_validation",
    "identify_accident_scenario",
    "edge_candidate_extraction",
    "edge_structure_validation",
    "causal_edge_linking",
    "review_causal_graph",   # auto-expands to graph_diagnosis + graph_revision_planning
)
```

`review_causal_graph` is a special alias — `get_active_step_keys()` automatically expands it into `graph_diagnosis` followed by `graph_revision_planning`. Do not write these two keys manually.

`pipeline/step_var_resolver.py` no longer contains `ACTIVE_STEP_KEYS`. Do not look there.

## 4. Few-shot configuration

Few-shot is configured in `batch_main_runner.py`:

```python
USE_FEW_SHOT = True  # global on/off switch

FEW_SHOT_PATTERN_FILES_BY_STEP = {
    "graph_diagnosis": (
        Path(r"prompt\review_feedback\case_coverage_12\review_feedback_analysis_few_shot_balanced_small.json"),
    ),
    "graph_revision_planning": (
        Path(r"prompt\review_feedback\case_coverage_12\review_feedback_analysis_few_shot_balanced_small.json"),
    ),
}
```

- When `USE_FEW_SHOT = False`, the `{few_shot_examples}` placeholder is replaced with an empty string for all steps.
- `FEW_SHOT_PATTERN_FILES_BY_STEP` only applies to `graph_diagnosis` and `graph_revision_planning`. Other steps receive few-shot examples via case directories.
- See `prompt/review_feedback/README.md` for the available few-shot files and their coverage.

## 5. When to edit `step_var_resolver.py`

Most steps do not require changes here. Edit only when:

- Adding a new source prefix (e.g. `env:`, `http:`)
- Extending the auto-resolve naming conventions
- Adding special extraction logic for a new variable (like `candidate_evidence_snippets`)

For a normal new step, only touch:
- the prompt file
- manifest
- step_registry
- `ACTIVE_STEP_KEYS` in `batch_main_runner.py`

## 6. Common errors

| Error | Meaning |
|-------|---------|
| `Missing key` | Key exists in `step_registry` but not in `manifest` |
| `Missing file` | `template_file` declared in manifest does not exist on disk |
| `Variable mismatch` | Template placeholders and manifest `required_vars` are out of sync |
| `Registry mismatch` | Variable names in `step_registry.required_vars` differ from those in `manifest.required_vars` |

## 7. What "2 passed" means

Running `.\scripts\test_prompt.ps1` (or the `pytest` command above) and seeing `2 passed` means both sync checks passed — `test_prompt_keys_sync.py` and `test_prompt_vars_sync.py`. It does not report how many prompt files exist.

To confirm a newly added prompt is covered, check that it appears in `prompt/manifest.json`, has a corresponding `prompt/*.txt` file, and is registered in `pipeline/step_registry.py`.
